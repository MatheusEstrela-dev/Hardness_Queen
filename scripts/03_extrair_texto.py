import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.extracao_texto import extrair
from ingestao.persistencia import (
    documento_inalterado,
    escrever_jsonl,
    hash_arquivo,
    registrar_documento,
)

PASTA_DOCS = Path("docs")
PASTA_CHUNKS = Path("data/chunks")
MANIFESTO = Path("data/manifesto.jsonl")


def main() -> int:
    documentos = sorted(
        caminho
        for caminho in PASTA_DOCS.glob("*")
        if caminho.suffix.lower() in {".pdf", ".docx"}
    )
    if not documentos:
        print(f"Nenhum PDF ou DOCX em '{PASTA_DOCS}/'.")
        return 1

    estados: Counter = Counter()
    for caminho in documentos:
        hash_doc = hash_arquivo(caminho)
        if documento_inalterado(MANIFESTO, caminho.name, hash_doc):
            print(f"[pulado] {caminho.name} inalterado")
            estados["pulado"] += 1
            continue

        chunks, estado = extrair(caminho)
        escrever_jsonl(
            PASTA_CHUNKS / f"{caminho.stem}.jsonl",
            [chunk.model_dump() for chunk in chunks],
        )
        paginas = len({chunk.pagina for chunk in chunks})
        registrar_documento(MANIFESTO, caminho.name, hash_doc, estado, paginas, len(chunks))
        estados[estado] += 1
        print(f"[{estado}] {caminho.name}: {len(chunks)} chunks")

    print("\nResumo por estado:")
    for estado, total in sorted(estados.items()):
        print(f"  {estado}: {total}")
    if estados["sem_camada_texto"]:
        print(
            f"\nATENCAO: {estados['sem_camada_texto']} documento(s) sem camada de texto "
            "nao produziram chunk algum. Verificar se o Tesseract esta instalado."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
