"""A area de trabalho decide onde cada etapa le e grava."""

from pathlib import Path

import pytest

from ingestao.caminhos import AREAS, caminhos


def test_sem_variavel_a_area_e_meteorologia(monkeypatch):
    monkeypatch.delenv("HARDNESS_AREA", raising=False)

    assert caminhos().propostas == Path("data/Meteorologia/regras_propostas.jsonl")


@pytest.mark.parametrize("area", AREAS)
def test_cada_area_tem_docs_e_data_proprios(monkeypatch, area):
    monkeypatch.setenv("HARDNESS_AREA", area)
    c = caminhos()

    assert c.docs == Path("docs") / area
    assert c.chunks == Path("data") / area / "chunks"
    assert c.dataset.parent == Path("data") / area


def test_area_desconhecida_falha_alto_em_vez_de_criar_pasta_vazia(monkeypatch):
    # Um erro de digitacao criaria data/<erro>/ e a esteira diria "nada a fazer".
    monkeypatch.setenv("HARDNESS_AREA", "meteorologia")

    with pytest.raises(SystemExit, match="desconhecida"):
        caminhos()
