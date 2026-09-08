import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def hash_arquivo(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(65536), b""):
            digestor.update(bloco)
    return digestor.hexdigest()[:16]


def ler_jsonl(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open("r", encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def anexar_jsonl(caminho: Path, registro: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


def escrever_jsonl(caminho: Path, registros: list[dict]) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arquivo:
        for registro in registros:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return len(registros)


def ids_ja_vistos(caminho: Path, campo: str) -> set[str]:
    return {registro[campo] for registro in ler_jsonl(caminho) if campo in registro}


def registrar_documento(
    manifesto: Path,
    doc: str,
    hash_doc: str,
    estado: str,
    paginas: int,
    chunks: int,
) -> None:
    anexar_jsonl(
        manifesto,
        {
            "doc": doc,
            "hash": hash_doc,
            "estado": estado,
            "paginas": paginas,
            "chunks": chunks,
            "processado_em": datetime.now(timezone.utc).isoformat(),
        },
    )


def documento_inalterado(manifesto: Path, doc: str, hash_doc: str) -> bool:
    for registro in ler_jsonl(manifesto):
        if registro.get("doc") == doc and registro.get("hash") == hash_doc:
            return True
    return False
