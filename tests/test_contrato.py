import pytest
from pydantic import ValidationError

from ingestao.contrato import Chunk, Extracao, Regra, RegraExtraida


def _regra_valida() -> dict:
    return {
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "nivel": "critico",
        "valor": 100.0,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
    }


def test_regra_extraida_aceita_payload_valido():
    regra = RegraExtraida(**_regra_valida())

    assert regra.valor == 100.0


def test_regra_extraida_rejeita_dominio_desconhecido():
    payload = _regra_valida()
    payload["dominio"] = "meteorologia_marinha"

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_regra_extraida_rejeita_unidade_desconhecida():
    payload = _regra_valida()
    payload["unidade"] = "polegadas"

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_janela_horas_pode_ser_nula():
    payload = _regra_valida()
    payload["janela_horas"] = None

    assert RegraExtraida(**payload).janela_horas is None


def test_extracao_aceita_lista_vazia():
    assert Extracao(regras=[]).regras == []


def test_regra_carrega_procedencia_e_status():
    regra = Regra(
        **_regra_valida(),
        regra_id="r1",
        chunk_id="c1",
        fonte_doc="laudo.pdf",
        fonte_pagina=12,
        fonte_secao="4.2 Caracterizacao do solo",
        status="ok",
    )

    assert regra.fonte_pagina == 12
    assert regra.motivo_suspeita is None


def test_chunk_aceita_pagina_nula():
    chunk = Chunk(chunk_id="c1", doc="laudo.docx", pagina=None, secao="1 Introducao", texto="x")

    assert chunk.pagina is None
