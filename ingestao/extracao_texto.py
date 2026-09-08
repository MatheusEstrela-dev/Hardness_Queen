import re
from pathlib import Path

import pymupdf
import pymupdf4llm
from docx import Document

from ingestao.contrato import Chunk
from ingestao.identidade import chunk_id

_CABECALHO = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_MINIMO_DE_CARACTERES = 10


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


def extrair_docx(caminho: Path) -> tuple[list[Chunk], str]:
    documento = Document(str(caminho))

    chunks: list[Chunk] = []
    secao_atual: str | None = None
    corpo: list[str] = []

    def fechar_bloco() -> None:
        texto = "\n".join(corpo).strip()
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

    for paragrafo in documento.paragraphs:
        texto = paragrafo.text.strip()
        if not texto:
            continue
        if paragrafo.style.name.startswith("Heading"):
            fechar_bloco()
            corpo = [texto]
            secao_atual = texto
        else:
            corpo.append(texto)
    fechar_bloco()

    return chunks, "texto_nativo"


def extrair(caminho: Path) -> tuple[list[Chunk], str]:
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        return extrair_pdf(caminho)
    if sufixo == ".docx":
        return extrair_docx(caminho)
    raise ValueError(f"extensao nao suportada: {sufixo}")
