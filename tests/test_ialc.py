"""Leitura do IALC. A planilha de teste e montada aqui, com a mesma forma da
real (duas abas, cabecalhos por extenso), para os testes nao dependerem de um
arquivo que a responsavel altera todo dia."""

import importlib
import json
from zipfile import ZipFile

import pytest

from ingestao.ialc import ler_abas, linhas_do_ialc, regra_do_ialc
from ingestao.validacao import classificar

CAB_S2ID = [
    "MUNICÍPIO", "MESORREGIÃO", "Acumulado de Chuva 96h(mm) o menor deflagrante",
    "Acumulado de Chuva 96h(mm) Média das ocorrências", "OBSERVAÇÃO",
]
CAB_LIMIAR = [
    "MUNICIPIOS", "COD_IBGE", "CHUVA APROXIMADA PARA RISCO", "RISCO BAIXO (mm) 25%",
    "RISCO EXTREMAMENTO ALTO 100%",
]


def _xlsx(caminho, abas: dict[str, list[list]]):
    """Um xlsx minimo com strings inline -- a forma mais simples que o formato aceita."""

    def celula(coluna, linha, valor):
        ref = f"{chr(65 + coluna)}{linha}"
        if valor is None:
            return ""
        if isinstance(valor, (int, float)):
            return f'<c r="{ref}"><v>{valor}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{valor}</t></is></c>'

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with ZipFile(caminho, "w") as z:
        folhas, rels = [], []
        for i, (nome, linhas) in enumerate(abas.items(), 1):
            folhas.append(f'<sheet name="{nome}" sheetId="{i}" r:id="rId{i}"/>')
            rels.append(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>')
            corpo = "".join(
                f'<row r="{n}">' + "".join(celula(c, n, v) for c, v in enumerate(linha)) + "</row>"
                for n, linha in enumerate(linhas, 1)
            )
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {ns}><sheetData>{corpo}</sheetData></worksheet>")
        z.writestr("xl/workbook.xml", f"<workbook {ns} {rel_ns}><sheets>{''.join(folhas)}</sheets></workbook>")
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels) + "</Relationships>",
        )
    return caminho


@pytest.fixture
def planilha(tmp_path):
    return _xlsx(tmp_path / "IALC.xlsx", {
        "Risco dos Registros S2id": [
            CAB_S2ID,
            ["Ipatinga", "Vale do Rio Doce", 32, 47, None],
            ["Abaeté", "Central Mineira", 104, 104, "1 registro"],
            ["Congonhal", "Sul", 0, 0, "Satélite registrou 0 chuvas"],
        ],
        "Limiar de Aproximação": [
            CAB_LIMIAR,
            ["Ipatinga", "3131307", 47, None, None],
            ["Abaeté", "3100203", 104, None, None],
            ["Congonhal", "3118007", 48, None, None],
            ["Abadia dos Dourados", "3100104", 11, None, None],
        ],
    })


def _regras(planilha):
    linhas, cabecalho = linhas_do_ialc(ler_abas(planilha))
    return {linha.municipio: regra_do_ialc(linha, cabecalho, "IALC.xlsx", "2026-09-11") for linha in linhas}


def test_uma_regra_por_municipio_so_com_o_numero_que_a_planilha_traz(planilha):
    regras = _regras(planilha)
    regra, _ = regras["Ipatinga"]

    assert len(regras) == 4
    assert (regra.escala, regra.nivel) == ("risco_ialc", "risco_extremamente_alto")
    assert (regra.valor_min, regra.valor_max, regra.unidade, regra.janela_horas) == (47.0, None, "mm", 96.0)
    assert (regra.entidade_tipo, regra.entidade_nome) == ("municipio", "Ipatinga")
    # Nenhuma classe de 25/50/75/90% e derivada: a planilha nao traz o numero.
    assert {r.nivel for r, _ in regras.values()} == {"risco_extremamente_alto"}


def test_rotulo_e_o_do_cabecalho_como_esta_escrito(planilha):
    regra, _ = _regras(planilha)["Ipatinga"]

    assert regra.nivel_rotulo == "RISCO EXTREMAMENTO ALTO 100%"


