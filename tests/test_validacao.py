from ingestao.contrato import RegraExtraida
from ingestao.validacao import (
    classificar,
    normalizar,
    suspeito_de_omissao,
    trecho_confere,
    valor_plausivel,
)


def _regra(**sobrescritas) -> RegraExtraida:
    payload = {
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "nivel": "roxo",
        "valor_min": 100.0,
        "valor_max": None,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
    }
    payload.update(sobrescritas)
    return RegraExtraida(**payload)


def test_normalizar_colapsa_espaco_e_markdown():
    assert normalizar("##  Solo   **gnaisse**  ") == "solo gnaisse"


def test_normalizar_remove_acento():
    assert normalizar("saturacao") == normalizar("saturação")


def test_trecho_confere_ignora_diferenca_de_espaco():
    assert trecho_confere("100mm em 72h", "o limiar e de   100mm  em 72h no gnaisse")


def test_trecho_inventado_nao_confere():
    assert not trecho_confere("800mm em 24h", "o limiar e de 100mm em 72h")


def test_trecho_confere_quando_markdown_deixa_espaco_antes_da_virgula():
    # pymupdf4llm entrega o chunk como markdown: "**termo** , resto" vira,
    # apos normalizar, "termo , resto" -- com espaco antes da virgula. O
    # modelo cita a prosa limpa, sem esse espaco. A comparacao por tokens
    # alfanumericos ignora a pontuacao dos dois lados e ainda confere.
    chunk = (
        "**Manutencao de chuvas continuas** , com aumento progressivo "
        "dos acumulados"
    )
    excerto = "Manutencao de chuvas continuas, com aumento progressivo dos acumulados"

    assert trecho_confere(excerto, chunk)


def test_trecho_confere_citacao_inventada_ainda_nao_confere():
    chunk = (
        "**Manutencao de chuvas continuas** , com aumento progressivo "
        "dos acumulados"
    )
    excerto = "superiores a 800 mm em 12 horas"

    assert not trecho_confere(excerto, chunk)


def test_trecho_confere_nao_funde_palavras_separadas_so_por_markdown():
    chunk = "solo de **gnaisse**100mm de espessura"
    excerto = "gnaisse100mm"

    assert not trecho_confere(excerto, chunk)


def test_trecho_confere_ignora_diferenca_de_pontuacao():
    chunk = "o limiar e de: 100mm, em 72h."
    excerto = "o limiar e de 100mm em 72h"

    assert trecho_confere(excerto, chunk)


def test_valor_plausivel_aceita_chuva_razoavel():
    assert valor_plausivel("chuva_acumulada", "mm", 100.0, None)


def test_valor_implausivel_de_chuva_e_recusado():
    assert not valor_plausivel("chuva_acumulada", "mm", 90000.0, None)


def test_valor_plausivel_aceita_cota_de_rio():
    assert valor_plausivel("cota", "m", 3.8, None)


def test_combinacao_de_grandeza_e_unidade_desconhecida_e_recusada():
    assert not valor_plausivel("cota", "mm", 3.8, None)


def test_valor_plausivel_aceita_faixa_fechada_dentro_do_limite():
    assert valor_plausivel("chuva_acumulada", "mm", 6.0, 30.0)


def test_valor_plausivel_recusa_faixa_invertida():
    assert not valor_plausivel("chuva_acumulada", "mm", 30.0, 6.0)


def test_valor_plausivel_recusa_extremo_maximo_fora_da_faixa():
    assert not valor_plausivel("chuva_acumulada", "mm", 6.0, 90000.0)


def test_valor_plausivel_aceita_limiar_de_vento_em_kmh():
    assert valor_plausivel("vento", "km/h", 90.0, None)


def test_valor_plausivel_recusa_vento_absurdo():
    assert not valor_plausivel("vento", "km/h", 5000.0, None)


def test_valor_plausivel_aceita_vil_em_kg_m2():
    assert valor_plausivel("vil", "kg/m2", 1.5, None)


def test_valor_plausivel_aceita_refletividade_em_dbz():
    assert valor_plausivel("refletividade", "dBZ", 45.0, None)


def test_valor_plausivel_aceita_temperatura_topo_negativa():
    assert valor_plausivel("temperatura_topo", "celsius", None, -50.0)


def test_classificar_regra_boa_devolve_ok():
    chunk = "conforme o estudo, saturacao a partir de 100mm em 72h no solo gnaisse"

    assert classificar(_regra(), chunk) == ("ok", None)


def test_classificar_marca_citacao_inventada():
    status, motivo = classificar(_regra(), "texto que nao contem a citacao")

    assert status == "suspeito"
    assert "trecho" in motivo


def test_classificar_prioriza_trecho_sobre_faixa():
    status, motivo = classificar(
        _regra(valor_min=90000.0, fonte_trecho="800mm em 24h"),
        "o limiar e de 100mm em 72h",
    )

    assert status == "suspeito"
    assert "trecho" in motivo


def test_classificar_marca_valor_min_implausivel():
    chunk = "saturacao a partir de 100mm em 72h"
    status, motivo = classificar(_regra(valor_min=90000.0), chunk)

    assert status == "suspeito"
    assert "valor_min" in motivo


def test_classificar_marca_faixa_invertida():
    chunk = "entre 30mm e 6mm em 1h"
    status, motivo = classificar(
        _regra(valor_min=30.0, valor_max=6.0, fonte_trecho="entre 30mm e 6mm em 1h"),
        chunk,
    )

    assert status == "suspeito"


def test_chunk_com_limiar_e_zero_regras_e_suspeito_de_omissao():
    assert suspeito_de_omissao("o acumulado critico e de 80mm em 24h", 0)


def test_chunk_sem_padrao_de_limiar_nao_e_suspeito():
    assert not suspeito_de_omissao("este capitulo descreve a metodologia adotada", 0)


def test_chunk_que_produziu_regra_nao_e_suspeito_de_omissao():
    assert not suspeito_de_omissao("o acumulado critico e de 80mm em 24h", 1)


def test_chunk_com_limiar_de_vento_e_suspeito_de_omissao():
    assert suspeito_de_omissao("rajadas de vento acima de 90 km/h exigem alerta", 0)


def test_chunk_com_limiar_de_vil_e_suspeito_de_omissao():
    assert suspeito_de_omissao("VIL de 1,5 kg/m2 indica risco de granizo", 0)


def test_chunk_com_limiar_de_refletividade_e_suspeito_de_omissao():
    assert suspeito_de_omissao("refletividade acima de 45 dBZ", 0)


def test_chunk_com_limiar_de_temperatura_e_suspeito_de_omissao():
    assert suspeito_de_omissao("temperatura de topo de nuvem de -50 C", 0)
