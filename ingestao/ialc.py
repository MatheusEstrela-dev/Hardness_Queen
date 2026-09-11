"""Leitura deterministica do IALC -- limiar de chuva por municipio.

O IALC (planilha mantida pela CINDEC-CEDEC) da, para cada um dos 853
municipios de MG, a chuva acumulada associada a desastre, calibrada pelo
historico do S2iD. E a fonte que PREVALECE sobre o Plano de Contingencia
municipal quando os dois divergem (decisao do usuario, 2026-09-11).

O que este modulo faz, e o que deliberadamente nao faz:

- Emite UMA regra por municipio: a classe cujo numero esta na planilha,
  "extremamente alto" (100% do limiar). As classes de 25/50/75/90% sao
  deriváveis, mas a regra de aplicacao do percentual nao foi confirmada com a
  responsavel pela planilha -- as colunas delas estao vazias. Nao se inventa.
- A janela (96h) e a unidade (mm) vem dos CABECALHOS da aba do S2iD; a aba de
  limiares nao as repete. Sem janela no cabecalho, a leitura falha alto.
- Toda regra carrega a proveniencia do valor, e vira suspeita quando ele nao e
  a media de varios eventos do proprio municipio. Medido na versao de
  2026-09-11, por este leitor: 299 municipios sem registro no S2iD receberam o
  valor de um vizinho (92% batem com um dos 3 mais proximos), 243 limiares vem
  de um evento so, e 19 foram ajustados a mao -- 561 de 853 ficam suspeitos.

O texto do "chunk" de cada regra e a linha da planilha escrita por extenso:
e a evidencia que o revisor ve na fila, com o menor evento deflagrante ao lado
do limiar -- o dado que mostra se ja houve desastre abaixo dele.
"""

import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from ingestao.contrato import Chunk, Regra, RegraExtraida
from ingestao.identidade import chunk_id, regra_id_de
from ingestao.validacao import classificar, normalizar

ABA_LIMIARES = "Limiar de Aproximação"
ABA_S2ID = "Risco dos Registros S2id"

_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _coluna(referencia: str) -> int:
    indice = 0
    for letra in re.match(r"[A-Z]+", referencia).group():
        indice = indice * 26 + ord(letra) - 64
    return indice - 1


def ler_abas(caminho: Path) -> dict[str, list[list[str | None]]]:
    """Valores armazenados de cada aba, sem recalcular nem alterar o arquivo.

    So biblioteca padrao: um xlsx e um zip de XML, e ler valores nao justifica
    uma dependencia nova no ambiente de treino pregado.
    """
    with ZipFile(caminho) as arquivo:
        compartilhadas = []
        if "xl/sharedStrings.xml" in arquivo.namelist():
            raiz = ET.fromstring(arquivo.read("xl/sharedStrings.xml"))
            compartilhadas = ["".join(t.itertext()) for t in raiz.findall("s:si", _NS)]
        relacoes = {r.get("Id"): r.get("Target") for r in ET.fromstring(arquivo.read("xl/_rels/workbook.xml.rels"))}
        abas = {}
        for aba in ET.fromstring(arquivo.read("xl/workbook.xml")).findall("s:sheets/s:sheet", _NS):
            alvo = relacoes[aba.get(_REL)]
            membro = alvo.lstrip("/") if alvo.startswith("/") else posixpath.normpath("xl/" + alvo)
            linhas = []
            for linha in ET.fromstring(arquivo.read(membro)).findall("s:sheetData/s:row", _NS):
                valores: dict[int, str] = {}
                for celula in linha.findall("s:c", _NS):
                    bruto = celula.find("s:v", _NS)
                    if celula.get("t") == "inlineStr":
                        texto = "".join(t.text or "" for t in celula.findall(".//s:t", _NS))
                    elif bruto is None:
                        continue
                    elif celula.get("t") == "s":
                        texto = compartilhadas[int(bruto.text)]
                    else:
                        texto = bruto.text
                    valores[_coluna(celula.get("r"))] = texto
                linhas.append([valores.get(i) for i in range(max(valores) + 1)] if valores else [])
            abas[aba.get("name")] = linhas
        return abas


