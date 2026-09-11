from typing import Literal

from pydantic import BaseModel, Field, model_validator

Dominio = Literal["geologia", "hidrologia", "meteorologia"]
EntidadeTipo = Literal["tipo_solo", "bacia", "estacao", "municipio", "regiao", "estado"]
Grandeza = Literal[
    "chuva_acumulada",
    "cota",
    "vazao",
    "vento",
    "vil",
    "refletividade",
    "temperatura_topo",
    "taxa_precipitacao",
]
Unidade = Literal["mm", "m", "m3/s", "km/h", "kg/m2", "dBZ", "celsius", "mm/h"]

# Tres escalas de classificacao coexistem no acervo, e nao sao a mesma coisa:
#
# - alerta_cor: escala normativa ESTADUAL de MG (POP_ENVIO_DE_ALERTA_
#   HIDROMETEOROLOGICO N 6.1.3/2025, secao 6.2), cinco niveis nomeados por cor
#   sobre chuva acumulada (mm). Limiar de outro orgao estadual ou federal (ex.:
#   INMET, que usa perigo potencial / perigo / grande perigo) e mapeado para a
#   cor equivalente na extracao; fonte_trecho preserva o texto original.
# - intensidade: classifica a taxa de precipitacao (mm/h) em si -- quao forte
#   esta chovendo --, nao a resposta operacional a esse tanto de chuva. Vem de
#   tabelas como a de PROTOCOLO_ALERTAS_METEORO.docx (Fraca/Moderada/Forte/
#   Muito Forte/Extremo).
# - nivel_municipal: a escala propria de um Plano de Contingencia municipal.
#   NUNCA e convertida para cor. Medido em Ipatinga: o plano chama o Nivel 2 de
#   "Atencao (Amarelo)" e o aciona com 35 mm em 24h para deslizamento; o
#   "Amarelo" do POP estadual comeca em 60 mm. Mesma cor, limiar e resposta
#   diferentes -- converter faria um alerta municipal parecer estadual. E os
#   planos nem concordam entre si no vocabulario (Ipatinga: Observacao/Atencao/
#   Critico/Emergencial; Merces e Muzambinho: Atencao/Alerta/Emergencia), por
#   isso o nivel e ORDINAL (n1 menos grave) e o nome vai em nivel_rotulo, como
#   o documento escreve.
#
# As escalas sao relacionadas -- o POP deriva as cores dos patamares de
# acumulado -- mas misturar os niveis de uma na outra (ex.: rotular "Moderada"
# como uma cor) reproduziria o erro ja corrigido neste projeto em que um
# limiar estadual de chuva foi rotulado entidade_tipo=tipo_solo por falta de
# opcao melhor no vocabulario.
#
# - risco_ialc: as classes do IALC (planilha mantida pela CINDEC-CEDEC), um
#   limiar de chuva por municipio calibrado pelo historico de desastres do
#   S2iD. PREVALECE sobre o PlanCon quando os dois divergem (decisao do
#   usuario, 2026-09-11). As classes sao percentuais do limiar do municipio
#   (baixo 25%, moderado 50%, alto 75%, muito alto 90%, extremamente alto
#   100%); a planilha so traz o numero dos 100%.
Escala = Literal["alerta_cor", "intensidade", "nivel_municipal", "risco_ialc"]

NIVEIS_ALERTA_COR: frozenset[str] = frozenset({"verde", "amarelo", "laranja", "vermelho", "roxo"})
NIVEIS_INTENSIDADE: frozenset[str] = frozenset({"fraca", "moderada", "forte", "muito_forte", "extremo"})
NIVEIS_MUNICIPAIS: frozenset[str] = frozenset({"n1", "n2", "n3", "n4", "n5"})
NIVEIS_RISCO_IALC: frozenset[str] = frozenset(
    {"risco_baixo", "risco_moderado", "risco_alto", "risco_muito_alto", "risco_extremamente_alto"}
)

NIVEIS_POR_ESCALA: dict[str, frozenset[str]] = {
    "alerta_cor": NIVEIS_ALERTA_COR,
    "intensidade": NIVEIS_INTENSIDADE,
    "nivel_municipal": NIVEIS_MUNICIPAIS,
    "risco_ialc": NIVEIS_RISCO_IALC,
}

