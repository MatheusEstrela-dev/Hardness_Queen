from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ingestao.persistencia import escrever_jsonl, ler_jsonl
from ingestao.revisao.app import criar_app


def _regra(
    regra_id: str,
    valor_min: float | None = 100.0,
    valor_max: float | None = None,
    *,
    janela_horas: int | None = 72,
    fonte_doc: str = "laudo.pdf",
    status: str = "ok",
    motivo_suspeita: str | None = None,
) -> dict:
    return {
        "regra_id": regra_id,
        "chunk_id": "c1",
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": janela_horas,
        "unidade": "mm",
        "escala": "alerta_cor",
        "nivel": "roxo",
        "valor_min": valor_min,
        "valor_max": valor_max,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
        "fonte_doc": fonte_doc,
        "fonte_pagina": 12,
        "fonte_secao": "4.2 Caracterizacao do solo",
        "origem": "modelo",
        "status": status,
        "motivo_suspeita": motivo_suspeita,
    }


@pytest.fixture
def ambiente(tmp_path: Path):
    propostas = tmp_path / "propostas.jsonl"
    decisoes = tmp_path / "decisoes.jsonl"
    aprovadas = tmp_path / "aprovadas.jsonl"
    # r2 usa valor_min diferente de r1 de proposito: sem isso as duas regras
    # desta fixture compartilhariam a mesma chave de limiar (agrupamento.py,
    # CAMPOS_CHAVE_LIMIAR) por coincidencia de todos os outros campos serem
    # iguais, e virariam UM grupo de 2 fontes em vez de dois itens
    # independentes -- o que quebraria os testes abaixo que dependem de
    # r1/r2 serem duas pendencias distintas. Os testes de agrupamento em si
    # tem fixtures proprias mais adiante.
    escrever_jsonl(propostas, [_regra("r1"), _regra("r2", valor_min=200.0)])
    cliente = TestClient(criar_app(propostas, decisoes, aprovadas))
    return cliente, decisoes, aprovadas


def _ambiente_em(tmp_path: Path, regras: list[dict]):
    propostas = tmp_path / "propostas.jsonl"
    decisoes = tmp_path / "decisoes.jsonl"
    aprovadas = tmp_path / "aprovadas.jsonl"
    escrever_jsonl(propostas, regras)
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
    assert corpo["pendentes"][0]["fontes"][0]["regra_id"] == "r2"


def test_aprovada_entra_no_arquivo_de_aprovadas(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})

    grupos = ler_jsonl(aprovadas)
    assert len(grupos) == 1
    assert [f["regra_id"] for f in grupos[0]["fontes"]] == ["r1"]


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

    grupo = ler_jsonl(aprovadas)[0]
    assert grupo["valor_min"] == 6.0
    assert grupo["valor_max"] == 30.0
    fonte = grupo["fontes"][0]
    assert fonte["valor_min_original"] == 100.0
    assert fonte["valor_max_original"] is None


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

    grupo = ler_jsonl(aprovadas)[0]
    assert grupo["valor_min"] == 90.0
    assert grupo["valor_max"] is None


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

    grupos_aprovadas = ler_jsonl(aprovadas)
    assert len(grupos_aprovadas) == 1
    assert grupos_aprovadas[0]["valor_min"] == 6.0
    assert grupos_aprovadas[0]["valor_max"] == 30.0
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

    grupos = ler_jsonl(aprovadas)
    assert [f["regra_id"] for f in grupos[0]["fontes"]] == ["r1"]
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


# --- Agrupamento por limiar -------------------------------------------------
#
# 81 regras propostas num run real colapsam para 67 limiares distintos: 14
# regras repetem um limiar ja afirmado por outro documento. A fila deve
# mostrar UM item por limiar, com todas as fontes que o corroboram, nao um
# item por ocorrencia.


def test_tres_regras_mesmo_limiar_viram_um_grupo_com_tres_fontes(tmp_path):
    cliente, _, _ = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0, fonte_doc="docA.docx"),
        _regra("r2", valor_min=6.0, valor_max=30.0, fonte_doc="docB.pdf"),
        _regra("r3", valor_min=6.0, valor_max=30.0, fonte_doc="docC.docx"),
    ])

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 1
    grupo = corpo["pendentes"][0]
    assert grupo["total_fontes"] == 3
    assert {f["regra_id"] for f in grupo["fontes"]} == {"r1", "r2", "r3"}
    assert {f["fonte_doc"] for f in grupo["fontes"]} == {"docA.docx", "docB.pdf", "docC.docx"}


