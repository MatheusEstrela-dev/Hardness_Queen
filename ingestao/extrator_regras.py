from pathlib import Path
from typing import Callable

from ingestao.contrato import Chunk, Extracao, Regra
from ingestao.identidade import regra_id
from ingestao.persistencia import anexar_jsonl, ids_ja_vistos
from ingestao.validacao import classificar, suspeito_de_omissao

# Qwen2.5-7B-Instruct e Qwen2.5-3B-Instruct nao couberam no tempo de sessao
# disponivel: o link desta estacao entrega a CDN da Hugging Face a cerca de
# 1,71 MB/s agregado (medido em 4 fragmentos paralelos), o que estima cerca de
# 2h para os ~15GB do 7B-Instruct. O Qwen2.5-3B (variante base, sem
# instruction tuning) ja estava em disco por causa do treino de
# scripts/02_treinar_modelo.py, entao a medicao de VRAM e tempo por chunk
# desta tarefa usa esse modelo. Ver secao 10 da spec para o registro completo
# e a ressalva sobre qualidade de extracao de um modelo base.
MODELO_PADRAO = "Qwen/Qwen2.5-3B"
SEMENTE = 42
MAX_TOKENS_DE_SAIDA = 1024

INSTRUCAO = """Voce extrai limiares tecnicos de laudos da Defesa Civil.

Extraia do trecho abaixo TODOS os limiares numericos que disparam atencao ou
alerta. Para cada um, copie em fonte_trecho o pedaco EXATO do texto original que
sustenta o numero, sem reescrever nem resumir.

Se o trecho nao fixa limiar algum, devolva a lista vazia. Nao invente limiar que
nao esteja escrito, e nao converta unidade.

Secao: {secao}

Trecho:
{texto}
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
                    extraida.valor,
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
) -> dict:
    ja_feitos = ids_ja_vistos(saida, "chunk_id") | ids_ja_vistos(omissoes, "chunk_id")

    resumo = {"chunks_processados": 0, "chunks_pulados": 0, "regras": 0, "suspeitas": 0, "omissoes": 0}
    for chunk in chunks:
        if chunk.chunk_id in ja_feitos:
            resumo["chunks_pulados"] += 1
            continue

        regras = extrair_do_chunk(chunk, gerar)
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
        # a determinacao aqui vem de temperature=0 (decodificacao gulosa) mais
        # o torch.manual_seed acima, chamado uma vez na criacao do gerador.
        return gerador(
            prompt,
            max_new_tokens=MAX_TOKENS_DE_SAIDA,
            temperature=0,
        )

    return gerar
