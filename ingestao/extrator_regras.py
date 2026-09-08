from pathlib import Path
from typing import Callable

from ingestao.contrato import Chunk, Extracao, Regra
from ingestao.identidade import regra_id
from ingestao.persistencia import anexar_jsonl, ids_ja_vistos
from ingestao.validacao import classificar, suspeito_de_omissao

MODELO_PADRAO = "Qwen/Qwen2.5-7B-Instruct"
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
        return gerador(
            prompt,
            max_new_tokens=MAX_TOKENS_DE_SAIDA,
            temperature=0,
            seed=SEMENTE,
        )

    return gerar
