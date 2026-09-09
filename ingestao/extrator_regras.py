from pathlib import Path
from typing import Callable

from ingestao.contrato import Chunk, Extracao, Regra
from ingestao.identidade import regra_id
from ingestao.persistencia import anexar_jsonl, ids_ja_vistos
from ingestao.validacao import classificar, suspeito_de_omissao

# Modelo de producao: scripts/04_extrair_regras.py chama
# criar_gerador_qwen() sem argumento e herda esta constante, entao ela precisa
# continuar sendo a variante Instruct -- e a que sabe seguir a instrucao de
# extrair TODOS os limiares, nao so notar que existe um numero no texto.
#
# A medicao de VRAM e tempo por chunk contra este modelo (ver secao 10 da
# spec) foi feita com os pesos completos em disco, em tests/test_extracao_real.py,
# que chama criar_gerador_qwen() sem argumento para medir exatamente o que
# producao executa.
MODELO_PADRAO = "Qwen/Qwen2.5-7B-Instruct"
SEMENTE = 42
MAX_TOKENS_DE_SAIDA = 1024

INSTRUCAO = """Voce extrai limiares tecnicos de laudos da Defesa Civil.

Trecho ({secao}):
{texto}

Extraia TODOS os limiares numericos do trecho acima. Em fonte_trecho copie o
pedaco EXATO que sustenta o numero. Faixa "entre X e Y" e UMA regra com
valor_min=X e valor_max=Y; "acima de X" preenche so valor_min.
"<= X", "ate X", "no maximo X" ou "abaixo de X" preenche so valor_max, sem inventar zero em valor_min.
Niveis por cor: verde, amarelo, laranja, vermelho, roxo (menos para mais grave).
Limiar valido para todo o estado usa entidade_tipo="estado" e
entidade_nome="minas gerais", em vez de inventar entidade que o texto nao nomeia.
"""


def montar_prompt(chunk: Chunk) -> str:
    return INSTRUCAO.format(secao=chunk.secao or "nao identificada", texto=chunk.texto)


def extrair_do_chunk(chunk: Chunk, gerar: Callable[[str], str]) -> list[Regra]:
    bruto = gerar(montar_prompt(chunk))
    extracao = Extracao.model_validate_json(bruto)

    regras: list[Regra] = []
    for extraida in extracao.regras:
        status, motivo = classificar(extraida, chunk.texto)
        regras.append(
            Regra(
                **extraida.model_dump(),
                regra_id=regra_id(
                    chunk.chunk_id,
                    extraida.entidade_tipo,
                    extraida.entidade_nome,
                    extraida.grandeza,
                    extraida.nivel,
                    extraida.valor_min,
                    extraida.valor_max,
                ),
                chunk_id=chunk.chunk_id,
                fonte_doc=chunk.doc,
                fonte_pagina=chunk.pagina,
                fonte_secao=chunk.secao,
                status=status,
                motivo_suspeita=motivo,
            )
        )
    return regras


def processar(
    chunks: list[Chunk],
    gerar: Callable[[str], str],
    saida: Path,
    omissoes: Path,
    falhas: Path,
) -> dict:
    # falhas entra no conjunto de "ja feitos" igual a saida e omissoes: um
    # chunk que falhou (OOM, JSON truncado) nao e retentado numa
    # reexecucao automatica. Apagar data/possiveis_falhas.jsonl e o jeito
    # do operador forcar nova tentativa -- util porque OOM pode ser
    # transitorio (outro processo liberou VRAM) enquanto um chunk
    # malformado nao muda sozinho.
    ja_feitos = ids_ja_vistos(saida, "chunk_id") | ids_ja_vistos(omissoes, "chunk_id") | ids_ja_vistos(
        falhas, "chunk_id"
    )

    resumo = {
        "chunks_processados": 0,
        "chunks_pulados": 0,
        "regras": 0,
        "suspeitas": 0,
        "omissoes": 0,
        "falhas": 0,
    }
    for chunk in chunks:
        if chunk.chunk_id in ja_feitos:
            resumo["chunks_pulados"] += 1
            continue

        try:
            regras = extrair_do_chunk(chunk, gerar)
        except Exception as erro:
            # Exception, nao BaseException: KeyboardInterrupt e SystemExit
            # precisam continuar propagando para o operador poder parar um
            # lote longo. Nada desaparece em silencio -- mesma convencao da
            # etapa 03 (erro_extracao no manifesto, ver 21d1b6c).
            anexar_jsonl(
                falhas,
                {"chunk_id": chunk.chunk_id, "doc": chunk.doc, "pagina": chunk.pagina, "erro": str(erro)},
            )
            resumo["falhas"] += 1
            print(f"[falha] chunk {chunk.chunk_id} ({chunk.doc}, pagina {chunk.pagina}): {erro}")
            continue

        for regra in regras:
            anexar_jsonl(saida, regra.model_dump())
            resumo["regras"] += 1
            if regra.status == "suspeito":
                resumo["suspeitas"] += 1

        if suspeito_de_omissao(chunk.texto, len(regras)):
            anexar_jsonl(
                omissoes,
                {"chunk_id": chunk.chunk_id, "doc": chunk.doc, "pagina": chunk.pagina, "texto": chunk.texto},
            )
            resumo["omissoes"] += 1

        resumo["chunks_processados"] += 1
    return resumo


def criar_gerador_qwen(model_id: str = MODELO_PADRAO) -> Callable[[str], str]:
    import outlines
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    # Efeito colateral: torch.manual_seed muda o estado global do gerador de
    # numeros aleatorios do processo, nao so deste gerador. Inofensivo aqui
    # porque a decodificacao e gulosa (do_sample=False), mas quem compartilhar
    # o processo com outro codigo que depende de aleatoriedade (ex.: o script
    # de treino) nao deveria esperar isso.
    torch.manual_seed(SEMENTE)

    quantizacao = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    modelo = outlines.from_transformers(
        AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=quantizacao,
            dtype=torch.bfloat16,
            device_map="cuda:0",
        ),
        AutoTokenizer.from_pretrained(model_id),
    )
    gerador = outlines.Generator(modelo, Extracao)

    def gerar(prompt: str) -> str:
        # outlines 1.3.3 repassa kwargs de inferencia direto para
        # transformers.generate(), que valida a lista contra a assinatura de
        # prepare_inputs_for_generation e rejeita chaves desconhecidas.
        # "seed" nao esta nessa lista (ValueError: model_kwargs nao usado) --
        # a determinacao aqui vem de do_sample=False (decodificacao gulosa)
        # mais o torch.manual_seed acima, chamado uma vez na criacao do
        # gerador.
        #
        # do_sample=False precisa ser explicito, nao um efeito colateral de
        # temperature=0. O generation_config default varia por modelo: o
        # Qwen2.5-3B base vem com do_sample=False (temperature ignorada, entao
        # temperature=0 passava batido por acidente), mas todo variante
        # Instruct -- incluindo o Qwen2.5-7B-Instruct de producao -- vem com
        # do_sample=True e temperature=0.7. Com do_sample=True, transformers
        # monta um TemperatureLogitsWarper e temperature=0 vira
        # "ValueError: `temperature` (=0) has to be a strictly positive
        # float". Pedir do_sample=False funciona independente do modelo, que
        # e exatamente o que a decodificacao gulosa deste projeto precisa.
        return gerador(
            prompt,
            max_new_tokens=MAX_TOKENS_DE_SAIDA,
            do_sample=False,
        )

    return gerar
