"""A escala de alerta da Defesa Civil de MG, transcrita dos protocolos.

Fonte: POP_ENVIO_DE_ALERTA_HIDROMETEOROLOGICO N 6.1.3/2025, secao 6.2, e
Instrucao Normativa COMPLETA de Alertas MG. Os textos de resposta operacional
sao parafrases fieis do que os documentos determinam para cada nivel -- nao
foram inventados, e e por isso que este modulo existe em vez de as frases
ficarem soltas no gerador de dataset.

Por que isso importa: o adaptador LoRA e treinado para REDIGIR o alerta a
partir de uma decisao que o banco ja tomou. Se ele aprender a redigir com uma
escala inventada, produz texto que soa plausivel e contradiz o protocolo --
o pior resultado possivel, porque parece certo.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NivelDeAlerta:
    """Um nivel da escala, com o que o protocolo manda fazer nele."""

    cor: str
    situacao: str
    # A resposta operacional, como o POP a descreve. E o que o modelo aprende
    # a escrever: o texto do alerta precisa dizer o que se espera de quem le.
    resposta: str
    # Ordem de gravidade, do menos para o mais grave. Serve para escolher o
    # nivel a partir de um valor observado sem depender da ordem do dicionario.
    gravidade: int


# Ordem: do menos para o mais grave.
ESCALA = (
    NivelDeAlerta(
        cor="verde",
        situacao="Sem Risco",
        resposta=(
            "Precipitacao de intensidade fraca, sem indicativos de risco iminente. "
            "O monitoramento segue em regime normal."
        ),
        gravidade=0,
    ),
    NivelDeAlerta(
        cor="amarelo",
        situacao="Situacao de Atencao",
        resposta=(
            "Recomenda-se o reforco da vigilancia e, se necessario, a emissao de "
            "alertas informativos via mensagens e canais oficiais."
        ),
        gravidade=1,
    ),
    NivelDeAlerta(
        cor="laranja",
        situacao="Situacao de Alerta",
        resposta=(
            "Recomendavel intensificar o monitoramento nas proximas horas. A situacao "
            "demanda mobilizacao das equipes e comunicacao preventiva com a populacao "
            "em areas vulneraveis."
        ),
        gravidade=2,
    ),
    NivelDeAlerta(
        cor="vermelho",
        situacao="Situacao de Perigo",
        resposta=(
            "Representa risco elevado de desastres, com necessidade de pronta resposta "
            "das autoridades competentes."
        ),
        gravidade=3,
    ),
    NivelDeAlerta(
        cor="roxo",
        situacao="Situacao Critica",
        resposta=(
            "Nivel maximo de alerta, indicando alto potencial de ocorrencias graves, "
            "como deslizamentos, alagamentos intensos e inundacoes. Exige resposta "
            "imediata, acoes emergenciais e possivel evacuacao preventiva."
        ),
        gravidade=4,
    ),
)

POR_COR = {nivel.cor: nivel for nivel in ESCALA}


def nivel_de(cor: str) -> NivelDeAlerta:
    return POR_COR[cor]


def mais_grave(cores: list[str]) -> NivelDeAlerta:
    """O nivel de maior gravidade entre os informados.

    Quando varios limiares sao ultrapassados ao mesmo tempo -- por exemplo o de
    1 hora e o de 24 horas -- o alerta emitido e o do nivel mais grave. Um
    alerta que reportasse o menos grave subestimaria a situacao.
    """
    return max((POR_COR[cor] for cor in cores), key=lambda n: n.gravidade)
