"""Extracao documental de Geo; parametros candidatos nunca sao homologacao."""

import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile
from collections import Counter

from ingestao.contrato import Chunk
from ingestao.identidade import chunk_id

_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NIVEIS = ("observacao", "atencao", "critico", "emergencial")
_NUMERO = r"\d+(?:[.,]\d+)?"
_LINHA = re.compile(
    rf"^\s*({_NUMERO})\s*(minutos?|horas?)\s+"
    + r"\s+".join([rf"({_NUMERO})\s*mm"] * 4)
    + r"\s*$", re.IGNORECASE,
)
PADRAO_CANDIDATO = re.compile(
    r"limiar|deflagrante|\bialc\b|\bspi\b|\b(?:icm|irq)\b|"
    r"n[ií]ve(?:l|is)\s+de\s+alerta|declividade|\bR[1-4]\b|"
    r"\d+(?:[.,]\d+)?\s*(?:mm\b|graus\b|%)", re.IGNORECASE,
)


def normalizar(texto: str) -> str:
    return " ".join("".join(
        c for c in unicodedata.normalize("NFKD", texto.lower())
        if not unicodedata.combining(c)
    ).split())


def ler_planilhas(caminho: Path) -> dict[str, list[dict]]:
    """Le valores armazenados e formulas sem recalcular ou alterar o XLSX."""
    with ZipFile(caminho) as arquivo:
        strings = []
        if "xl/sharedStrings.xml" in arquivo.namelist():
            strings = ["".join(t.itertext()) for t in ET.fromstring(
                arquivo.read("xl/sharedStrings.xml"))]
        relacoes = {r.get("Id"): r.get("Target") for r in ET.fromstring(
            arquivo.read("xl/_rels/workbook.xml.rels"))}
        resultado = {}
        for aba in ET.fromstring(arquivo.read("xl/workbook.xml")).findall("s:sheets/s:sheet", _NS):
            alvo = relacoes[aba.get(f"{{{_REL}}}id")]
            membro = alvo.lstrip("/") if alvo.startswith("/") else posixpath.normpath("xl/" + alvo)
            linhas = []
            for linha in ET.fromstring(arquivo.read(membro)).findall("s:sheetData/s:row", _NS):
                valores, formulas = {}, {}
                for celula in linha:
                    coluna = re.sub(r"\d", "", celula.get("r", ""))
                    valor = celula.find("s:v", _NS)
                    texto = valor.text if valor is not None else None
                    if celula.get("t") == "s" and texto is not None:
                        texto = strings[int(texto)]
                    elif celula.get("t") == "inlineStr":
                        texto = "".join(t.text or "" for t in celula.findall(".//s:t", _NS))
                    if texto is not None:
                        valores[coluna] = texto
                    formula = celula.find("s:f", _NS)
                    if formula is not None:
                        formulas[coluna] = ET.tostring(formula, encoding="unicode")
                linhas.append({"linha": int(linha.get("r")), "valores": valores, "formulas": formulas})
            resultado[aba.get("name")] = linhas
        return resultado


def registro_ialc(linha: int, valores: dict, cabecalhos: dict) -> dict:
    bruto = valores.get("I")
    try:
        referencia = float(bruto.replace(",", ".")) if bruto is not None else None
    except ValueError:
        referencia = None
    return {
        "entidade_tipo": "municipio", "entidade_nome": valores.get("A"),
        "codigo_ibge_fonte": valores.get("D"), "grandeza": "chuva_acumulada",
        "chuva_referencia_mm": referencia, "janela_minutos": None,
        "faixas_preenchidas": {c: valores[c] for c in "KLMNO" if valores.get(c) is not None},
        "cabecalhos_faixas": {c: cabecalhos.get(c) for c in "KLMNO"},
        "fonte_aba": "Limiar de Aproximação", "fonte_linha": linha,
        "fonte_celula": f"I{linha}", "valores_fonte": valores,
        "status": "pendente_revisao", "uso_operacional": False,
        "pendencias": ["confirmar_metodo_referencia", "confirmar_janela_96h",
                       "confirmar_formula_percentuais", "confirmar_evento_e_precedencia"],
    }


def auditar_ialc(abas: dict) -> dict:
    historico = {}
    for linha in abas["Risco dos Registros S2id"][1:]:
        valores = linha["valores"]
        if valores.get("A"):
            historico.setdefault(normalizar(valores["A"]), []).append(linha)
    contagens, divergencias = Counter(), []
    for linha in abas["Limiar de Aproximação"][1:]:
        valores = linha["valores"]
        if not valores.get("A"):
            continue
        correspondencias = historico.get(normalizar(valores["A"]), [])
        if len(correspondencias) != 1:
            motivo = "sem_correspondencia_por_nome" if not correspondencias else "nome_ambiguo"
            contagens[motivo] += 1
            divergencias.append({"municipio": valores["A"], "linha_ialc": linha["linha"], "motivo": motivo})
            continue
        origem = correspondencias[0]
        def numero(valor):
            try:
                return float(valor.replace(",", "."))
            except (AttributeError, ValueError):
                return None
        referencia = numero(valores.get("I"))
        menor, media = (numero(origem["valores"].get(c)) for c in "EF")
        if referencia is None:
            contagens["referencia_nao_numerica"] += 1
            continue
        contagens["igual_menor"] += referencia == menor
        contagens["igual_media"] += referencia == media
        if referencia not in (menor, media):
            contagens["diferente_de_ambos"] += 1
            divergencias.append({"municipio": valores["A"], "linha_ialc": linha["linha"],
                                 "linha_historico": origem["linha"], "referencia_mm": referencia,
                                 "menor_deflagrante_mm": menor, "media_ocorrencias_mm": media,
                                 "motivo": "referencia_diferente_de_menor_e_media"})
    return {"contagens": dict(contagens), "divergencias": divergencias,
            "metodo": "comparacao por nome sem acentos; igualdade nao comprova metodologia",
            "formulas_armazenadas": sum(len(l["formulas"]) for linhas in abas.values() for l in linhas)}


