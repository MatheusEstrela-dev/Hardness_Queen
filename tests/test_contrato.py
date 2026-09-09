import pytest
from pydantic import ValidationError

from ingestao.contrato import Chunk, Extracao, Regra, RegraExtraida


def _regra_valida(**sobrescritas) -> dict:
    payload = {
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "escala": "alerta_cor",
        "nivel": "roxo",
        "valor_min": 100.0,
        "valor_max": None,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
    }
    payload.update(sobrescritas)
    return payload


def test_regra_extraida_aceita_payload_valido():
    regra = RegraExtraida(**_regra_valida())

    assert regra.valor_min == 100.0
    assert regra.valor_max is None


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


def test_regra_extraida_rejeita_nivel_fora_da_escala_de_cinco_cores():
    payload = _regra_valida()
    payload["nivel"] = "critico"

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_regra_extraida_aceita_nivel_de_cor_com_escala_alerta_cor():
    regra = RegraExtraida(**_regra_valida(escala="alerta_cor", nivel="roxo"))

    assert regra.escala == "alerta_cor"
    assert regra.nivel == "roxo"


def test_regra_extraida_rejeita_nivel_de_intensidade_com_escala_alerta_cor():
    payload = _regra_valida(escala="alerta_cor", nivel="moderada")

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_regra_extraida_aceita_nivel_de_intensidade_com_escala_intensidade():
    payload = _regra_valida(
        escala="intensidade",
        nivel="moderada",
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        valor_min=6.0,
        valor_max=30.0,
        fonte_trecho="moderada 6 mm/h a 30 mm/h",
    )

    regra = RegraExtraida(**payload)

    assert regra.escala == "intensidade"
    assert regra.nivel == "moderada"


def test_regra_extraida_rejeita_nivel_de_cor_com_escala_intensidade():
    payload = _regra_valida(escala="intensidade", nivel="roxo")

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_regra_extraida_aceita_grandeza_taxa_precipitacao_e_unidade_mm_h():
    payload = _regra_valida(
        escala="intensidade",
        nivel="extremo",
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        valor_min=90.0,
        valor_max=None,
        fonte_trecho="extremo acima de 90mm/h",
    )

    regra = RegraExtraida(**payload)

    assert regra.grandeza == "taxa_precipitacao"
    assert regra.unidade == "mm/h"


def test_janela_horas_pode_ser_nula():
    payload = _regra_valida()
    payload["janela_horas"] = None

    assert RegraExtraida(**payload).janela_horas is None


def test_extracao_aceita_lista_vazia():
    assert Extracao(regras=[]).regras == []


def test_faixa_fechada_com_os_dois_extremos():
    regra = RegraExtraida(**_regra_valida(valor_min=6.0, valor_max=30.0))

    assert regra.valor_min == 6.0
    assert regra.valor_max == 30.0


def test_faixa_aberta_so_com_minimo():
    regra = RegraExtraida(**_regra_valida(valor_min=90.0, valor_max=None))

    assert regra.valor_min == 90.0
    assert regra.valor_max is None


def test_faixa_aberta_so_com_maximo():
    regra = RegraExtraida(**_regra_valida(valor_min=None, valor_max=50.0))

    assert regra.valor_min is None
    assert regra.valor_max == 50.0


def test_faixa_sem_nenhum_extremo_e_rejeitada():
    payload = _regra_valida(valor_min=None, valor_max=None)

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def _regra_completa(**sobrescritas) -> Regra:
    payload = {
        "regra_id": "r1",
        "chunk_id": "c1",
        "fonte_doc": "laudo.pdf",
        "fonte_pagina": 12,
        "fonte_secao": "4.2 Caracterizacao do solo",
        "origem": "modelo",
        "status": "ok",
    }
    payload.update(sobrescritas)
    return Regra(**_regra_valida(), **payload)


def test_regra_carrega_procedencia_e_status():
    regra = _regra_completa()

    assert regra.fonte_pagina == 12
    assert regra.motivo_suspeita is None


def test_regra_exige_origem():
    payload = {
        "regra_id": "r1",
        "chunk_id": "c1",
        "fonte_doc": "laudo.pdf",
        "fonte_pagina": 12,
        "fonte_secao": "4.2 Caracterizacao do solo",
        "status": "ok",
    }

    with pytest.raises(ValidationError):
        Regra(**_regra_valida(), **payload)


def test_regra_rejeita_origem_desconhecida():
    with pytest.raises(ValidationError):
        _regra_completa(origem="ocr")


def test_regra_aceita_origem_tabela():
    regra = _regra_completa(origem="tabela")

    assert regra.origem == "tabela"


def test_regra_aceita_origem_modelo():
    regra = _regra_completa(origem="modelo")

    assert regra.origem == "modelo"


def test_chunk_aceita_pagina_nula():
    chunk = Chunk(chunk_id="c1", doc="laudo.docx", pagina=None, secao="1 Introducao", texto="x")

    assert chunk.pagina is None


def test_fonte_trecho_mais_longo_que_o_teto_e_rejeitado():
    # Regressao: um chunk com uma tabela de eventos (9 linhas x 7 colunas,
    # celulas multi-linha em <br>) fez o modelo copiar uma linha inteira em
    # fonte_trecho, esgotando o orcamento de tokens antes do JSON fechar
    # (task-16). Uma linha dessa tabela tem 87-145 caracteres; o teto
    # precisa tornar isso estruturalmente impossivel.
    payload = _regra_valida(
        fonte_trecho=(
            "Teofilo Otoni|3|15/12/2017 - 186 mm; 02/02/2018 - 35,2 mm; "
            "25/11/2022 - 264,8 mm|Max 120h 175,8|110 mm|Vale do Mucuri|15"
        )
    )

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_fonte_trecho_mais_curto_que_o_minimo_e_rejeitado():
    # Uma citacao de poucos caracteres nao verifica nada -- nem da pra um
    # revisor humano achar o numero no documento original com ela.
    payload = _regra_valida(fonte_trecho="6 mm")

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_fonte_trecho_realista_cabe_confortavelmente_no_teto():
    payload = _regra_valida(fonte_trecho="podendo variar entre 6 mm e 30 mm em uma hora")

    regra = RegraExtraida(**payload)

    assert regra.fonte_trecho == "podendo variar entre 6 mm e 30 mm em uma hora"
