"""Extensao do contrato para Planos de Contingencia municipais.

Cada teste daqui tranca um defeito medido na amostra de Ipatinga (PlanCon
2025/2026), onde a esteira, com o contrato anterior, extraiu zero regras
corretas: a tabela de niveis nao tinha representacao (janela de 15 min, niveis
do plano sem cor) e o que saiu pelo modelo veio com todos os campos errados.
"""

import pytest
from pydantic import ValidationError

from ingestao.contrato import Chunk, RegraExtraida
from ingestao.extrator_regras import INSTRUCAO, montar_prompt
from ingestao.identidade import regra_id
from ingestao.revisao.agrupamento import agrupar_por_limiar, chave_limiar
from ingestao.tabelas import extrair_de_tabelas

# Transcricao literal do markdown que a etapa 03 produziu para a pagina 12 do
# PlanCon de Ipatinga (pagina 18 do PDF).
TABELAS_IPATINGA = """**TABELA DE NÍVEIS DE ALERTA PARA RISCO GEOLÓGICO (DESLIZAMENTOS)**

|TEMPO|NÍVEL 1(Observação)|NÍVEL 2(Atenção)|NÍVEL 3(Crítico)|NÍVEL 4 (Emergencial)|
|---|---|---|---|---|
|1 hora|5 mm|25 mm|35 mm|50 mm|
|24 horas|25 mm|35 mm|80 mm|90 mm|
|72 horas|35 mm|80 mm|90 mm|110 mm|
|96 horas|80 mm|90 mm|110 mm|120 mm|



**TABELA DE NÍVEIS DE ALERTA PARA INUNDAÇÃO E ALAGAMENTO**

|TEMPO|NÍVEL 1(Observação)|NÍVEL 2(Atenção)|NÍVEL 3(Crítico)|NÍVEL 4 (Emergencial)|
|---|---|---|---|---|
|15 minutos|5 mm|10 mm|15 mm|50 mm|
|1 horas|20 mm|30 mm|40 mm|90 mm|
|4 horas|40 mm|50 mm|60 mm|130 mm|
|24 horas|80 mm|90 mm|100 mm|210 mm|
|72 horas|120 mm|130 mm|140 mm|250 mm|
|96 horas|160 mm|170 mm|180 mm|370 mm|

PLANO DE CONTINGÊNCIA - IPATINGA 2025/2026 VERSÃO: 00
"""

CABECALHO = "|TEMPO|NÍVEL 1(Observação)|NÍVEL 2(Atenção)|NÍVEL 3(Crítico)|NÍVEL 4 (Emergencial)|\n|---|---|---|---|---|\n"


def _chunk(texto=TABELAS_IPATINGA, doc="IPATINGA_2026-04-16.pdf"):
    return Chunk(chunk_id="c18", doc=doc, pagina=18, secao="6. MONITORAMENTO", texto=texto)


def _municipal(**sobrescritas):
    payload = {
        "dominio": "geologia", "entidade_tipo": "municipio", "entidade_nome": "ipatinga",
        "grandeza": "chuva_acumulada", "janela_horas": 24, "unidade": "mm",
        "escala": "nivel_municipal", "nivel": "n2", "nivel_rotulo": "Atenção",
        "valor_min": 35.0, "valor_max": None, "fonte_trecho": "|24 horas|25 mm|35 mm|80 mm|90 mm|",
    }
    payload.update(sobrescritas)
    return payload


# --- contrato ---------------------------------------------------------------


def test_nivel_municipal_e_ordinal_e_carrega_o_nome_do_documento():
    regra = RegraExtraida(**_municipal())

    assert (regra.escala, regra.nivel, regra.nivel_rotulo) == ("nivel_municipal", "n2", "Atenção")


def test_nivel_municipal_sem_rotulo_e_recusado():
    with pytest.raises(ValidationError, match="nivel_rotulo"):
        RegraExtraida(**_municipal(nivel_rotulo=None))