def _indice(cabecalho: list[str | None], *termos: str) -> int:
    """Coluna cujo cabecalho contem todos os termos (normalizados).

    Por nome e nao por posicao: a planilha e editada todo dia, e uma coluna
    inserida no meio nao pode deslocar em silencio o limiar para outro campo.
    """
    alvo = [normalizar(t) for t in termos]
    achadas = [i for i, h in enumerate(cabecalho) if h and all(t in normalizar(h) for t in alvo)]
    if len(achadas) != 1:
        raise ValueError(f"IALC: esperava 1 coluna com {termos} no cabecalho, achei {len(achadas)}")
    return achadas[0]


def _celula(valores: list | None, indice: int) -> str | None:
    return valores[indice] if valores and indice < len(valores) else None


def _numero(valor: str | None) -> float | None:
    if valor is None or not str(valor).strip():
        return None
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return None


@dataclass(frozen=True)
class LinhaIALC:
    linha: int
    municipio: str
    cod_ibge: str | None
    limiar_mm: float
    menor_deflagrante_mm: float | None
    media_ocorrencias_mm: float | None
    observacao: str | None
    tem_registro_s2id: bool

    def proveniencia(self) -> str | None:
        """Por que este limiar merece atencao do revisor. None se nao merece."""
        if not self.tem_registro_s2id:
            return (
                "municipio sem registro no S2iD: limiar emprestado de municipio vizinho "
                "(metodo nao documentado na planilha)"
            )
        if self.media_ocorrencias_mm is not None and self.limiar_mm != self.media_ocorrencias_mm:
            return (
                f"limiar diferente da media dos eventos do S2iD (menor {self.menor_deflagrante_mm:g} mm, "
                f"media {self.media_ocorrencias_mm:g} mm): ajuste manual"
            )
        if normalizar(self.observacao or "").startswith(("1 registro", "realmente e 1")):
            return "limiar de um unico evento do S2iD"
        return None


@dataclass(frozen=True)
class CabecalhoIALC:
    janela_horas: float
    # Como a planilha escreve a classe dos 100% -- inclusive o erro de
    # digitacao "EXTREMAMENTO". E o rotulo que liga a regra a celula de origem.
    rotulo_limiar: str


def linhas_do_ialc(abas: dict[str, list[list[str | None]]]) -> tuple[list[LinhaIALC], CabecalhoIALC]:
    """As linhas de limiar, cruzadas com o historico do S2iD, e o que o cabecalho define."""
    if ABA_LIMIARES not in abas or ABA_S2ID not in abas:
        raise ValueError(f"IALC: abas esperadas {ABA_LIMIARES!r} e {ABA_S2ID!r}, achei {list(abas)}")

    cab_s2id = abas[ABA_S2ID][0]
    col_menor = _indice(cab_s2id, "menor deflagrante")
    col_media = _indice(cab_s2id, "media das ocorrencias")
    col_obs = _indice(cab_s2id, "observacao")
    janela = re.search(r"(\d+)\s*h", cab_s2id[col_menor] or "", re.IGNORECASE)
    if janela is None or "mm" not in (cab_s2id[col_menor] or "").lower():
        raise ValueError(f"IALC: janela e unidade nao estao no cabecalho {cab_s2id[col_menor]!r}")

    historico: dict[str, list] = {}
    for valores in abas[ABA_S2ID][1:]:
        if valores and valores[0]:
            historico[normalizar(valores[0])] = valores

    cab = abas[ABA_LIMIARES][0]
    col_mun = _indice(cab, "municipios")
    col_ibge = _indice(cab, "cod", "ibge")
    col_limiar = _indice(cab, "chuva aproximada")
    rotulo_limiar = cab[_indice(cab, "extrem", "100")].strip()

    linhas = []
    for numero, valores in enumerate(abas[ABA_LIMIARES][1:], 2):
        municipio, limiar = _celula(valores, col_mun), _numero(_celula(valores, col_limiar))
        if not municipio or limiar is None:
            continue
        s2id = historico.get(normalizar(municipio))
        linhas.append(
            LinhaIALC(
                linha=numero,
                municipio=municipio.strip(),
                cod_ibge=_celula(valores, col_ibge),
                limiar_mm=limiar,
                menor_deflagrante_mm=_numero(_celula(s2id, col_menor)),
                media_ocorrencias_mm=_numero(_celula(s2id, col_media)),
                observacao=(_celula(s2id, col_obs) or "").strip() or None,
                tem_registro_s2id=s2id is not None,
            )
        )
    return linhas, CabecalhoIALC(janela_horas=float(janela.group(1)), rotulo_limiar=rotulo_limiar)