def test_media_de_varios_eventos_passa_e_mostra_o_menor_deflagrante(planilha):
    regra, chunk = _regras(planilha)["Ipatinga"]

    assert (regra.status, regra.motivo_suspeita) == ("ok", None)
    # Ja houve desastre com 32 mm: o revisor precisa ver isso ao lado dos 47.
    assert "menor deflagrante 32 mm" in chunk.texto


@pytest.mark.parametrize("municipio,motivo", [
    ("Abaeté", "limiar de um unico evento"),
    ("Congonhal", "ajuste manual"),
    ("Abadia dos Dourados", "sem registro no S2iD"),
])
def test_limiar_que_nao_e_media_de_varios_eventos_fica_suspeito_com_o_motivo(planilha, municipio, motivo):
    regra, _ = _regras(planilha)[municipio]

    assert regra.status == "suspeito"
    assert motivo in regra.motivo_suspeita


def test_regra_passa_pelas_mesmas_defesas_das_outras_origens(planilha):
    regra, chunk = _regras(planilha)["Ipatinga"]

    assert classificar(regra, chunk.texto) == ("ok", None)


def test_id_nao_depende_da_linha_da_planilha(tmp_path, planilha):
    # A planilha e editada todo dia: uma linha inserida no meio nao pode
    # mudar o id das regras seguintes e duplicar a importacao.
    antes, _ = _regras(planilha)["Ipatinga"]
    abas = ler_abas(planilha)
    abas["Limiar de Aproximação"].insert(1, ["Nova Linha", "0000000", 50, None, None])
    deslocada = _xlsx(tmp_path / "IALC2.xlsx", abas)
    depois, _ = _regras(deslocada)["Ipatinga"]

    assert antes.regra_id == depois.regra_id


def test_cabecalho_sem_janela_falha_em_vez_de_supor_96h(tmp_path):
    sem_janela = [h.replace("96h", "") for h in CAB_S2ID]
    planilha = _xlsx(tmp_path / "x.xlsx", {
        "Risco dos Registros S2id": [sem_janela, ["Ipatinga", "-", 32, 47, None]],
        "Limiar de Aproximação": [CAB_LIMIAR, ["Ipatinga", "3131307", 47, None, None]],
    })

    with pytest.raises(ValueError, match="janela"):
        linhas_do_ialc(ler_abas(planilha))


def test_coluna_procurada_pelo_nome_e_nao_pela_posicao(tmp_path):
    reordenado = ["COD_IBGE", "CHUVA APROXIMADA PARA RISCO", "MUNICIPIOS", "RISCO EXTREMAMENTO ALTO 100%"]
    planilha = _xlsx(tmp_path / "x.xlsx", {
        "Risco dos Registros S2id": [CAB_S2ID, ["Ipatinga", "-", 32, 47, None]],
        "Limiar de Aproximação": [reordenado, ["3131307", 47, "Ipatinga", None]],
    })

    linhas, _ = linhas_do_ialc(ler_abas(planilha))

    assert (linhas[0].municipio, linhas[0].limiar_mm) == ("Ipatinga", 47.0)


# --- script de importacao ---------------------------------------------------


def test_importar_e_idempotente_e_grava_a_evidencia(tmp_path, monkeypatch, planilha):
    # O nome comeca com digito, como os das outras etapas: import por string.
    importar = importlib.import_module("scripts.06_importar_ialc")
    propostas = tmp_path / "propostas.jsonl"
    chunks = tmp_path / "chunks"
    monkeypatch.setattr(importar, "PROPOSTAS", propostas)
    monkeypatch.setattr(importar, "PASTA_CHUNKS", chunks)

    assert importar.main([str(planilha), "--municipio", "ipatinga", "--versao", "2026-09-11"]) == 0
    assert importar.main([str(planilha), "--municipio", "ipatinga", "--versao", "2026-09-12"]) == 0

    gravadas = [json.loads(l) for l in propostas.read_text(encoding="utf-8").splitlines()]
    evidencias = [json.loads(l) for l in (chunks / "IALC.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["entidade_nome"] for r in gravadas] == ["Ipatinga"]
    assert [e["chunk_id"] for e in evidencias] == [gravadas[0]["chunk_id"]]