@pytest.mark.parametrize("escala,nivel", [("nivel_municipal", "amarelo"), ("alerta_cor", "n2")])
def test_niveis_nao_atravessam_de_uma_escala_para_outra(escala, nivel):
    # O "Atencao (Amarelo)" de Ipatinga comeca em 35 mm/24h; o Amarelo do POP
    # estadual, em 60. A escala e a fronteira que impede um de virar o outro.
    with pytest.raises(ValidationError):
        RegraExtraida(**_municipal(escala=escala, nivel=nivel))


def test_janela_de_quinze_minutos_tem_representacao():
    assert RegraExtraida(**_municipal(janela_horas=0.25)).janela_horas == 0.25


@pytest.mark.parametrize("janela", [0, -1])
def test_janela_nao_positiva_e_recusada(janela):
    with pytest.raises(ValidationError, match="positiva"):
        RegraExtraida(**_municipal(janela_horas=janela))


def test_sentido_padrao_e_acima():
    assert RegraExtraida(**_municipal()).sentido == "acima"


def test_chuva_abaixo_de_um_valor_nao_e_limiar_de_risco():
    with pytest.raises(ValidationError, match="sentido"):
        RegraExtraida(**_municipal(sentido="abaixo"))


def test_temperatura_de_topo_aceita_sentido_abaixo():
    # Topo de nuvem mais frio e conveccao mais forte: aqui menos e pior.
    regra = RegraExtraida(**_municipal(
        dominio="meteorologia", grandeza="temperatura_topo", unidade="celsius", janela_horas=None,
        escala="intensidade", nivel="forte", nivel_rotulo=None, sentido="abaixo",
        valor_min=None, valor_max=-60.0, fonte_trecho="topo abaixo de -60 graus Celsius",
    ))

    assert regra.sentido == "abaixo"


# --- identidade -------------------------------------------------------------


def test_regras_que_so_diferem_na_janela_tem_ids_diferentes():
    # Colisao real em Ipatinga: sem a janela no id, "96h Nivel 1 = 80 mm" e
    # "24h Nivel 1 = 80 mm" do mesmo chunk tinham o mesmo id.
    base = ("c18", "municipio", "ipatinga", "chuva_acumulada", "nivel_municipal", "n1", 80.0, None)

    assert regra_id(*base, 96, "geologia") != regra_id(*base, 24, "geologia")


def test_regras_que_so_diferem_no_dominio_tem_ids_diferentes():
    base = ("c18", "municipio", "ipatinga", "chuva_acumulada", "nivel_municipal", "n1", 80.0, None, 24)

    assert regra_id(*base, "geologia") != regra_id(*base, "hidrologia")


# --- parser de tabela do PlanCon ---------------------------------------------


def test_tabela_de_ipatinga_vira_quarenta_regras_distintas():
    regras, ignoradas = extrair_de_tabelas(_chunk())

    assert (len(regras), ignoradas) == (40, 0)
    assert len({r.regra_id for r in regras}) == 40
    assert all(r.status == "ok" and r.origem == "tabela" for r in regras)


def test_processo_do_titulo_define_o_dominio():
    regras, _ = extrair_de_tabelas(_chunk())

    assert sum(r.dominio == "geologia" for r in regras) == 16
    assert sum(r.dominio == "hidrologia" for r in regras) == 24


def test_limiar_e_do_municipio_do_plano_e_nunca_vira_cor():
    regras, _ = extrair_de_tabelas(_chunk())

    assert {(r.entidade_tipo, r.entidade_nome) for r in regras} == {("municipio", "ipatinga")}
    assert {r.escala for r in regras} == {"nivel_municipal"}
    # O "Critico" do plano e o terceiro nivel (Laranja no proprio plano). Pelo
    # sinonimo das tabelas estaduais ele viraria roxo.
    critico = [r for r in regras if r.nivel_rotulo == "Crítico"]
    assert critico and {r.nivel for r in critico} == {"n3"}


