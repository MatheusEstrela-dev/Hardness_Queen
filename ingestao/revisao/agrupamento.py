"""Agrupamento de regras propostas pelo limiar que elas descrevem.

Varios documentos normativos podem afirmar o mesmo limiar (ex.: tres fontes
concordando que alerta_cor=laranja e chuva_acumulada entre 30 e 70 mm/h numa
janela de 1h). Isso e corroboracao, nao duplicacao: o revisor deve decidir
uma vez por limiar, vendo todas as fontes que o sustentam, nao uma vez por
ocorrencia -- hoje a fila mostra as tres como itens separados e o revisor
decide o mesmo limiar tres vezes.
"""

# O que torna duas regras "o mesmo limiar": concordancia nesses sete campos.
# entidade_tipo/entidade_nome/dominio ficam de fora de proposito -- nos dados
# reais do acervo (ver data/regras_propostas.jsonl) esses tres campos sao
# constantes dentro de cada grupo com mais de uma fonte, entao nao mudam o
# resultado do agrupamento; inclui-los so estreitaria o agrupamento sem
# ganho observado, e o pedido original de agrupamento e explicito sobre
# quais sete campos definem o limiar.
CAMPOS_CHAVE_LIMIAR = (
    "escala",
    "nivel",
    "grandeza",
    "unidade",
    "valor_min",
    "valor_max",
    "janela_horas",
)

# Campos de proveniencia minimos que cada fonte carrega dentro de um grupo.
CAMPOS_FONTE = (
    "regra_id",
    "fonte_doc",
    "fonte_pagina",
    "fonte_secao",
    "fonte_trecho",
    "status",
    "motivo_suspeita",
    "origem",
)


def chave_limiar(regra: dict) -> tuple:
    return tuple(regra[campo] for campo in CAMPOS_CHAVE_LIMIAR)


def agrupar_por_limiar(regras: list[dict], campos_fonte: tuple[str, ...] = CAMPOS_FONTE) -> list[dict]:
    """Agrupa regras que descrevem o mesmo limiar (mesma chave_limiar).

    Preserva a ordem de primeira aparicao de cada grupo (regras nao vistas
    antes abrem grupo na posicao em que aparecem; regras que reforcam um
    grupo existente nao movem sua posicao).

    Cada grupo carrega os sete campos do limiar, dominio/entidade_tipo/
    entidade_nome (da primeira fonte -- ver nota em CAMPOS_CHAVE_LIMIAR),
    a lista `fontes` (uma entrada por regra de origem, com os campos de
    `campos_fonte`) e `total_fontes`.

    O `status` do grupo e "suspeito" se QUALQUER fonte for suspeita, "ok"
    apenas se todas forem. Esconder uma fonte suspeita dentro de um grupo
    que parece limpo seria pior do que a duplicacao que este agrupamento
    substitui -- o revisor precisa ver que uma citacao diverge, nao so a
    media otimista do grupo. O detalhe de QUAL fonte esta suspeita continua
    disponivel: cada entrada de `fontes` mantem seu proprio `status` e
    `motivo_suspeita`.
    """
    grupos: dict[tuple, dict] = {}
    for regra in regras:
        chave = chave_limiar(regra)
        grupo = grupos.get(chave)
        if grupo is None:
            grupo = {campo: regra[campo] for campo in CAMPOS_CHAVE_LIMIAR}
            grupo["dominio"] = regra["dominio"]
            grupo["entidade_tipo"] = regra["entidade_tipo"]
            grupo["entidade_nome"] = regra["entidade_nome"]
            grupo["fontes"] = []
            grupos[chave] = grupo
        grupo["fontes"].append({campo: regra.get(campo) for campo in campos_fonte})

    for grupo in grupos.values():
        grupo["total_fontes"] = len(grupo["fontes"])
        grupo["status"] = (
            "suspeito"
            if any(fonte["status"] == "suspeito" for fonte in grupo["fontes"])
            else "ok"
        )
    return list(grupos.values())
