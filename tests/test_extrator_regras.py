import json
from pathlib import Path

from ingestao.contrato import Chunk
from ingestao.extrator_regras import extrair_do_chunk, montar_prompt, processar
from ingestao.persistencia import ler_jsonl

TEXTO = "4.2 Solo gnaisse. A saturacao ocorre a partir de 100mm em 72h."


def _chunk(chunk_id: str = "c1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc="laudo.pdf",
        pagina=12,
        secao="4.2 Caracterizacao do solo",
        texto=TEXTO,
    )


def _gerador(payload: dict):
    def gerar(_prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    return gerar


def _uma_regra(valor: float = 100.0, trecho: str = "saturacao ocorre a partir de 100mm em 72h") -> dict:
    return {
        "regras": [
            {
                "dominio": "geologia",
                "entidade_tipo": "tipo_solo",
                "entidade_nome": "gnaisse",
                "grandeza": "chuva_acumulada",
                "janela_horas": 72,
                "unidade": "mm",
                "nivel": "critico",
                "valor": valor,
                "fonte_trecho": trecho,
            }
        ]
    }


def test_prompt_contem_o_texto_e_a_secao_do_chunk():
    prompt = montar_prompt(_chunk())

    assert TEXTO in prompt
    assert "4.2 Caracterizacao do solo" in prompt


def test_extrair_anexa_procedencia_que_nao_veio_do_modelo():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert len(regras) == 1
    assert regras[0].fonte_doc == "laudo.pdf"
    assert regras[0].fonte_pagina == 12
    assert regras[0].fonte_secao == "4.2 Caracterizacao do solo"
    assert regras[0].chunk_id == "c1"


def test_regra_boa_recebe_status_ok():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert regras[0].status == "ok"


def test_citacao_inventada_recebe_status_suspeito():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra(trecho="800mm em 24h")))

    assert regras[0].status == "suspeito"
    assert "trecho" in regras[0].motivo_suspeita


def test_valor_implausivel_recebe_status_suspeito():
    payload = _uma_regra(valor=90000.0, trecho="saturacao ocorre a partir de 100mm em 72h")
    regras = extrair_do_chunk(_chunk(), _gerador(payload))

    assert regras[0].status == "suspeito"


def test_lista_vazia_e_resultado_legitimo():
    assert extrair_do_chunk(_chunk(), _gerador({"regras": []})) == []


def test_regra_id_e_estavel_entre_execucoes():
    primeira = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))
    segunda = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert primeira[0].regra_id == segunda[0].regra_id


def test_processar_grava_regras_e_conta(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"

    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes)

    assert resumo["regras"] == 1
    assert resumo["chunks_processados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_processar_retoma_e_pula_chunk_ja_feito(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    processar([_chunk()], _gerador(_uma_regra()), saida, omissoes)

    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes)

    assert resumo["chunks_pulados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_chunk_com_limiar_e_zero_regras_vai_para_omissoes(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"

    resumo = processar([_chunk()], _gerador({"regras": []}), saida, omissoes)

    assert resumo["omissoes"] == 1
    assert ler_jsonl(omissoes)[0]["chunk_id"] == "c1"