def test_quinze_minutos_viram_um_quarto_de_hora():
    regras, _ = extrair_de_tabelas(_chunk())
    quinze = [r for r in regras if r.janela_horas == 0.25]

    assert [r.valor_min for r in quinze] == [5.0, 10.0, 15.0, 50.0]


def test_documento_que_nao_e_plancon_nao_ganha_municipio_adivinhado():
    regras, ignoradas = extrair_de_tabelas(_chunk(doc="relatorio_qualquer.pdf"))

    assert regras == []
    assert ignoradas == 10


def test_titulo_sem_processo_nao_ganha_dominio_adivinhado():
    texto = "**TABELA DE NIVEIS**\n\n" + CABECALHO + "|24 horas|25 mm|35 mm|80 mm|90 mm|\n"

    assert extrair_de_tabelas(_chunk(texto)) == ([], 1)


def test_linha_com_celula_ruim_e_ignorada_inteira_sem_deslocar_niveis():
    texto = (
        "**TABELA PARA DESLIZAMENTOS**\n\n" + CABECALHO
        + "|24 horas|25 mm|35 mm|-|90 mm|\n|96 horas|80 mm|90 mm|110 mm|120 mm|\n"
    )
    regras, ignoradas = extrair_de_tabelas(_chunk(texto))

    assert ignoradas == 1
    assert {r.janela_horas for r in regras} == {96}


def test_linha_que_decresce_entre_niveis_e_ignorada():
    # Nivel mais grave com limiar menor: documento errado ou colunas
    # desalinhadas. Em nenhum dos dois casos a regra deve existir.
    texto = "**TABELA PARA DESLIZAMENTOS**\n\n" + CABECALHO + "|24 horas|25 mm|80 mm|35 mm|90 mm|\n"

    assert extrair_de_tabelas(_chunk(texto)) == ([], 1)


def test_umidade_do_ar_nao_vira_regra():
    texto = "|UMIDADE|NÍVEL DE ALERTA|\n|---|---|\n|Entre 21% e 30%|ATENÇÃO|\n|Abaixo de 12%|EMERGÊNCIA|\n"

    regras, _ = extrair_de_tabelas(_chunk(texto))

    assert regras == []


# --- fila de revisao --------------------------------------------------------


def _proposta(**sobrescritas):
    base = RegraExtraida(**_municipal()).model_dump()
    base.update(regra_id="r1", fonte_doc="IPATINGA_2026-04-16.pdf", fonte_pagina=18,
                fonte_secao=None, status="ok", motivo_suspeita=None, origem="tabela")
    base.update(sobrescritas)
    return base


def test_mesmo_numero_em_municipios_diferentes_nao_vira_uma_decisao_so():
    grupos = agrupar_por_limiar([_proposta(), _proposta(regra_id="r2", entidade_nome="barbacena")])

    assert len(grupos) == 2


def test_grupo_leva_o_nome_do_nivel_para_a_tela():
    assert agrupar_por_limiar([_proposta()])[0]["nivel_rotulo"] == "Atenção"


def test_mesmo_municipio_escrito_com_caixa_diferente_e_um_grupo_so():
    # Medido em Ipatinga: o parser tira "ipatinga" do nome do arquivo e o
    # modelo copia "Ipatinga" do texto.
    grupos = agrupar_por_limiar([_proposta(), _proposta(regra_id="r2", entidade_nome="Ipatinga")])

    assert len(grupos) == 1
    assert len(grupos[0]["fontes"]) == 2


def test_proposta_gravada_antes_do_campo_sentido_continua_legivel():
    antiga = _proposta()
    del antiga["sentido"], antiga["nivel_rotulo"]

    assert chave_limiar(antiga) == chave_limiar(_proposta())


# --- prompt -----------------------------------------------------------------


def test_prompt_diz_ao_modelo_de_qual_documento_vem_o_trecho():
    assert "IPATINGA_2026-04-16.pdf" in montar_prompt(_chunk())


def test_prompt_proibe_converter_nivel_municipal_em_cor():
    assert "nivel_municipal" in INSTRUCAO
    assert "NUNCA cor" in INSTRUCAO
