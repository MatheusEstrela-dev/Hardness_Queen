import re
from pathlib import Path

import pymupdf
import pymupdf4llm
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ingestao.contrato import Chunk
from ingestao.identidade import chunk_id

_CABECALHO = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_MINIMO_DE_CARACTERES = 10

# Medido no acervo real de 3 .docx (ver task-13-report.md): os titulos de
# secao que nao usam estilo Heading (negrito ou maiuscula em paragrafo
# "Normal") vao de 6 a 98 caracteres. 120 da folga sobre o maior cabecalho
# medido sem deixar frases de corpo qualificarem so pelo tamanho -- a frase
# ainda precisa ser negrito, maiuscula ou numerada para contar como secao.
LIMITE_DE_CARACTERES_DE_CABECALHO = 120

# .docx nao tem pagina fixa (secao 4 da spec), entao a unidade de chunking
# nao pode ser "a pagina inteira" como no PDF. Sem um teto, um documento sem
# estilo de titulo vira um chunk so (medido: 20631 e 21245 caracteres em
# documentos reais, ~11x o maior chunk de PDF, e isso estourou VRAM na
# etapa 04). O teto usa a mesma ordem de grandeza da distribuicao real de
# PDF (mediana 1824, maximo 2721 caracteres) com folga: 2800 fica acima do
# maior chunk de PDF medido, entao o .docx passa a produzir chunks
# comparaveis aos de PDF em vez de excepcionalmente maiores.
TAMANHO_MAXIMO_DO_CHUNK = 2800

# "6.2" ou "6.2.1" no comeco do paragrafo, ou "1." como nos documentos reais
# (INSTRUCAO_NORMATIVA, PROTOCOLO_NORMATIVO: "1. OBJETIVO", "2. ABRANGENCIA"
# etc, paragrafos "Normal", sem negrito).
_NUMERACAO_DE_SECAO = re.compile(r"^\d+(\.\d+)*[.\s]")


def titulo_da_secao(texto_markdown: str) -> str | None:
    encontrado = _CABECALHO.search(texto_markdown)
    return encontrado.group(1).strip() if encontrado else None


def _tem_camada_de_texto(caminho: Path) -> bool:
    with pymupdf.open(caminho) as documento:
        for pagina in documento:
            if len(pagina.get_text().strip()) >= _MINIMO_DE_CARACTERES:
                return True
    return False


def extrair_pdf(caminho: Path) -> tuple[list[Chunk], str]:
    tinha_texto = _tem_camada_de_texto(caminho)
    paginas = pymupdf4llm.to_markdown(str(caminho), page_chunks=True)

    chunks: list[Chunk] = []
    ultima_secao: str | None = None
    for pagina in paginas:
        texto = pagina["text"].strip()
        if not texto:
            continue
        secao = titulo_da_secao(pagina["text"]) or ultima_secao
        ultima_secao = secao
        numero = pagina["metadata"]["page_number"]
        chunks.append(
            Chunk(
                chunk_id=chunk_id(caminho.name, numero, texto),
                doc=caminho.name,
                pagina=numero,
                secao=secao,
                texto=texto,
            )
        )

    if tinha_texto:
        estado = "texto_nativo"
    elif chunks:
        estado = "ocr_aplicado"
    else:
        estado = "sem_camada_texto"
    return chunks, estado


def _paragrafo_e_cabecalho_por_heuristica(paragrafo) -> bool:
    """Documentos reais (Instrucao_Normativa_COMPLETA_Alertas_MG.docx,
    PROTOCOLO_NORMATIVO.docx) nao usam o estilo Heading -- todo paragrafo e
    "Normal", e o titulo se marca visualmente: negrito, maiuscula, ou
    numeracao de secao. Uma frase de prosa nao e curta como um titulo, entao
    o limite de tamanho e a primeira guarda contra falso positivo (uma frase
    longa com um trecho em negrito no meio nao qualifica so por isso).
    """
    texto = paragrafo.text.strip()
    if not texto or len(texto) > LIMITE_DE_CARACTERES_DE_CABECALHO:
        return False

    corridas_com_texto = [corrida for corrida in paragrafo.runs if corrida.text.strip()]
    todo_em_negrito = bool(corridas_com_texto) and all(corrida.bold for corrida in corridas_com_texto)

    return todo_em_negrito or texto.isupper() or bool(_NUMERACAO_DE_SECAO.match(texto))


