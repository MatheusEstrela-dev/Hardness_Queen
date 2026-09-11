"""Agrupamento de regras propostas pelo limiar que elas descrevem.

Varios documentos normativos podem afirmar o mesmo limiar (ex.: tres fontes
concordando que alerta_cor=laranja e chuva_acumulada entre 30 e 70 mm/h numa
janela de 1h). Isso e corroboracao, nao duplicacao: o revisor deve decidir
uma vez por limiar, vendo todas as fontes que o sustentam, nao uma vez por
ocorrencia -- hoje a fila mostra as tres como itens separados e o revisor
decide o mesmo limiar tres vezes.
"""

from ingestao.validacao import normalizar

# O que torna duas regras "o mesmo limiar": concordancia nestes campos.
#
# entidade_tipo/entidade_nome/dominio ficaram de fora enquanto o acervo era
# so de normas estaduais: eram constantes em todo grupo, e inclui-los nao
# mudava nada. Deixaram de ser com os Planos de Contingencia municipais --
# o "Nivel 1 a partir de 80 mm em 96h" de Ipatinga e o de outro municipio
# cairiam no mesmo grupo, e UMA decisao do revisor valeria para os dois.
# Pelo mesmo motivo entra o sentido: um limiar "acima de X" e um "abaixo de X"
# nao sao o mesmo limiar mesmo com o mesmo numero.
CAMPOS_CHAVE_LIMIAR = (
    "entidade_tipo",
    "entidade_nome",
    "dominio",
    "escala",
    "nivel",
    "grandeza",
    "unidade",
    "sentido",
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


# Campos que entraram no contrato depois que ja havia propostas gravadas. Uma
# proposta antiga nao os tem, e o valor que ela teria e o padrao do contrato:
# todo limiar anterior a eles era "acima de" (chuva, cota, vazao).
PADROES_DE_CAMPOS_NOVOS = {"sentido": "acima", "nivel_rotulo": None}


def _campo(regra: dict, campo: str):
    return regra[campo] if campo in regra else PADROES_DE_CAMPOS_NOVOS[campo]


def chave_limiar(regra: dict) -> tuple:
    # O nome da entidade e comparado normalizado: o parser de tabela tira o
    # municipio do nome do arquivo ("ipatinga") e o modelo copia do texto
    # ("Ipatinga"). Sem isso a mesma cidade abria dois grupos na fila. O valor
    # gravado continua o original -- e ele que o redator escreve no alerta.
    return tuple(
        normalizar(_campo(regra, campo)) if campo == "entidade_nome" else _campo(regra, campo)
        for campo in CAMPOS_CHAVE_LIMIAR
    )


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
            grupo = {campo: _campo(regra, campo) for campo in CAMPOS_CHAVE_LIMIAR}
            # Descritivo, fora da chave: o nome que o plano da ao nivel.
            grupo["nivel_rotulo"] = _campo(regra, "nivel_rotulo")
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