def test_duas_regras_com_valor_max_diferente_viram_dois_grupos(tmp_path):
    cliente, _, _ = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0),
        _regra("r2", valor_min=6.0, valor_max=70.0),
    ])

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 2


def test_duas_regras_com_janela_horas_diferente_viram_dois_grupos(tmp_path):
    cliente, _, _ = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=100.0, janela_horas=24),
        _regra("r2", valor_min=100.0, janela_horas=72),
    ])

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 2


def test_grupo_com_uma_fonte_suspeita_e_outra_ok_surge_status_misto(tmp_path):
    cliente, _, _ = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0, status="ok"),
        _regra(
            "r2",
            valor_min=6.0,
            valor_max=30.0,
            fonte_doc="outro.pdf",
            status="suspeito",
            motivo_suspeita="valor nao aparece no trecho citado",
        ),
    ])

    corpo = cliente.get("/api/pendentes").json()

    grupo = corpo["pendentes"][0]
    # O grupo nao pode parecer limpo so porque uma das duas fontes e ok --
    # esconder a suspeita dentro de uma media otimista seria pior que a
    # duplicacao que o agrupamento substitui.
    assert grupo["status"] == "suspeito"
    status_por_fonte = {f["regra_id"]: f["status"] for f in grupo["fontes"]}
    assert status_por_fonte == {"r1": "ok", "r2": "suspeito"}
    fonte_suspeita = next(f for f in grupo["fontes"] if f["regra_id"] == "r2")
    assert fonte_suspeita["motivo_suspeita"] == "valor nao aparece no trecho citado"


def test_aprovar_grupo_grava_uma_linha_em_aprovadas_com_tres_fontes(tmp_path):
    cliente, _, aprovadas = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0, fonte_doc="docA.docx"),
        _regra("r2", valor_min=6.0, valor_max=30.0, fonte_doc="docB.pdf"),
        _regra("r3", valor_min=6.0, valor_max=30.0, fonte_doc="docC.docx"),
    ])

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_ids": ["r1", "r2", "r3"], "veredito": "aprovado", "revisor": "matheus"},
    )

    assert resposta.status_code == 200
    grupos = ler_jsonl(aprovadas)
    assert len(grupos) == 1
    assert {f["regra_id"] for f in grupos[0]["fontes"]} == {"r1", "r2", "r3"}


def test_aprovar_grupo_grava_tres_decisoes_mesmo_revisor_e_timestamp(tmp_path):
    cliente, decisoes, _ = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0, fonte_doc="docA.docx"),
        _regra("r2", valor_min=6.0, valor_max=30.0, fonte_doc="docB.pdf"),
        _regra("r3", valor_min=6.0, valor_max=30.0, fonte_doc="docC.docx"),
    ])

    cliente.post(
        "/api/decisao",
        json={"regra_ids": ["r1", "r2", "r3"], "veredito": "aprovado", "revisor": "matheus"},
    )

    registros = ler_jsonl(decisoes)
    assert len(registros) == 3
    assert {r["regra_id"] for r in registros} == {"r1", "r2", "r3"}
    assert len({r["revisor"] for r in registros}) == 1
    assert len({r["decidido_em"] for r in registros}) == 1


def test_grupo_decidido_nao_reaparece_na_fila(tmp_path):
    cliente, _, _ = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0, fonte_doc="docA.docx"),
        _regra("r2", valor_min=6.0, valor_max=30.0, fonte_doc="docB.pdf"),
        _regra("r3", valor_min=6.0, valor_max=30.0, fonte_doc="docC.docx"),
    ])

    cliente.post(
        "/api/decisao",
        json={"regra_ids": ["r1", "r2", "r3"], "veredito": "aprovado", "revisor": "matheus"},
    )

    corpo = cliente.get("/api/pendentes").json()
    assert corpo["total"] == 0


def test_regra_id_desconhecido_no_grupo_devolve_404_e_nao_escreve_nada(tmp_path):
    cliente, decisoes, aprovadas = _ambiente_em(tmp_path, [
        _regra("r1", valor_min=6.0, valor_max=30.0, fonte_doc="docA.docx"),
        _regra("r2", valor_min=6.0, valor_max=30.0, fonte_doc="docB.pdf"),
    ])

    resposta = cliente.post(
        "/api/decisao",
        json={
            "regra_ids": ["r1", "r2", "inexistente"],
            "veredito": "aprovado",
            "revisor": "matheus",
        },
    )

    assert resposta.status_code == 404
    assert ler_jsonl(decisoes) == []
    assert ler_jsonl(aprovadas) == []