def _celula_para_markdown(texto: str) -> str:
    # \n dentro de uma celula (paragrafos multiplos, quebra manual de linha)
    # vira <br>, mesma convencao do pymupdf4llm -- sem isso a linha da
    # tabela deixaria de caber numa unica linha de texto, quebrando a
    # premissa "entidade e valor na mesma linha".
    texto = texto.strip().replace("\n", "<br>")
    return texto.replace("|", "\\|")


def _tabela_para_markdown(tabela: Table) -> str:
    """Renderiza uma tabela do .docx como markdown com linha de cabecalho,
    no mesmo formato que o pymupdf4llm produz para tabela de PDF (ver
    test_pdf_com_tabela_preserva_as_colunas_em_markdown) -- assim o
    extrator ve um formato consistente independente da origem do
    documento.

    Tabela sem linha alguma (guarda contra .docx malformado) devolve
    string vazia e nao entra no chunk.
    """
    linhas = tabela.rows
    if not linhas:
        return ""

    linhas_markdown: list[str] = []
    for indice, linha in enumerate(linhas):
        celulas = [_celula_para_markdown(celula.text) for celula in linha.cells]
        linhas_markdown.append("|" + "|".join(celulas) + "|")
        if indice == 0:
            linhas_markdown.append("|" + "|".join("---" for _ in celulas) + "|")

    return "\n".join(linhas_markdown)


def extrair_docx(caminho: Path) -> tuple[list[Chunk], str]:
    documento = Document(str(caminho))

    chunks: list[Chunk] = []
    secao_atual: str | None = None
    corpo: list[str] = []
    tamanho_do_corpo = 0

    def fechar_bloco() -> None:
        nonlocal corpo, tamanho_do_corpo
        texto = "\n".join(corpo).strip()
        corpo = []
        tamanho_do_corpo = 0
        if not texto:
            return
        chunks.append(
            Chunk(
                chunk_id=chunk_id(caminho.name, None, texto),
                doc=caminho.name,
                pagina=None,
                secao=secao_atual,
                texto=texto,
            )
        )

    def adicionar_ao_corpo(texto: str) -> None:
        nonlocal corpo, tamanho_do_corpo
        # teto de tamanho: fecha no bloco atual antes de estourar, nunca no
        # meio de um item (paragrafo ou tabela), e continua na mesma secao
        # (secao_atual nao muda) -- e assim que o chunk de continuacao
        # carrega a procedencia adiante. Um item sozinho maior que o teto
        # (uma tabela grande) e mantido inteiro mesmo assim: nao ha logica
        # de particionar um item em varios chunks, so de fechar o bloco
        # anterior antes dele.
        if corpo and tamanho_do_corpo + len(texto) + 1 > TAMANHO_MAXIMO_DO_CHUNK:
            fechar_bloco()
        corpo.append(texto)
        tamanho_do_corpo += len(texto) + 1

    # document.paragraphs e document.tables sao vistas separadas e perdem a
    # ordem relativa entre paragrafo e tabela; iter_inner_content() percorre
    # o corpo do documento (element.body) e devolve Paragraph/Table na
    # ordem em que aparecem no XML, que e a ordem em que precisam entrar no
    # chunk.
    for item in documento.iter_inner_content():
        if isinstance(item, Paragraph):
            texto = item.text.strip()
            if not texto:
                continue

            e_cabecalho = item.style.name.startswith("Heading") or _paragrafo_e_cabecalho_por_heuristica(item)
            if e_cabecalho:
                fechar_bloco()
                corpo = [texto]
                tamanho_do_corpo = len(texto)
                secao_atual = texto
                continue

            adicionar_ao_corpo(texto)
        elif isinstance(item, Table):
            texto_tabela = _tabela_para_markdown(item)
            if not texto_tabela:
                continue
            adicionar_ao_corpo(texto_tabela)

    fechar_bloco()

    return chunks, "texto_nativo"


def extrair(caminho: Path) -> tuple[list[Chunk], str]:
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        return extrair_pdf(caminho)
    if sufixo == ".docx":
        return extrair_docx(caminho)
    raise ValueError(f"extensao nao suportada: {sufixo}")
