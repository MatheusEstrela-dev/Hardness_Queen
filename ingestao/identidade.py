import hashlib


def _hash(*partes: object) -> str:
    bruto = "|".join("" if parte is None else str(parte) for parte in partes)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]


def chunk_id(doc: str, pagina: int | None, texto: str) -> str:
    return _hash(doc, pagina, texto)


def regra_id(
    chunk_id: str,
    entidade_tipo: str,
    entidade_nome: str,
    grandeza: str,
    nivel: str,
    valor_min: float | None,
    valor_max: float | None,
) -> str:
    return _hash(chunk_id, entidade_tipo, entidade_nome, grandeza, nivel, valor_min, valor_max)
