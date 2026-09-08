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
        "nivel": "critico",
        "valor": 100.0,
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


def test_valor_plausivel_aceita_chuva_razoavel():
    assert valor_plausivel("chuva_acumulada", "mm", 100.0)


def test_valor_implausivel_de_chuva_e_recusado():
    assert not valor_plausivel("chuva_acumulada", "mm", 90000.0)


def test_valor_plausivel_aceita_cota_de_rio():
    assert valor_plausivel("cota", "m", 3.8)


def test_combinacao_de_grandeza_e_unidade_desconhecida_e_recusada():
    assert not valor_plausivel("cota", "mm", 3.8)


def test_classificar_regra_boa_devolve_ok():
    chunk = "conforme o estudo, saturacao a partir de 100mm em 72h no solo gnaisse"

    assert classificar(_regra(), chunk) == ("ok", None)


def test_classificar_marca_citacao_inventada():
    status, motivo = classificar(_regra(), "texto que nao contem a citacao")

    assert status == "suspeito"
    assert "trecho" in motivo


def test_classificar_marca_valor_implausivel():
    chunk = "saturacao a partir de 100mm em 72h"
    status, motivo = classificar(_regra(valor=90000.0), chunk)

    assert status == "suspeito"
    assert "valor" in motivo


def test_chunk_com_limiar_e_zero_regras_e_suspeito_de_omissao():
    assert suspeito_de_omissao("o acumulado critico e de 80mm em 24h", 0)


def test_chunk_sem_padrao_de_limiar_nao_e_suspeito():
    assert not suspeito_de_omissao("este capitulo descreve a metodologia adotada", 0)


def test_chunk_que_produziu_regra_nao_e_suspeito_de_omissao():
    assert not suspeito_de_omissao("o acumulado critico e de 80mm em 24h", 1)
