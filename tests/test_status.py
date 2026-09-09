import json
from pathlib import Path

import scripts.status as status


def _escrever_jsonl(caminho: Path, registros: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arquivo:
        for registro in registros:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _regra_proposta(**sobrescritas) -> dict:
    payload = {
        "dominio": "hidrologia",
        "entidade_tipo": "estado",
        "entidade_nome": "minas gerais",
        "grandeza": "chuva_acumulada",
        "janela_horas": 1,
        "unidade": "mm",
        "escala": "alerta_cor",
        "nivel": "amarelo",
        "valor_min": 6.0,
        "valor_max": 30.0,
        "fonte_trecho": "podendo variar entre 6 mm e 30 mm em uma hora",
        "regra_id": "r1",
        "chunk_id": "c1",
        "fonte_doc": "doc.docx",
        "fonte_pagina": None,
        "fonte_secao": "secao 1",
        "status": "ok",
        "motivo_suspeita": None,
    }
    payload.update(sobrescritas)
    return payload


def _preparar_pastas(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    propostas = tmp_path / "regras_propostas.jsonl"
    pasta_chunks = tmp_path / "chunks"
    pasta_chunks.mkdir()
    monkeypatch.setattr(status, "PROPOSTAS", propostas)
    monkeypatch.setattr(status, "PASTA_CHUNKS", pasta_chunks)
    return propostas, pasta_chunks


def test_regras_imprime_contagem_por_escala(tmp_path, monkeypatch, capsys):
    propostas, _pasta_chunks = _preparar_pastas(tmp_path, monkeypatch)
    monkeypatch.setattr(status, "DECISOES", tmp_path / "decisoes.jsonl")
    monkeypatch.setattr(status, "APROVADAS", tmp_path / "aprovadas.jsonl")
    _escrever_jsonl(
        propostas,
        [
            _regra_proposta(regra_id="r1", escala="alerta_cor"),
            _regra_proposta(regra_id="r2", escala="alerta_cor"),
            _regra_proposta(
                regra_id="r3",
                escala="intensidade",
                nivel="moderada",
                grandeza="taxa_precipitacao",
                unidade="mm/h",
                fonte_trecho="Moderada 6 mm/h a 30 mm/h",
            ),
        ],
    )

    status.regras()

    saida = capsys.readouterr().out
    linhas_de_escala = {
        linha.split()[1]: int(linha.split()[2])
        for linha in saida.splitlines()
        if linha.strip().startswith("escala ")
    }
    assert linhas_de_escala == {"alerta_cor": 2, "intensidade": 1}


def test_reclassificar_marca_suspeito_regra_ok_cujos_numeros_nao_estao_no_trecho(tmp_path, monkeypatch, capsys):
    propostas, pasta_chunks = _preparar_pastas(tmp_path, monkeypatch)

    # excerto real mas sem os numeros da faixa -- a fabricacao que o
    # trecho_confere e o valor_plausivel deixavam passar como "ok".
    _escrever_jsonl(
        propostas,
        [
            _regra_proposta(
                valor_min=26.0,
                valor_max=50.0,
                fonte_trecho="Situacao de Perigo, a severidade e alta. Ameaca a vida ou a propriedade.",
                status="ok",
                motivo_suspeita=None,
            )
        ],
    )
    _escrever_jsonl(
        pasta_chunks / "doc.jsonl",
        [
            {
                "chunk_id": "c1",
                "doc": "doc.docx",
                "pagina": None,
                "secao": "secao 1",
                "texto": "Situacao de Perigo, a severidade e alta. Ameaca a vida ou a propriedade.",
            }
        ],
    )

    status.reclassificar()

    atualizadas = [json.loads(linha) for linha in propostas.read_text(encoding="utf-8").splitlines()]
    assert atualizadas[0]["status"] == "suspeito"
    assert "valor_min" in atualizadas[0]["motivo_suspeita"]


def test_reclassificar_marca_suspeito_quando_chunk_de_origem_sumiu(tmp_path, monkeypatch, capsys):
    propostas, _pasta_chunks = _preparar_pastas(tmp_path, monkeypatch)

    _escrever_jsonl(propostas, [_regra_proposta(chunk_id="chunk-que-nao-existe-mais", status="ok")])

    status.reclassificar()

    atualizadas = [json.loads(linha) for linha in propostas.read_text(encoding="utf-8").splitlines()]
    assert atualizadas[0]["status"] == "suspeito"
    assert "nao pode ser reverificada" in atualizadas[0]["motivo_suspeita"]

    saida = capsys.readouterr().out
    assert "1" in saida


def test_reclassificar_preserva_regra_genuina_como_ok(tmp_path, monkeypatch):
    propostas, pasta_chunks = _preparar_pastas(tmp_path, monkeypatch)

    _escrever_jsonl(propostas, [_regra_proposta(status="ok")])
    _escrever_jsonl(
        pasta_chunks / "doc.jsonl",
        [
            {
                "chunk_id": "c1",
                "doc": "doc.docx",
                "pagina": None,
                "secao": "secao 1",
                "texto": "risco de alagamento podendo variar entre 6 mm e 30 mm em uma hora",
            }
        ],
    )

    status.reclassificar()

    atualizadas = [json.loads(linha) for linha in propostas.read_text(encoding="utf-8").splitlines()]
    assert atualizadas[0]["status"] == "ok"
    assert atualizadas[0]["motivo_suspeita"] is None


def test_reclassificar_imprime_contagem_antes_e_depois(tmp_path, monkeypatch, capsys):
    propostas, pasta_chunks = _preparar_pastas(tmp_path, monkeypatch)

    _escrever_jsonl(
        propostas,
        [
            _regra_proposta(
                regra_id="r1",
                valor_min=26.0,
                valor_max=50.0,
                fonte_trecho="texto sem numero algum aqui",
                status="ok",
                motivo_suspeita=None,
            ),
            _regra_proposta(
                regra_id="r2",
                valor_min=6.0,
                valor_max=30.0,
                fonte_trecho="podendo variar entre 6 mm e 30 mm em uma hora",
                status="ok",
                motivo_suspeita=None,
            ),
        ],
    )
    _escrever_jsonl(
        pasta_chunks / "doc.jsonl",
        [
            {
                "chunk_id": "c1",
                "doc": "doc.docx",
                "pagina": None,
                "secao": "secao 1",
                "texto": "texto sem numero algum aqui, podendo variar entre 6 mm e 30 mm em uma hora",
            }
        ],
    )

    status.reclassificar()

    atualizadas = [json.loads(linha) for linha in propostas.read_text(encoding="utf-8").splitlines()]
    contagem = {"ok": 0, "suspeito": 0}
    for registro in atualizadas:
        contagem[registro["status"]] += 1
    assert contagem == {"ok": 1, "suspeito": 1}
