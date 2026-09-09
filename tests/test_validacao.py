from ingestao.contrato import RegraExtraida
from ingestao.validacao import (
    classificar,
    extremos_citados,
    normalizar,
    pode_conter_limiar,
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
        "escala": "alerta_cor",
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


def test_valor_plausivel_aceita_taxa_de_precipitacao_da_tabela_de_intensidade():
    # faixa "Moderada" de PROTOCOLO_ALERTAS_METEORO.docx: 6 mm/h a 30 mm/h.
    assert valor_plausivel("taxa_precipitacao", "mm/h", 6.0, 30.0)


def test_valor_implausivel_de_taxa_de_precipitacao_e_recusado():
    # nenhuma chuva sustentada real chega a milhares de mm/h -- o recorde
    # mundial de acumulado em 1h fica perto de 400 mm (La Reuniao, 1966).
    assert not valor_plausivel("taxa_precipitacao", "mm/h", 5000.0, None)


def test_classificar_marca_taxa_de_precipitacao_implausivel_como_suspeito():
    chunk = "extremo acima de 9000mm/h"
    regra = _regra(
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        escala="intensidade",
        nivel="extremo",
        valor_min=9000.0,
        valor_max=None,
        fonte_trecho=chunk,
    )

    status, motivo = classificar(regra, chunk)

    assert status == "suspeito"
    assert "valor_min" in motivo


def test_classificar_aceita_regra_de_taxa_de_precipitacao_genuina():
    chunk = "Moderada 6 mm/h a 30 mm/h"
    regra = _regra(
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        # Uma taxa nao tem janela: o "por hora" ja esta na unidade. A fixture
        # padrao usa 72, herdado de um exemplo de chuva acumulada.
        janela_horas=None,
        escala="intensidade",
        nivel="moderada",
        valor_min=6.0,
        valor_max=30.0,
        fonte_trecho="Moderada 6 mm/h a 30 mm/h",
    )

    assert classificar(regra, chunk) == ("ok", None)


def test_padrao_de_limiar_reconhece_taxa_em_mm_h():
    assert suspeito_de_omissao("Moderada 6 mm/h a 30 mm/h", 0)


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


def test_extremos_citados_aceita_ambos_os_extremos_presentes():
    assert extremos_citados(6.0, 30.0, "podendo variar entre 6 mm e 30 mm em uma hora")


def test_extremos_citados_aceita_separador_decimal_por_virgula():
    assert extremos_citados(31.5, None, "cota atinge 31,5 m na regua")


def test_extremos_citados_compara_numericamente_nao_como_string():
    assert extremos_citados(90.0, None, "vento acima de 90 km/h")


def test_extremos_citados_recusa_trecho_sem_nenhum_digito():
    assert not extremos_citados(
        26.0,
        50.0,
        "Situacao de Perigo, a severidade e alta. Representando uma "
        "significante ameaca a vida ou a propriedade.",
    )


def test_extremos_citados_recusa_trecho_com_apenas_um_dos_extremos():
    assert not extremos_citados(6.0, 30.0, "podendo variar a partir de 6 mm em uma hora")


def test_extremos_citados_aceita_minimo_nulo_com_maximo_presente():
    assert extremos_citados(None, 6.0, "chuva fraca: ate 6 mm/h")


def test_classificar_marca_extremos_nao_citados_mesmo_com_trecho_real():
    # regressao: a fabricacao real do documento -- faixa plausivel, trecho
    # genuino do chunk, mas sem nenhum dos numeros da faixa.
    chunk = "Situacao de Perigo, a severidade e alta. Ameaca a vida ou a propriedade."
    regra = _regra(
        grandeza="chuva_acumulada",
        unidade="mm",
        valor_min=26.0,
        valor_max=50.0,
        fonte_trecho=chunk,
    )

    status, motivo = classificar(regra, chunk)

    assert status == "suspeito"
    assert "valor_min" in motivo


def test_classificar_aceita_regra_genuina_com_extremos_citados():
    chunk = "risco de alagamento podendo variar entre 6 mm e 30 mm em uma hora"
    regra = _regra(
        grandeza="chuva_acumulada",
        unidade="mm",
        valor_min=6.0,
        valor_max=30.0,
        fonte_trecho="podendo variar entre 6 mm e 30 mm em uma hora",
    )

    assert classificar(regra, chunk) == ("ok", None)


def test_pode_conter_limiar_aceita_chuva_em_mm():
    assert pode_conter_limiar("acumulado de 30 mm em 24h")


def test_pode_conter_limiar_aceita_vento_em_kmh():
    assert pode_conter_limiar("rajadas de 90 km/h")


def test_pode_conter_limiar_aceita_taxa_em_mm_h():
    assert pode_conter_limiar("taxa de 6 mm/h")


def test_pode_conter_limiar_aceita_refletividade_em_dbz():
    assert pode_conter_limiar("refletividade de 45 dBZ")


def test_pode_conter_limiar_recusa_prosa_sem_numero():
    assert not pode_conter_limiar("este capitulo descreve a metodologia adotada")


def test_pode_conter_limiar_recusa_numero_sem_unidade():
    assert not pode_conter_limiar("o artigo 5 da lei")


def test_classificar_prioriza_trecho_confere_sobre_extremos_citados():
    # trecho nao existe no chunk E os extremos nao aparecem no trecho
    # citado -- a falha de existencia do trecho e a mais fundamental e deve
    # ser reportada primeiro.
    status, motivo = classificar(
        _regra(valor_min=26.0, valor_max=50.0, fonte_trecho="trecho que o modelo inventou, sem numero algum"),
        "chunk real que nao contem essa citacao de jeito nenhum",
    )

    assert status == "suspeito"
    assert "trecho" in motivo


def test_taxa_com_janela_e_suspeita():
    # Achado real: "60 mm em 24 horas" virou taxa_precipitacao de 60 mm/h com
    # janela 24. Sao coisas diferentes por um fator de 24, e codificada como
    # taxa a regra praticamente nunca dispara.
    regra = _regra(
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        janela_horas=24,
        valor_min=60.0,
        valor_max=None,
        fonte_trecho="acumulados de 60 mm em 24 horas na regiao",
    )
    chunk = "previsao de acumulados de 60 mm em 24 horas na regiao central"

    status, motivo = classificar(regra, chunk)

    assert status == "suspeito"
    assert "chuva_acumulada" in motivo


def test_taxa_sem_janela_passa():
    regra = _regra(
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        janela_horas=None,
        valor_min=6.0,
        valor_max=30.0,
        fonte_trecho="Chuva moderada: acima de 6 mm e ate 30 mm/h",
    )
    chunk = "classificacao: Chuva moderada: acima de 6 mm e ate 30 mm/h no periodo"

    assert classificar(regra, chunk) == ("ok", None)


def test_faixa_degenerada_e_suspeita():
    # Achado real: "superiores a 90 mm em 24 horas" virou valor_min=90 E
    # valor_max=90, ou seja "exatamente 90" em vez de "acima de 90".
    regra = _regra(
        grandeza="chuva_acumulada",
        unidade="mm",
        janela_horas=24,
        valor_min=90.0,
        valor_max=90.0,
        fonte_trecho="acumulados superiores a 90 mm em 24 horas",
    )
    chunk = "registro de acumulados superiores a 90 mm em 24 horas no municipio"

    status, motivo = classificar(regra, chunk)

    assert status == "suspeito"
    assert "degenerada" in motivo


def test_limiar_aberto_com_um_extremo_nulo_passa():
    regra = _regra(
        grandeza="chuva_acumulada",
        unidade="mm",
        janela_horas=24,
        valor_min=90.0,
        valor_max=None,
        fonte_trecho="acumulados superiores a 90 mm em 24 horas",
    )
    chunk = "registro de acumulados superiores a 90 mm em 24 horas no municipio"

    assert classificar(regra, chunk) == ("ok", None)


def test_taxa_com_janela_de_uma_hora_e_redundante_mas_coerente():
    # "30 mm em uma hora" e ao mesmo tempo um acumulado de 1h e uma taxa de
    # 30 mm/h. O documento escreve das duas formas; nao e erro.
    regra = _regra(
        grandeza="taxa_precipitacao",
        unidade="mm/h",
        janela_horas=1,
        escala="intensidade",
        nivel="moderada",
        valor_min=6.0,
        valor_max=30.0,
        fonte_trecho="podendo variar entre 6 mm e 30 mm em uma hora",
    )
    chunk = "acumulados podendo variar entre 6 mm e 30 mm em uma hora"

    assert classificar(regra, chunk) == ("ok", None)
