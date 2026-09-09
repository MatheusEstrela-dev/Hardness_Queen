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

# Duas escalas de classificacao coexistem no acervo, e nao sao a mesma coisa:
#
# - alerta_cor: escala normativa de MG (POP_ENVIO_DE_ALERTA_HIDROMETEOROLOGICO
#   N 6.1.3/2025, secao 6.2), cinco niveis nomeados por cor sobre chuva
#   acumulada (mm). Limiar vindo de outra fonte (ex.: INMET, que usa perigo
#   potencial / perigo / grande perigo) e mapeado para a cor equivalente na
#   extracao; fonte_trecho preserva o texto original.
# - intensidade: classifica a taxa de precipitacao (mm/h) em si -- quao forte
#   esta chovendo --, nao a resposta operacional a esse tanto de chuva. Vem de
#   tabelas como a de PROTOCOLO_ALERTAS_METEORO.docx (Fraca/Moderada/Forte/
#   Muito Forte/Extremo).
#
# As duas escalas sao relacionadas -- o POP deriva as cores dos patamares de
# acumulado -- mas misturar os niveis de uma na outra (ex.: rotular "Moderada"
# como uma cor) reproduziria o erro ja corrigido neste projeto em que um
# limiar estadual de chuva foi rotulado entidade_tipo=tipo_solo por falta de
# opcao melhor no vocabulario.
Escala = Literal["alerta_cor", "intensidade"]

NIVEIS_ALERTA_COR: frozenset[str] = frozenset({"verde", "amarelo", "laranja", "vermelho", "roxo"})
NIVEIS_INTENSIDADE: frozenset[str] = frozenset({"fraca", "moderada", "forte", "muito_forte", "extremo"})

NIVEIS_POR_ESCALA: dict[str, frozenset[str]] = {
    "alerta_cor": NIVEIS_ALERTA_COR,
    "intensidade": NIVEIS_INTENSIDADE,
}

Nivel = Literal["verde", "amarelo", "laranja", "vermelho", "roxo", "fraca", "moderada", "forte", "muito_forte", "extremo"]
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
    janela_horas: int | None
    unidade: Unidade
    escala: Escala
    nivel: Nivel
    valor_min: float | None
    valor_max: float | None
    # Um excerto serve para um humano confirmar um numero e para
    # trecho_confere localiza-lo no chunk de origem -- nenhuma das duas
    # coisas precisa de centenas de caracteres. Os limiares genuinos deste
    # acervo citam algo como "podendo variar entre 6 mm e 30 mm em uma
    # hora" (46 caracteres) ou "Previsao ou ocorrencia de acumulados entre
    # 30 mm e 70 mm em 1 hora" (68 caracteres); 100 deixa folga confortavel
    # acima disso. Ao mesmo tempo, isso torna impossivel copiar uma linha
    # da tabela de eventos historicos de PROTOCOLO_ALERTAS_METEORO.docx (9
    # linhas x 7 colunas, celulas multi-linha em <br>), cuja linha mais
    # curta tem 87 caracteres e a mais longa 145 -- foi copiar uma dessas
    # linhas que esgotou o orcamento de tokens antes do JSON fechar
    # (task-16). O minimo de 10 barra uma citacao vazia ou de duas
    # palavras soltas ("6 mm"), que nao verifica nada.
    #
    # O bound entra no JSON schema (minLength/maxLength) que outlines usa
    # para montar a gramatica de decodificacao -- constrangimento
    # estrutural, nao pedido no prompt. Confirmado em
    # outlines_core.build_regex_from_schema: o regex gerado para uma string
    # com esses bounds usa repeticao limitada, ex. "{10,100}", entao o
    # decodificador nao tem caminho para emitir um token alem do teto.
    fonte_trecho: str = Field(min_length=10, max_length=100)

    @model_validator(mode="after")
    def _exige_pelo_menos_um_extremo(self) -> "RegraExtraida":
        if self.valor_min is None and self.valor_max is None:
            raise ValueError("regra precisa de valor_min ou valor_max preenchido")
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
