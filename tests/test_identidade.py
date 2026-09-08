from ingestao.identidade import chunk_id, regra_id


def test_chunk_id_e_determinista():
    a = chunk_id("laudo.pdf", 12, "texto da pagina")
    b = chunk_id("laudo.pdf", 12, "texto da pagina")

    assert a == b


def test_chunk_id_muda_com_o_texto():
    a = chunk_id("laudo.pdf", 12, "texto original")
    b = chunk_id("laudo.pdf", 12, "texto editado")

    assert a != b


def test_chunk_id_aceita_pagina_nula_do_docx():
    assert chunk_id("laudo.docx", None, "texto") != ""


def test_regra_id_e_determinista():
    args = ("abc123", "tipo_solo", "gnaisse", "chuva_acumulada", "critico", 100.0)

    assert regra_id(*args) == regra_id(*args)


def test_regra_id_muda_com_o_valor():
    base = ("abc123", "tipo_solo", "gnaisse", "chuva_acumulada", "critico")

    assert regra_id(*base, 100.0) != regra_id(*base, 90.0)