def _evidencia(linha: LinhaIALC, janela: float) -> tuple[str, str]:
    """O texto da linha por extenso, e o trecho dele que sustenta a regra."""
    trecho = (
        f"MUNICIPIOS={linha.municipio}; COD_IBGE={linha.cod_ibge}; "
        f"CHUVA APROXIMADA PARA RISCO={linha.limiar_mm:g} mm em {janela:g}h"
    )
    if not linha.tem_registro_s2id:
        historico = "sem registro no S2iD"
    else:
        menor = "-" if linha.menor_deflagrante_mm is None else f"{linha.menor_deflagrante_mm:g} mm"
        media = "-" if linha.media_ocorrencias_mm is None else f"{linha.media_ocorrencias_mm:g} mm"
        historico = f"menor deflagrante {menor}; media das ocorrencias {media}; observacao {linha.observacao or '-'}"
    texto = f"IALC, aba {ABA_LIMIARES}, linha {linha.linha}: {trecho}. Aba {ABA_S2ID}: {historico}."
    return texto, trecho


def regra_do_ialc(
    linha: LinhaIALC, cabecalho: CabecalhoIALC, fonte_doc: str, versao: str
) -> tuple[Regra, Chunk]:
    """A regra e o chunk que a sustenta -- quem importa grava os dois.

    O chunk precisa ir para data/chunks/ como o de qualquer documento: e la que
    o reclassificar procura o texto de origem para reconferir a regra.
    """
    janela = cabecalho.janela_horas
    texto, trecho = _evidencia(linha, janela)
    chunk = Chunk(
        # Identidade pelo trecho (municipio, IBGE, valor, janela), nao pela
        # linha: a planilha e editada todo dia, e uma linha inserida no meio
        # mudaria o id de todas as seguintes, duplicando a importacao. Assim o
        # id so muda quando o limiar muda -- e ai e mesmo uma regra nova.
        chunk_id=chunk_id(fonte_doc, None, trecho),
        doc=fonte_doc,
        pagina=None,
        secao=f"{ABA_LIMIARES} (versao {versao})",
        texto=texto,
    )
    extraida = RegraExtraida(
        # Mesmo dominio que as tabelas estaduais dao a chuva: a grandeza
        # medida e meteorologica, ainda que calibrada por desastre de solo.
        dominio="meteorologia",
        entidade_tipo="municipio",
        entidade_nome=linha.municipio,
        grandeza="chuva_acumulada",
        janela_horas=janela,
        unidade="mm",
        escala="risco_ialc",
        nivel="risco_extremamente_alto",
        nivel_rotulo=cabecalho.rotulo_limiar,
        sentido="acima",
        valor_min=linha.limiar_mm,
        valor_max=None,
        fonte_trecho=trecho,
    )
    status, motivo = classificar(extraida, chunk.texto)
    if status == "ok" and linha.proveniencia():
        status, motivo = "suspeito", linha.proveniencia()
    return Regra(
        **extraida.model_dump(),
        regra_id=regra_id_de(chunk.chunk_id, extraida),
        chunk_id=chunk.chunk_id,
        fonte_doc=fonte_doc,
        fonte_pagina=None,
        fonte_secao=chunk.secao,
        origem="tabela",
        status=status,
        motivo_suspeita=motivo,
    ), chunk
