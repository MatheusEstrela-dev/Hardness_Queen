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
    escala: str,
    nivel: str,
    valor_min: float | None,
    valor_max: float | None,
    janela_horas: float | None = None,
    dominio: str | None = None,
) -> str:
    # janela e dominio entraram depois de uma colisao real: na tabela do
    # PlanCon de Ipatinga, "deslizamento, 96h, Nivel 1 = 80 mm" e "inundacao,
    # 24h, Nivel 1 = 80 mm" saem do mesmo chunk com os mesmos oito campos
    # anteriores -- mesmo id, e a segunda regra sobrescreveria a primeira.
    return _hash(
        chunk_id, entidade_tipo, entidade_nome, grandeza, escala, nivel,
        valor_min, valor_max, janela_horas, dominio,
    )


def regra_id_de(chunk_id: str, regra) -> str:
    """O id de uma RegraExtraida -- o unico jeito de montar o id a partir dela.

    Os dois produtores de regra (parser de tabela e modelo) chamam isto, para
    que nunca divirjam sobre quais campos definem a identidade.
    """
    return regra_id(
        chunk_id, regra.entidade_tipo, regra.entidade_nome, regra.grandeza, regra.escala,
        regra.nivel, regra.valor_min, regra.valor_max, regra.janela_horas, regra.dominio,
    )
