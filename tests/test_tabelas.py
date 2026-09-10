from ingestao.contrato import Chunk
from ingestao.tabelas import extrair_de_tabelas

TABELA_INTENSIDADE = """
| INTENSIDADE | TAXA DE PRECIPITACAO |
| --- | --- |
| Fraca | <= 6,0 mm/h |
| Moderada | 6 mm/h a 30 mm/h |
| Forte | 30 mm/h a 70 mm/h |
| Muito Forte | 70 mm/h a 90 mm/h |
| Extremo | > 90mm/h |
"""

TABELA_HISTORICA = """
|Cidades|N de evento|Data|Limiar|CAD|
|---|---|---|---|---|
|Januaria|3|08/12/2023 - 45mm|40mm|2|
"""


def _chunk(texto: str, chunk_id: str = "c1") -> Chunk:
    return Chunk(chunk_id=chunk_id, doc="protocolo.docx", pagina=5, secao="3. Intensidade", texto=texto)


def test_tabela_de_intensidade_produz_cinco_regras_na_ordem():
    regras, ignoradas = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert ignoradas == 0
    assert [r.nivel for r in regras] == ["fraca", "moderada", "forte", "muito_forte", "extremo"]


def test_tabela_de_intensidade_todas_escala_intensidade():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.escala == "intensidade" for r in regras)


def test_tabela_de_intensidade_todas_origem_tabela():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.origem == "tabela" for r in regras)


def test_tabela_de_intensidade_todas_grandeza_taxa_precipitacao_unidade_mm_h():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.grandeza == "taxa_precipitacao" for r in regras)
    assert all(r.unidade == "mm/h" for r in regras)


def test_tabela_de_intensidade_janela_horas_nula_por_ser_taxa():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.janela_horas is None for r in regras)


def test_tabela_de_intensidade_faixas_exatas():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))
    faixas = [(r.valor_min, r.valor_max) for r in regras]

    assert faixas == [
        (None, 6.0),
        (6.0, 30.0),
        (30.0, 70.0),
        (70.0, 90.0),
        (90.0, None),
    ]


def test_tabela_de_intensidade_todas_status_ok():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.status == "ok" for r in regras)


def test_tabela_de_intensidade_procedencia_vem_do_chunk():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.fonte_doc == "protocolo.docx" for r in regras)
    assert all(r.fonte_pagina == 5 for r in regras)
    assert all(r.fonte_secao == "3. Intensidade" for r in regras)
    assert all(r.chunk_id == "c1" for r in regras)


def test_tabela_de_intensidade_entidade_estadual():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert all(r.entidade_tipo == "estado" for r in regras)
    assert all(r.entidade_nome == "minas gerais" for r in regras)


def test_separador_decimal_com_virgula_e_com_ponto():
    texto = """
| INTENSIDADE | TAXA DE PRECIPITACAO |
| --- | --- |
| Fraca | <= 6,0 mm/h |
"""
    regras, _ = extrair_de_tabelas(_chunk(texto))
    assert regras[0].valor_max == 6.0

    texto_ponto = """
| INTENSIDADE | TAXA DE PRECIPITACAO |
| --- | --- |
| Fraca | <= 6.5 mm/h |
"""
    regras_ponto, _ = extrair_de_tabelas(_chunk(texto_ponto, "c2"))
    assert regras_ponto[0].valor_max == 6.5


def test_mm_h_nao_e_confundida_com_mm():
    regras, _ = extrair_de_tabelas(_chunk(TABELA_INTENSIDADE))

    assert not any(r.grandeza == "chuva_acumulada" for r in regras)
    assert not any(r.unidade == "mm" for r in regras)


def test_tabela_historica_nao_produz_regra_mas_conta_linha_ignorada():
    regras, ignoradas = extrair_de_tabelas(_chunk(TABELA_HISTORICA))

    assert regras == []
    assert ignoradas == 1


def test_tabela_de_niveis_por_cor_usa_escala_alerta_cor():
    texto = """
| Nivel | Acumulado |
| --- | --- |
| Verde | <= 10 mm |
| Amarelo | 10 mm a 30 mm |
"""
    regras, ignoradas = extrair_de_tabelas(_chunk(texto))

    assert ignoradas == 0
    assert len(regras) == 2
    assert all(r.escala == "alerta_cor" for r in regras)
    assert [r.nivel for r in regras] == ["verde", "amarelo"]
    assert all(r.grandeza == "chuva_acumulada" for r in regras)


def test_sinonimo_situacao_de_atencao_mapeia_para_amarelo():
    texto = """
| Nivel | Acumulado |
| --- | --- |
| Situacao de Atencao | 10 mm a 30 mm |
"""
    regras, ignoradas = extrair_de_tabelas(_chunk(texto))

    assert ignoradas == 0
    assert len(regras) == 1
    assert regras[0].escala == "alerta_cor"
    assert regras[0].nivel == "amarelo"


def test_texto_sem_tabela_devolve_lista_vazia_e_zero_ignoradas():
    regras, ignoradas = extrair_de_tabelas(_chunk("Paragrafo comum sem tabela alguma, so prosa tecnica."))

    assert regras == []
    assert ignoradas == 0


def test_markdown_malformado_nao_quebra():
    texto = """
| INTENSIDADE | TAXA DE PRECIPITACAO |
| --- | --- |
| Fraca | <= 6,0 mm/h | celula extra |
| Moderada | 6 mm/h a 30 mm/h |
"""
    regras, ignoradas = extrair_de_tabelas(_chunk(texto))

    # a linha malformada (3 celulas, cabecalho tem 2) nao derruba o parser;
    # ela conta como ignorada e a linha seguinte, bem formada, ainda produz regra.
    assert ignoradas == 1
    assert len(regras) == 1
    assert regras[0].nivel == "moderada"


def test_linha_com_rotulo_ambiguo_e_ignorada_nao_gera_regra():
    # celula que casa com duas escalas ao mesmo tempo (ex.: menciona tanto uma
    # cor quanto uma classe de intensidade) e ambigua -- o parser prefere
    # contar como nao reconhecida a adivinhar qual escala vale.
    texto = """
| Nivel | Faixa |
| --- | --- |
| Fraca Verde | <= 6 mm/h |
"""
    regras, ignoradas = extrair_de_tabelas(_chunk(texto))

    assert regras == []
    assert ignoradas == 1