# Os niveis do IALC levam o prefixo "risco_" porque "moderado" e "alto" sem ele
# ficariam a uma letra de "moderada" (intensidade) -- num Literal fechado, o
# tipo de erro de digitacao que passa despercebido.
Nivel = Literal[
    "verde", "amarelo", "laranja", "vermelho", "roxo",
    "fraca", "moderada", "forte", "muito_forte", "extremo",
    "n1", "n2", "n3", "n4", "n5",
    "risco_baixo", "risco_moderado", "risco_alto", "risco_muito_alto", "risco_extremamente_alto",
]

# Para que lado o limiar aponta. "acima": o nivel vale a partir do valor, mais
# e pior -- chuva, cota, vazao, vento. "abaixo": menos e pior. O caso real ja no
# vocabulario e temperatura_topo (topo de nuvem mais frio = conveccao mais
# forte); os que vem pela frente sao o fator de seguranca de barragem e a
# altura de inundacao da legenda SGB. O gerador de dataset e o motor de alerta
# escolhem o nivel mais grave pelo sentido: sem este campo, um limiar "abaixo"
# seria lido ao contrario e o nivel sairia invertido.
Sentido = Literal["acima", "abaixo"]

# Grandezas em que "menos e pior" nao faz sentido fisico. Chuva abaixo de um
# valor nunca agrava risco hidrometeorologico; aceitar sentido="abaixo" aqui
# so poderia vir de erro de extracao.
GRANDEZAS_SO_ACIMA: frozenset[str] = frozenset({"chuva_acumulada", "taxa_precipitacao", "vazao", "cota"})

# Nome do nivel como o documento escreve ("Observacao", "Critico"). Curto por
# ser um rotulo, e limitado no schema porque o outlines monta a gramatica a
# partir dele: sem teto o modelo poderia gastar o orcamento de tokens aqui.
MAX_CHARS_NIVEL_ROTULO = 40
Status = Literal["ok", "suspeito"]
Veredito = Literal["aprovado", "rejeitado", "corrigido"]

# De onde a regra veio: "tabela" quando ingestao/tabelas.py leu uma linha de
# markdown por regra de codigo, "modelo" quando o Qwen inferiu a partir de
# prosa. So existe em Regra, nunca em RegraExtraida -- o modelo nunca produz
# a propria procedencia, e o parser de tabela tambem nao inventa a dele: quem
# atribui e o script, o mesmo lugar que ja atribui fonte_doc/fonte_pagina/
# fonte_secao. Serve ao portao humano: uma regra de tabela merece confianca
# diferente de uma inferida, e o revisor pode priorizar por isso.
Origem = Literal["tabela", "modelo"]


# Limites do excerto citado, medidos sobre as frases com padrao de limiar nos
# 92 chunks reais deste acervo: mediana 124 caracteres, p75 174, p90 237.
# Um teto de 100 (o primeiro valor adotado, calibrado em apenas dois exemplos
# de 46 e 68 caracteres) cobria so 35% dessas frases -- a gramatica truncava a
# citacao ANTES dos numeros e extremos_citados reprovava extracao correta:
# 44 das 89 suspeitas de uma execucao real eram esse falso positivo. 250
# cobre 91%.
#
# O teto nasceu para impedir que copiar uma linha da tabela de eventos
# (87-145 caracteres) esgotasse o orcamento de tokens antes do JSON fechar.
# Esse risco hoje e coberto por MAX_TOKENS_DE_SAIDA=4096, entao o teto pode
# servir ao seu proposito restante: manter a citacao curta o bastante para um
# humano conferir de relance, sem cortar a frase que sustenta o numero.
#
# O bound entra no JSON schema (minLength/maxLength) que outlines usa para
# montar a gramatica -- restricao estrutural, nao pedido no prompt.
MAX_CHARS_FONTE_TRECHO = 250

# O minimo barra citacao vazia ou de duas palavras soltas ("6 mm"), que nao
# permite a um revisor achar o numero no documento original.
MIN_CHARS_FONTE_TRECHO = 10