def extrair_tabelas_alerta(texto: str) -> list[dict]:
    """Gramatica fechada da tabela encontrada no Plancon de Ipatinga.

    Aceita somente titulo de evento, quatro niveis na ordem documentada e
    quatro valores com unidade. O valor isolado nao define operador nem faixa.
    """
    evento, cabecalho_ok = None, False
    resultado = []
    for linha in texto.splitlines():
        limpa = normalizar(linha)
        if "tabela" in limpa:
            evento, cabecalho_ok = None, False
            if "alerta" in limpa and "risco geologico" in limpa and "deslizamento" in limpa:
                evento = "deslizamento"
            elif "alerta" in limpa and "inundacao" in limpa and "alagamento" in limpa:
                evento = "inundacao_e_alagamento"
        elif "nivel" in limpa:
            posicoes = [limpa.find(f"nivel {i} ({n})") for i, n in enumerate(_NIVEIS, 1)]
            cabecalho_ok = all(p >= 0 for p in posicoes) and posicoes == sorted(posicoes)
        match = _LINHA.fullmatch(linha)
        if evento is None or not cabecalho_ok or match is None:
            continue
        janela, unidade, *valores = match.groups()
        minutos = float(janela.replace(",", ".")) * (60 if unidade.lower().startswith("hora") else 1)
        for nivel, valor in zip(_NIVEIS, valores):
            resultado.append({
                "evento": evento, "dominio": "geologia" if evento == "deslizamento" else "hidrologia",
                "grandeza": "chuva_acumulada", "unidade": "mm", "janela_minutos": minutos,
                "escala_fonte": "niveis_plancon", "nivel": nivel,
                "valor_referencia_mm": float(valor.replace(",", ".")),
                "operador": None, "fonte_trecho": linha.strip(),
                "status": "pendente_revisao", "uso_operacional": False,
            })
    return resultado


def ler_documento(caminho: Path):
    if caminho.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(caminho) as documento:
            for numero, pagina in enumerate(documento, 1):
                yield numero, None, pagina.get_text(sort=True)
    else:
        from ingestao.extracao_texto import extrair_docx

        chunks, _ = extrair_docx(caminho)
        for chunk in chunks:
            yield None, chunk.secao, chunk.texto


def dividir_texto(doc: str, pagina: int | None, secao: str | None, texto: str):
    from ingestao.extracao_texto import TAMANHO_MAXIMO_DO_CHUNK

    # Sobreposicao preserva contexto nas fronteiras. A tabela e lida antes,
    # sobre a pagina inteira, para nunca separar cabecalho e valores.
    passo = TAMANHO_MAXIMO_DO_CHUNK - 300
    for inicio in range(0, len(texto), passo):
        trecho = texto[inicio:inicio + TAMANHO_MAXIMO_DO_CHUNK].strip()
        if trecho:
            yield Chunk(chunk_id=chunk_id(doc, pagina, trecho), doc=doc,
                        pagina=pagina, secao=secao, texto=trecho)


def classes_qgis(caminho: Path):
    """Faixas de simbologia sao catalogadas sem promover a alerta operacional."""
    with ZipFile(caminho) as arquivo:
        membros = sorted(n for n in arquivo.namelist() if n.endswith(".qgs"))
        for membro in membros:
            projeto = ET.fromstring(arquivo.read(membro))
            for camada in projeto.findall(".//projectlayers/maplayer"):
                for renderer in camada.findall(".//rasterrenderer"):
                    for shader in renderer.findall("rastershader/colorrampshader"):
                        for elemento in shader.findall("item"):
                            yield {
                                "camada": camada.findtext("layername"),
                                "campo": renderer.get("band"), "tipo_renderer": "raster",
                                "tipo_rampa": shader.get("colorRampType"),
                                "classe_fonte": dict(elemento.attrib), "membro_zip": membro,
                                "fonte_trecho": ET.tostring(elemento, encoding="unicode").strip(),
                                "natureza": "simbologia_cartografica", "uso_operacional": False,
                                "pendencia": "conferir_valor_do_raster_com_legenda_e_metodologia",
                            }
                for renderer in camada.findall("renderer-v2"):
                    for elemento in renderer.findall("ranges/range") + renderer.findall("categories/category"):
                        yield {
                            "camada": camada.findtext("layername"),
                            "campo": renderer.get("attr"), "tipo_renderer": renderer.get("type"),
                            "classe_fonte": dict(elemento.attrib), "membro_zip": membro,
                            "fonte_trecho": ET.tostring(elemento, encoding="unicode").strip(),
                            "natureza": "simbologia_cartografica", "uso_operacional": False,
                        }
