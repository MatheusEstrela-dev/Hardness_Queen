from ingestao.extracao_geo import extrair_tabelas_alerta, registro_ialc
from ingestao.extracao_geo import classes_qgis
from zipfile import ZipFile


def test_ialc_nao_inventa_faixas_nem_janela():
    registro = registro_ialc(4, {"A": "Abre Campo", "D": "3100302", "I": "95"}, {})
    assert registro["chuva_referencia_mm"] == 95
    assert registro["janela_minutos"] is None
    assert registro["faixas_preenchidas"] == {}
    assert registro["uso_operacional"] is False


def test_tabela_preserva_evento_janela_e_niveis_sem_converter_para_cor():
    texto = """TABELA DE NÍVEIS DE ALERTA PARA RISCO GEOLÓGICO (DESLIZAMENTOS)
TEMPO NÍVEL 1 (Observação) NÍVEL 2 (Atenção) NÍVEL 3 (Crítico) NÍVEL 4 (Emergencial)
96 horas 80 mm 90 mm 110 mm 120 mm
TABELA DE NÍVEIS DE ALERTA PARA INUNDAÇÃO E ALAGAMENTO
TEMPO NÍVEL 1 (Observação) NÍVEL 2 (Atenção) NÍVEL 3 (Crítico) NÍVEL 4 (Emergencial)
15 minutos 5 mm 10 mm 15 mm 50 mm"""
    regras = extrair_tabelas_alerta(texto)
    assert len(regras) == 8
    assert regras[0]["janela_minutos"] == 5760
    assert regras[4]["janela_minutos"] == 15
    assert regras[0]["evento"] != regras[4]["evento"]
    assert regras[3]["valor_referencia_mm"] == 120
    assert regras[3]["nivel"] == "emergencial"
    assert all(r["uso_operacional"] is False for r in regras)


def test_numeros_climatologicos_nao_viram_limiares():
    assert extrair_tabelas_alerta("Precipitação anual 1029 mm. Em 96 horas choveu 80 mm.") == []


def test_linha_incompleta_nao_desloca_colunas():
    texto = """TABELA DE NÍVEIS DE ALERTA PARA RISCO GEOLÓGICO (DESLIZAMENTOS)
TEMPO NÍVEL 1 (Observação) NÍVEL 2 (Atenção) NÍVEL 3 (Crítico) NÍVEL 4 (Emergencial)
96 horas 80 mm 90 mm 120 mm"""
    assert extrair_tabelas_alerta(texto) == []


def test_qgis_preserva_valor_e_legenda_divergentes(tmp_path):
    caminho = tmp_path / "spi.qgz"
    with ZipFile(caminho, "w") as arquivo:
        arquivo.writestr("spi.qgs", '''<qgis><projectlayers><maplayer>
        <layername>SPI_12</layername><pipe><rasterrenderer band="1">
        <rastershader><colorrampshader colorRampType="DISCRETE">
        <item value="-0.3546" label="&lt;= -2,0 - Extremamente Seco" />
        </colorrampshader></rastershader></rasterrenderer></pipe>
        </maplayer></projectlayers></qgis>''')
    classes = list(classes_qgis(caminho))
    assert len(classes) == 1
    assert classes[0]["classe_fonte"]["value"] == "-0.3546"
    assert classes[0]["classe_fonte"]["label"].startswith("<= -2,0")
    assert classes[0]["uso_operacional"] is False


def test_cabecalho_invertido_nao_troca_valores_de_nivel():
    texto = """TABELA DE NÍVEIS DE ALERTA PARA RISCO GEOLÓGICO (DESLIZAMENTOS)
TEMPO NÍVEL 4 (Emergencial) NÍVEL 3 (Crítico) NÍVEL 2 (Atenção) NÍVEL 1 (Observação)
96 horas 120 mm 110 mm 90 mm 80 mm"""
    assert extrair_tabelas_alerta(texto) == []


def test_tabela_seguinte_nao_herda_evento_anterior():
    texto = """TABELA DE NÍVEIS DE ALERTA PARA RISCO GEOLÓGICO (DESLIZAMENTOS)
TEMPO NÍVEL 1 (Observação) NÍVEL 2 (Atenção) NÍVEL 3 (Crítico) NÍVEL 4 (Emergencial)
96 horas 80 mm 90 mm 110 mm 120 mm
TABELA DE CHUVAS OBSERVADAS
96 horas 10 mm 20 mm 30 mm 40 mm"""
    assert len(extrair_tabelas_alerta(texto)) == 4