class RegraExtraida(BaseModel):
    """Exatamente o que o modelo produz. A procedencia de arquivo nao passa
    pelo modelo: quem anexa e o script, a partir dos metadados do chunk.

    O limiar e uma faixa, nao um valor unico:
    - valor_min e valor_max preenchidos: faixa fechada. "entre 6 mm e 30 mm"
      vira valor_min=6.0, valor_max=30.0.
    - so valor_min: limiar aberto para cima. "acima de 90 mm" e "90 mm ou
      mais" viram valor_min=90.0, valor_max=None.
    - so valor_max: limiar aberto para baixo.
    - Ambos os extremos sao inclusivos. A distincao entre > e >= nao e
      operacionalmente relevante num limiar de alerta.
    - Pelo menos um dos dois precisa estar preenchido -- uma regra sem
      nenhum extremo nao e um limiar.
    """

    dominio: Dominio
    entidade_tipo: EntidadeTipo
    entidade_nome: str
    grandeza: Grandeza
    # Fracionario de proposito: o PlanCon de Ipatinga tem limiar em 15 minutos
    # (0.25). Inteiro, essa linha da tabela nao tinha representacao e o modelo
    # era forcado a escrever 0 ou 1.
    janela_horas: float | None
    unidade: Unidade
    escala: Escala
    nivel: Nivel
    nivel_rotulo: str | None = Field(default=None, max_length=MAX_CHARS_NIVEL_ROTULO)
    sentido: Sentido = "acima"
    valor_min: float | None
    valor_max: float | None
    fonte_trecho: str = Field(min_length=MIN_CHARS_FONTE_TRECHO, max_length=MAX_CHARS_FONTE_TRECHO)

    @model_validator(mode="after")
    def _exige_pelo_menos_um_extremo(self) -> "RegraExtraida":
        if self.valor_min is None and self.valor_max is None:
            raise ValueError("regra precisa de valor_min ou valor_max preenchido")
        return self

    @model_validator(mode="after")
    def _janela_positiva(self) -> "RegraExtraida":
        if self.janela_horas is not None and self.janela_horas <= 0:
            raise ValueError(f"janela_horas precisa ser positiva, veio {self.janela_horas}")
        return self

    @model_validator(mode="after")
    def _escala_municipal_carrega_o_rotulo(self) -> "RegraExtraida":
        # n1..n5 sozinhos nao dizem nada a um revisor nem a quem le o alerta;
        # o nome que o plano da ao nivel e o que liga a regra ao documento.
        if self.escala == "nivel_municipal" and not (self.nivel_rotulo or "").strip():
            raise ValueError("escala nivel_municipal exige nivel_rotulo com o nome do nivel no documento")
        return self

    @model_validator(mode="after")
    def _sentido_coerente_com_grandeza(self) -> "RegraExtraida":
        if self.sentido == "abaixo" and self.grandeza in GRANDEZAS_SO_ACIMA:
            raise ValueError(f"{self.grandeza} com sentido 'abaixo' nao descreve agravamento de risco")
        return self

    @model_validator(mode="after")
    def _nivel_pertence_a_escala(self) -> "RegraExtraida":
        # O ponto inteiro do campo escala e este validador -- sem ele, as
        # duas escalas voltam a se misturar, so que agora com uma coluna a
        # mais para dar falsa sensacao de que estao separadas.
        permitidos = NIVEIS_POR_ESCALA[self.escala]
        if self.nivel not in permitidos:
            raise ValueError(f"nivel {self.nivel!r} nao pertence a escala {self.escala!r}")
        return self


class Extracao(BaseModel):
    regras: list[RegraExtraida]


class Chunk(BaseModel):
    chunk_id: str
    doc: str
    pagina: int | None
    secao: str | None
    texto: str


class Regra(RegraExtraida):
    regra_id: str
    chunk_id: str
    fonte_doc: str
    fonte_pagina: int | None
    fonte_secao: str | None
    origem: Origem
    status: Status
    motivo_suspeita: str | None = None


class Decisao(BaseModel):
    regra_id: str
    veredito: Veredito
    valor_min_corrigido: float | None = None
    valor_max_corrigido: float | None = None
    revisor: str
    decidido_em: str
