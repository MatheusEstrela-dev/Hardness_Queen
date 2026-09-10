from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ingestao.persistencia import escrever_jsonl, ler_jsonl
from ingestao.revisao.app import criar_app


def _regra(regra_id: str, valor_min: float | None = 100.0, valor_max: float | None = None) -> dict:
    return {
        "regra_id": regra_id,
        "chunk_id": "c1",
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "escala": "alerta_cor",
        "nivel": "roxo",
        "valor_min": valor_min,
        "valor_max": valor_max,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
        "fonte_doc": "laudo.pdf",
        "fonte_pagina": 12,
        "fonte_secao": "4.2 Caracterizacao do solo",
        "origem": "modelo",
        "status": "ok",
        "motivo_suspeita": None,
    }


@pytest.fixture
def ambiente(tmp_path: Path):
    propostas = tmp_path / "propostas.jsonl"
    decisoes = tmp_path / "decisoes.jsonl"
    aprovadas = tmp_path / "aprovadas.jsonl"
    escrever_jsonl(propostas, [_regra("r1"), _regra("r2")])
    cliente = TestClient(criar_app(propostas, decisoes, aprovadas))
    return cliente, decisoes, aprovadas


def test_fila_lista_todas_as_pendentes(ambiente):
    cliente, _, _ = ambiente

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 2


def test_aprovar_grava_decisao_com_revisor(ambiente):
    cliente, decisoes, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"},
    )

    assert resposta.status_code == 200
    registro = ler_jsonl(decisoes)[0]
    assert registro["regra_id"] == "r1"
    assert registro["revisor"] == "matheus"
    assert registro["decidido_em"]


def test_regra_decidida_sai_da_fila(ambiente):
    cliente, _, _ = ambiente
    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 1
    assert corpo["pendentes"][0]["regra_id"] == "r2"


def test_aprovada_entra_no_arquivo_de_aprovadas(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})

    assert [r["regra_id"] for r in ler_jsonl(aprovadas)] == ["r1"]


def test_rejeitada_nao_entra_nas_aprovadas(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "rejeitado", "revisor": "matheus"})

    assert ler_jsonl(aprovadas) == []


def test_correcao_da_faixa_entra_nas_aprovadas_com_os_extremos_novos(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post(
        "/api/decisao",
        json={
            "regra_id": "r1",
            "veredito": "corrigido",
            "valor_min_corrigido": 6.0,
            "valor_max_corrigido": 30.0,
            "revisor": "matheus",
        },
    )

    aprovada = ler_jsonl(aprovadas)[0]
    assert aprovada["valor_min"] == 6.0
    assert aprovada["valor_max"] == 30.0
    assert aprovada["valor_min_original"] == 100.0
    assert aprovada["valor_max_original"] is None


def test_correcao_pode_deixar_um_extremo_sem_limite(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post(
        "/api/decisao",
        json={
            "regra_id": "r1",
            "veredito": "corrigido",
            "valor_min_corrigido": 90.0,
            "valor_max_corrigido": None,
            "revisor": "matheus",
        },
    )

    aprovada = ler_jsonl(aprovadas)[0]
    assert aprovada["valor_min"] == 90.0
    assert aprovada["valor_max"] is None


def test_decisao_para_regra_inexistente_devolve_404(ambiente):
    cliente, decisoes, aprovadas = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "inexistente", "veredito": "aprovado", "revisor": "matheus"},
    )

    assert resposta.status_code == 404
    # 404 precisa acontecer ANTES de qualquer escrita -- nem a trilha de
    # auditoria nem o derivado podem registrar uma decisao para uma regra
    # que nao existe nas propostas.
    assert ler_jsonl(decisoes) == []
    assert ler_jsonl(aprovadas) == []


def test_duas_decisoes_para_a_mesma_regra_geram_uma_linha_em_aprovadas_com_a_ultima(ambiente):
    cliente, decisoes, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})
    cliente.post(
        "/api/decisao",
        json={
            "regra_id": "r1",
            "veredito": "corrigido",
            "valor_min_corrigido": 6.0,
            "valor_max_corrigido": 30.0,
            "revisor": "matheus",
        },
    )

    registros_aprovadas = ler_jsonl(aprovadas)
    assert len(registros_aprovadas) == 1
    assert registros_aprovadas[0]["valor_min"] == 6.0
    assert registros_aprovadas[0]["valor_max"] == 30.0
    # decisoes.jsonl e a trilha de auditoria -- append-only, nunca perde
    # uma decisao mesmo quando ela e substituida no derivado.
    assert len(ler_jsonl(decisoes)) == 2


def test_aprovar_depois_rejeitar_deixa_a_regra_fora_de_aprovadas(ambiente):
    cliente, decisoes, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})
    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "rejeitado", "revisor": "matheus"})

    assert ler_jsonl(aprovadas) == []
    assert len(ler_jsonl(decisoes)) == 2


def test_rejeitar_depois_aprovar_deixa_a_regra_dentro_de_aprovadas(ambiente):
    cliente, decisoes, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "rejeitado", "revisor": "matheus"})
    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})

    assert [r["regra_id"] for r in ler_jsonl(aprovadas)] == ["r1"]
    assert len(ler_jsonl(decisoes)) == 2


def test_corrigido_sem_nenhum_extremo_devolve_422(ambiente):
    cliente, decisoes, aprovadas = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={
            "regra_id": "r1",
            "veredito": "corrigido",
            "valor_min_corrigido": None,
            "valor_max_corrigido": None,
            "revisor": "matheus",
        },
    )

    assert resposta.status_code == 422
    # Rejeitado antes da validacao do pydantic -- nao pode aprovar o valor
    # original da regra em silencio nem registrar a tentativa na trilha.
    assert ler_jsonl(decisoes) == []
    assert ler_jsonl(aprovadas) == []


def test_revisor_vazio_devolve_422(ambiente):
    cliente, decisoes, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "aprovado", "revisor": ""},
    )

    assert resposta.status_code == 422
    assert ler_jsonl(decisoes) == []


def test_revisor_so_com_espacos_devolve_422(ambiente):
    cliente, decisoes, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "aprovado", "revisor": "   "},
    )

    assert resposta.status_code == 422
    assert ler_jsonl(decisoes) == []


def test_veredito_invalido_e_recusado_na_validacao(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "talvez", "revisor": "matheus"},
    )

    assert resposta.status_code == 422


def test_pagina_de_revisao_responde(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_pagina_mostra_fonte_secao_na_grade_de_campos(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.get("/")

    assert "fonte_secao" in resposta.text


def test_pagina_mostra_escala_na_grade_de_campos(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.get("/")

    assert "escala" in resposta.text


def test_pagina_mostra_origem_na_grade_de_campos(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.get("/")

    assert "origem" in resposta.text
