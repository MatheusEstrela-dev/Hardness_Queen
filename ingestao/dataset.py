"""Geracao dos exemplos de treino do adaptador que REDIGE alertas.

O adaptador nao decide limiar -- essa e a decisao do banco, por consulta
espacial. Ele aprende a transformar uma decisao ja tomada em texto tecnico que
a Defesa Civil emitiria. Por isso o dataset precisa de duas coisas certas: a
escala real de niveis (ingestao/niveis.py, transcrita dos protocolos) e os
limiares que de fato valem.

De onde vem o limiar, em ordem de preferencia:

1. data/regras_aprovadas.jsonl -- regras extraidas dos documentos e APROVADAS
   por um revisor humano. E a fonte correta: o gerador de dataset e o motor de
   alertas passam a beber do mesmo lugar, entao o modelo e sempre treinado com
   o que esta valendo.
2. LIMIARES_DE_PARTIDA abaixo -- usados enquanto o catalogo nao existe. Sao
   transcritos do POP, nao inventados, mas nao passaram pelo portao humano.

O script diz qual fonte usou. Isso importa: um dataset gerado da fonte 2 treina
o modelo com limiares que nenhuma pessoa homologou, e quem for usar o adaptador
precisa saber disso.

CURADORIA -- por que este modulo e mais que um formatador de string
-------------------------------------------------------------------
Um exemplo de treino errado nao aparece na loss: ele aparece meses depois, em
texto que soa certo. Cinco regras de curadoria, todas com teste em
tests/test_dataset_curadoria.py, e todas escritas depois de o gerador anterior
violar cada uma delas:

1. Nenhuma amostra subestima o nivel. Um valor amostrado dentro da faixa de um
   nivel nao pode ultrapassar o piso de um nivel mais grave da MESMA janela --
   senao o exemplo ensina a chamar de amarelo o que o protocolo chama de
   laranja. Por isso `_teto_efetivo`.
2. Nada de limiar de outro catalogo. Se o catalogo aprovado diz 175 mm, nenhum
   exemplo pode citar 170 mm, 70 mm ou 60 mm por estarem escritos no codigo.
   Todo numero de todo exemplo sai do catalogo em uso.
3. Escopo se respeita. Regra de um municipio gera exemplo daquele municipio; os
   municipios de LOCAIS entram so quando a regra vale para o estado.
4. Grandeza se respeita. Taxa e mm/h instantaneo e nao tem janela; acumulado e
   mm numa janela. Um exemplo que diz "acumulado de 130 mm/h em 24h" ensina uma
   confusao de unidade que nenhum revisor pediria.
5. Catalogo quebrado para o gerador, e nao cai no fallback em silencio. Cair no
   fallback quando o catalogo existe mas nao serve produz um dataset que parece
   homologado e nao e.

Cada exemplo escrito tem uma linha correspondente no arquivo de proveniencia
(mesmo nome, sufixo .proveniencia.jsonl), dizendo de quais regras ele saiu. O
arquivo de treino em si fica com prompt/completion e nada mais, porque o TRL le
todas as chaves do exemplo.
"""

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from ingestao.niveis import ESCALA, POR_COR, mais_grave, nivel_de

APROVADAS = Path("data/regras_aprovadas.jsonl")
SAIDA = Path("data/dataset_treino.jsonl")

SYSTEM_PROMPT = (
    "Voce redige alertas hidrometeorologicos para a Defesa Civil de Minas Gerais. "
    "Recebe uma decisao ja tomada -- nivel de alerta, limiar ultrapassado e local -- "
    "e escreve o texto tecnico do alerta. Nao decida o nivel: ele ja vem decidido."
)

# Transcritos do POP_ENVIO_DE_ALERTA_HIDROMETEOROLOGICO N 6.1.3/2025, secao 6.2.
# Cada entrada: (cor, janela_horas, valor_min, valor_max ou None).
LIMIARES_DE_PARTIDA = [
    ("amarelo", 1, 6.0, 30.0),
    ("amarelo", 24, 60.0, None),
    ("laranja", 1, 30.0, 70.0),
    ("laranja", 24, 90.0, None),
    ("vermelho", 1, 70.0, 90.0),
    ("vermelho", 24, 120.0, None),
    ("roxo", 1, 100.0, None),
    ("roxo", 24, 170.0, None),
]

# Municipios reais de MG, um por mesorregiao, para o modelo nao aprender a
# associar um nivel a um lugar especifico. Usados apenas para regra de alcance
# estadual: regra de um municipio gera exemplo daquele municipio.
LOCAIS = [
    ("Belo Horizonte", "Metropolitana"),
    ("Januaria", "Norte de Minas"),
    ("Teofilo Otoni", "Vale do Mucuri"),
    ("Uberlandia", "Triangulo Mineiro"),
    ("Juiz de Fora", "Zona da Mata"),
    ("Montes Claros", "Norte de Minas"),
]

# Grandezas que disparam alerta de chuva, e a unidade que cada uma exige. A
# unidade nao e decoracao: mm num intervalo e acumulado, mm/h e taxa. Trocar
# uma pela outra muda o fenomeno.
UNIDADE_DA_GRANDEZA = {"chuva_acumulada": "mm", "taxa_precipitacao": "mm/h"}

# Acumulado precisa de janela ("60 mm em quanto tempo?"); taxa e instantanea e
# ja traz o tempo na unidade -- janela numa taxa e erro de fator N.
EXIGE_JANELA = {"chuva_acumulada": True, "taxa_precipitacao": False}


@dataclass(frozen=True)
class Limiar:
    """Um limiar pronto para virar exemplo, com escopo e proveniencia.

    `fontes` e tupla porque duas regras aprovadas podem descrever o mesmo
    limiar (o mesmo numero aparece em dois documentos). Nesse caso vira UM
    limiar, e portanto um conjunto de exemplos, citando as duas regras.
    """

    cor: str
    janela_horas: int | None
    valor_min: float
    valor_max: float | None
    grandeza: str
    unidade: str
    escopo_tipo: str
    locais: tuple[tuple[str, str | None], ...]
    fontes: tuple[str, ...]

    @property
    def gravidade(self) -> int:
        return POR_COR[self.cor].gravidade

    def identidade(self) -> tuple:
        """Tudo que define o limiar, menos de onde ele veio."""
        return (
            self.cor,
            self.janela_horas,
            self.valor_min,
            self.valor_max,
            self.grandeza,
            self.unidade,
            self.escopo_tipo,
            self.locais,
        )


def _ler_aprovadas(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def _finito(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _escopo(regra: dict) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    """Onde a regra vale, e quais locais podem aparecer nos exemplos dela.

    Ausencia de escopo significa alcance estadual: e o caso das regras antigas
    e dos limiares de partida. Escopo presente mas vazio e registro quebrado --
    nao da para adivinhar onde a regra vale, e um exemplo com o local errado e
    pior que exemplo nenhum.
    """
    tipo = regra.get("entidade_tipo") or "estado"
    nome = regra.get("entidade_nome")
    if nome is not None and not str(nome).strip():
        raise ValueError(f"regra {regra.get('regra_id')} tem entidade_nome vazio")
    if tipo == "estado":
        return tipo, tuple(LOCAIS)
    if not nome:
        raise ValueError(f"regra {regra.get('regra_id')} e de {tipo} sem entidade_nome")
    return tipo, ((str(nome).strip(), None),)


def _validar(regra: dict) -> None:
    """Recusa o que nao da para transformar em exemplo honesto.

    Falha alto de proposito. O caminho silencioso -- pular a regra ruim e
    seguir com as boas, ou cair no fallback -- produz um dataset que se
    apresenta como homologado e nao corresponde ao catalogo.
    """
    identificacao = regra.get("regra_id", "sem regra_id")
    grandeza = regra.get("grandeza")

    if not _finito(regra.get("valor_min")):
        raise ValueError(f"regra {identificacao}: valor_min nao e numero finito")
    valor_max = regra.get("valor_max")
    if valor_max is not None:
        if not _finito(valor_max):
            raise ValueError(f"regra {identificacao}: valor_max nao e numero finito")
        if valor_max <= regra["valor_min"]:
            raise ValueError(
                f"regra {identificacao}: faixa invertida ou degenerada "
                f"({regra['valor_min']} a {valor_max})"
            )

    unidade = regra.get("unidade") or UNIDADE_DA_GRANDEZA[grandeza]
    if unidade != UNIDADE_DA_GRANDEZA[grandeza]:
        raise ValueError(
            f"regra {identificacao}: {grandeza} nao se mede em {unidade}, "
            f"e sim em {UNIDADE_DA_GRANDEZA[grandeza]}"
        )

    janela = regra.get("janela_horas")
    if EXIGE_JANELA[grandeza]:
        if janela is None:
            raise ValueError(f"regra {identificacao}: acumulado em {unidade} sem janela_horas")
        if not _finito(janela) or janela <= 0:
            raise ValueError(f"regra {identificacao}: janela_horas invalida ({janela})")
    elif janela is not None:
        raise ValueError(
            f"regra {identificacao}: taxa em {unidade} com janela_horas={janela} -- "
            "a unidade ja traz o tempo, a janela seria erro de fator"
        )

    if regra.get("nivel") not in POR_COR:
        raise ValueError(f"regra {identificacao}: nivel '{regra.get('nivel')}' fora da escala")


def _limiares_de_regras_aprovadas(regras: list[dict]) -> list[Limiar]:
    """Converte regras aprovadas em limiares deste gerador.

    So aproveita regras de chuva na escala de alerta por cor: sao as que
    disparam alerta. Regra de intensidade descreve o fenomeno e nao vira
    alerta por si; regra de outra grandeza entraria como exemplo de um texto
    que o adaptador ainda nao precisa saber redigir. O que passa esse filtro,
    porem, e validado: uma regra de alerta quebrada para o gerador.
    """
    limiares: list[Limiar] = []
    for regra in regras:
        if regra.get("escala") != "alerta_cor":
            continue
        if regra.get("grandeza") not in UNIDADE_DA_GRANDEZA:
            continue
        _validar(regra)
        tipo, locais = _escopo(regra)
        grandeza = regra["grandeza"]
        limiares.append(
            Limiar(
                cor=regra["nivel"],
                janela_horas=regra.get("janela_horas"),
                valor_min=float(regra["valor_min"]),
                valor_max=None if regra.get("valor_max") is None else float(regra["valor_max"]),
                grandeza=grandeza,
                unidade=regra.get("unidade") or UNIDADE_DA_GRANDEZA[grandeza],
                escopo_tipo=tipo,
                locais=locais,
                fontes=(str(regra.get("regra_id") or "sem regra_id"),),
            )
        )
    return _agrupar_equivalentes(limiares)


def _limiares_de_partida() -> list[Limiar]:
    return [
        Limiar(
            cor=cor,
            janela_horas=janela,
            valor_min=valor_min,
            valor_max=valor_max,
            grandeza="chuva_acumulada",
            unidade="mm",
            escopo_tipo="estado",
            locais=tuple(LOCAIS),
            fontes=("LIMIARES_DE_PARTIDA",),
        )
        for cor, janela, valor_min, valor_max in LIMIARES_DE_PARTIDA
    ]


def _agrupar_equivalentes(limiares: list[Limiar]) -> list[Limiar]:
    """Um limiar descrito por N regras vira um limiar com N fontes.

    Sem isso, duas regras aprovadas que dizem a mesma coisa (o mesmo numero
    citado em dois documentos) triplicariam o peso daquele limiar no treino --
    o modelo aprenderia que aquele caso e tres vezes mais comum do que e.
    """
    agrupados: dict[tuple, Limiar] = {}
    for limiar in limiares:
        chave = limiar.identidade()
        existente = agrupados.get(chave)
        if existente is None:
            agrupados[chave] = limiar
            continue
        fontes = tuple(dict.fromkeys(existente.fontes + limiar.fontes))
        agrupados[chave] = replace(existente, fontes=fontes)
    return list(agrupados.values())


# Posicoes dentro da faixa onde amostrar um valor observado. Tres pontos --
# logo acima do piso, no meio e perto do teto -- em vez de um so: o adaptador
# precisa aprender que qualquer valor DENTRO da faixa dispara o mesmo nivel, e
# nao decorar um numero especifico por nivel.
POSICOES_NA_FAIXA = (0.15, 0.5, 0.85)

# Multiplicadores para limiar aberto ("acima de X") sem nivel mais grave
# acima dele, pelo mesmo motivo.
ACIMA_DE = (1.05, 1.3, 1.8)


def _teto_efetivo(limiar: Limiar, catalogo: list[Limiar]) -> float | None:
    """Ate onde um valor pode subir sem virar caso de nivel mais grave.

    Este e o conserto da falha mais grave do gerador anterior. O limiar amarelo
    de 24h e "acima de 60 mm", aberto, e amostrar 1,8x dava 108 mm -- que na
    mesma janela de 24h e LARANJA (piso 90 mm). O exemplo dizia AMARELO. Um
    dataset assim ensina o modelo a subestimar a gravidade, que e exatamente o
    erro que um alerta nao pode cometer.

    O teto sai do proprio catalogo em uso: o menor piso entre os niveis mais
    graves da mesma grandeza e da mesma janela. Nao ha numero fixo aqui.
    """
    pisos = [
        outro.valor_min
        for outro in catalogo
        if outro.grandeza == limiar.grandeza
        and outro.janela_horas == limiar.janela_horas
        and outro.gravidade > limiar.gravidade
        and outro.valor_min > limiar.valor_min
    ]
    candidatos = [valor for valor in (limiar.valor_max, min(pisos) if pisos else None) if valor]
    return min(candidatos) if candidatos else None


def _observado(limiar: Limiar, teto: float | None, posicao: int) -> float:
    """Um valor observado plausivel que dispara este nivel e nenhum acima dele."""
    if teto is None:
        return round(limiar.valor_min * ACIMA_DE[posicao], 1)
    bruto = limiar.valor_min + (teto - limiar.valor_min) * POSICOES_NA_FAIXA[posicao]
    arredondado = round(bruto, 1)
    # Faixa estreita: o arredondamento pode empurrar o valor para fora dela, e
    # um valor fora da faixa e um exemplo com o nivel errado.
    return arredondado if limiar.valor_min < arredondado < teto else bruto


def _descrever_limiar(limiar: Limiar, teto: float | None) -> tuple[str, str]:
    """A frase do limiar para o enunciado, e a forma curta para o texto.

    Duas formas porque "ultrapassando o limiar de superior a 60 mm" nao e
    portugues. O enunciado descreve a regra ("superior a 60 mm em 24 horas"), o
    alerta cita o valor ("o limiar de 60 mm em 24 horas").
    """
    unidade = limiar.unidade
    if limiar.valor_max is not None:
        faixa = f"entre {limiar.valor_min:g} {unidade} e {limiar.valor_max:g} {unidade}"
        curto = f"{limiar.valor_min:g} {unidade} a {limiar.valor_max:g} {unidade}"
    else:
        faixa = f"superior a {limiar.valor_min:g} {unidade}"
        curto = f"{limiar.valor_min:g} {unidade}"
    if limiar.janela_horas is None:
        return faixa, curto
    plural = "s" if limiar.janela_horas != 1 else ""
    tempo = f" em {limiar.janela_horas:g} hora{plural}"
    return faixa + tempo, curto + tempo


def _janela_curta(limiar: Limiar) -> str:
    return f"{limiar.janela_horas:g}h"


def _medicao(limiar: Limiar, observado: float) -> tuple[str, str, str]:
    """Como a medicao aparece no enunciado e no alerta.

    Acumulado e taxa nao se descrevem com a mesma frase. "Acumulado de
    130 mm/h em 24h" mistura as duas e ensina uma confusao de unidade.
    """
    if limiar.grandeza == "taxa_precipitacao":
        nome = f"{observado:g} {limiar.unidade}"
        return (
            f"Taxa de precipitacao: {nome}",
            f"registrou taxa de precipitacao de {nome}",
            nome,
        )
    janela = _janela_curta(limiar)
    nome = f"{observado:g} {limiar.unidade} em {janela}"
    return (
        f"Acumulado em {janela}: {observado:g} {limiar.unidade}",
        f"registrou acumulado de {nome}",
        nome,
    )


# Tres redacoes para a mesma informacao. Com um molde unico o adaptador decora
# a frase em vez de aprender a estrutura; variando a forma e mantendo o
# conteudo, ele aprende o que precisa estar no alerta, nao como soa.
MOLDES = (
    "{cabecalho} {sujeito} {medicao_verbo}, ultrapassando o limiar de {limiar_curto} "
    "definido para este nivel. {resposta}",
    "{cabecalho} Registro de {medicao_nome} {sujeito}. O valor supera o limiar de "
    "{limiar_curto}. {resposta}",
    "{cabecalho} {sujeito} {medicao_nome} acima do limiar de {limiar_curto} estabelecido "
    "para o nivel. {resposta}",
)

# Como o local entra na frase, em tres construcoes -- uma por molde. Regiao nao
# se chama de municipio, e local sem mesorregiao conhecida nao ganha uma
# inventada: o rotulo geografico errado seria uma alucinacao introduzida por
# nos, no dado de treino.
SUJEITOS = {
    "municipio": ("O municipio de {nome}", "no municipio de {nome}", "{nome}"),
    "regiao": ("A regiao {nome}", "na regiao {nome}", "{nome}"),
    "estado": ("O municipio de {nome}", "no municipio de {nome}", "{nome}"),
}


def _sujeito(escopo_tipo: str, local: tuple[str, str | None], molde: int) -> str:
    nome, mesorregiao = local
    base = SUJEITOS[escopo_tipo][molde].format(nome=nome)
    if mesorregiao is None:
        return f"{base}:" if molde == 2 else base
    if molde == 0:
        return f"{base}, na mesorregiao {mesorregiao},"
    if molde == 1:
        return f"{base} ({mesorregiao})"
    return f"{base}, mesorregiao {mesorregiao}:"


def _rotular(local: tuple[str, str | None]) -> str:
    nome, mesorregiao = local
    return f"{nome} ({mesorregiao})" if mesorregiao else nome


def _montar(pergunta: str, resposta: str) -> dict:
    return {
        "prompt": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": pergunta},
        ],
        "completion": [{"role": "assistant", "content": resposta}],
    }


def _exemplo(limiar: Limiar, teto: float | None, local: tuple, posicao: int) -> dict:
    nivel = nivel_de(limiar.cor)
    observado = _observado(limiar, teto, posicao)
    faixa, curto = _descrever_limiar(limiar, teto)
    entrada, verbo, nome = _medicao(limiar, observado)

    pergunta = (
        f"Municipio: {_rotular(local)}. "
        f"{entrada}. "
        f"Limiar do nivel {nivel.cor} ({nivel.situacao}): {faixa}. "
        "Redija o alerta."
    )
    molde = posicao % len(MOLDES)
    resposta = MOLDES[molde].format(
        cabecalho=f"NIVEL {nivel.cor.upper()} - {nivel.situacao}.",
        sujeito=_sujeito(limiar.escopo_tipo, local, molde),
        medicao_verbo=verbo,
        medicao_nome=nome,
        limiar_curto=curto,
        resposta=nivel.resposta,
    )
    return _montar(pergunta, resposta)


def _exemplo_verde(escopo_tipo: str, local: tuple) -> dict:
    """O nivel verde nao tem limiar numerico, e precisa estar no dataset.

    Sem ele o modelo so ve situacoes de alerta e aprende a sempre alarmar --
    e "sem risco, monitoramento em regime normal" e uma saida legitima que ele
    tambem tem de saber redigir.

    Nao cita medicao nenhuma de proposito. O gerador anterior escrevia "12 mm
    em 24h", numero que nao vem de catalogo algum: com o catalogo de taxa, por
    exemplo, aquele exemplo falava de acumulado que ninguem mediu.
    """
    nivel = nivel_de("verde")
    return _montar(
        (
            f"Municipio: {_rotular(local)}. Nenhum limiar de alerta ultrapassado -- "
            "situacao de nivel verde. Redija o informe."
        ),
        (
            f"NIVEL {nivel.cor.upper()} - {nivel.situacao}. {_sujeito(escopo_tipo, local, 0)} "
            f"nao registrou valores acima dos limiares de alerta. {nivel.resposta}"
        ),
    )


def _par_de_limiares(catalogo: list[Limiar]) -> tuple[Limiar, Limiar] | None:
    """Dois limiares de janelas diferentes que podem ser ultrapassados juntos.

    Serve ao exemplo que ensina "vale o mais grave". Ha duas armadilhas:

    - a redacao nao pode sair do codigo. O exemplo anterior tinha 78 mm e 65 mm
      escritos a mao, e reaparecia num dataset gerado de um catalogo que nao
      contem nenhum desses numeros.
    - o par tem de ser fisicamente possivel. Aquele mesmo exemplo dizia 78 mm
      em 1h e 65 mm em 24h -- o acumulado de 24h nao pode ser menor que o de
      1h, ele contem o de 1h. Um cenario impossivel ensina que a coerencia
      entre janelas nao importa.

    Escolhe o par de maior diferenca de gravidade, para a licao ficar clara.
    """
    melhor: tuple[Limiar, Limiar] | None = None
    for curto in catalogo:
        for longo in catalogo:
            if curto.grandeza != longo.grandeza or curto.locais != longo.locais:
                continue
            if curto.janela_horas is None or longo.janela_horas is None:
                continue
            if curto.janela_horas >= longo.janela_horas or curto.gravidade == longo.gravidade:
                continue
            valor_curto = _observado(curto, _teto_efetivo(curto, catalogo), 1)
            valor_longo = _observado(longo, _teto_efetivo(longo, catalogo), 1)
            if valor_curto > valor_longo:
                continue
            candidato = (curto, longo)
            if melhor is None or abs(curto.gravidade - longo.gravidade) > abs(
                melhor[0].gravidade - melhor[1].gravidade
            ):
                melhor = candidato
    return melhor


def _exemplo_dois_limiares(
    par: tuple[Limiar, Limiar], catalogo: list[Limiar], local: tuple
) -> dict:
    """Dois limiares ultrapassados ao mesmo tempo: vale o mais grave."""
    curto, longo = par
    nivel = mais_grave([curto.cor, longo.cor])
    partes_pergunta = []
    partes_resposta = []
    for limiar in (curto, longo):
        observado = _observado(limiar, _teto_efetivo(limiar, catalogo), 1)
        faixa, curto_txt = _descrever_limiar(limiar, None)
        entrada, _, nome = _medicao(limiar, observado)
        partes_pergunta.append(f"{entrada} (limiar do nivel {limiar.cor}: {faixa})")
        partes_resposta.append(f"{nome}, acima do limiar de {curto_txt}")

    return _montar(
        (
            f"Municipio: {_rotular(local)}. {partes_pergunta[0]}. {partes_pergunta[1]}. "
            "Redija o alerta."
        ),
        (
            f"NIVEL {nivel.cor.upper()} - {nivel.situacao}. "
            f"{_sujeito(curto.escopo_tipo, local, 0)} registrou {partes_resposta[0]}, e "
            f"{partes_resposta[1]}. Prevalece o nivel de maior gravidade. {nivel.resposta}"
        ),
    )


def _proveniencia(caminho_saida: Path) -> Path:
    return caminho_saida.with_suffix(".proveniencia.jsonl")


def _registrar(exemplos: list[tuple[dict, tuple[str, ...]]], fonte: str) -> list[dict]:
    """Uma linha de proveniencia por linha de dataset, na mesma ordem.

    Fica fora do arquivo de treino porque o TRL le todas as chaves do exemplo:
    um campo extra ali mudaria o que entra no prompt.
    """
    registros = []
    for numero, (exemplo, fontes) in enumerate(exemplos, 1):
        canonico = json.dumps(exemplo, sort_keys=True, ensure_ascii=False)
        registros.append(
            {
                "linha": numero,
                "tipo": "sintetico",
                "fonte_catalogo": fonte,
                "regras": list(fontes),
                "exemplo_sha256": hashlib.sha256(canonico.encode("utf-8")).hexdigest(),
            }
        )
    return registros


def _catalogo(caminho_aprovadas: Path) -> tuple[list[Limiar], str, str]:
    """O catalogo em uso, seu rotulo curto e a descricao para o operador.

    Catalogo ausente cai para os limiares do POP -- e o estado de quem ainda
    nao revisou nada. Catalogo presente sem nenhum limiar de alerta e outra
    coisa: alguem revisou e o resultado nao serve para treinar. Cair no
    fallback nesse caso entregaria um dataset com cara de homologado.
    """
    aprovadas = _ler_aprovadas(caminho_aprovadas)
    if not aprovadas:
        limiares = _limiares_de_partida()
        return (
            limiares,
            "limiares_de_partida",
            f"LIMIARES_DE_PARTIDA ({len(limiares)} transcritos do POP) -- "
            f"'{caminho_aprovadas}' vazio ou inexistente, NENHUM limiar passou por revisao humana",
        )

    limiares = _limiares_de_regras_aprovadas(aprovadas)
    if not limiares:
        raise ValueError(
            f"'{caminho_aprovadas}' tem {len(aprovadas)} regra(s) mas nenhum limiar de alerta "
            "por cor em chuva -- nao ha o que treinar. Reveja o catalogo em vez de gerar um "
            "dataset a partir dos limiares de partida, que nao foram homologados."
        )
    return (
        limiares,
        "regras_aprovadas",
        f"{caminho_aprovadas} ({len(limiares)} limiares de regras aprovadas por revisor)",
    )


def gerar(caminho_saida: Path = SAIDA, caminho_aprovadas: Path = APROVADAS) -> int:
    """Gera o dataset. A origem dos limiares e parametro, nao global de modulo:
    assim o teste passa um caminho em vez de remendar o modulo."""
    catalogo, rotulo, descricao = _catalogo(caminho_aprovadas)

    # Combinatoria deliberada: cada limiar vira um exemplo por local do seu
    # escopo e por posicao dentro da faixa. Dez exemplos ensinam a abertura do
    # alerta e nada mais -- medido: o adaptador treinado com 10 acertava
    # "NIVEL VERMELHO" e depois perdia a linha. O material e o mesmo; o que
    # muda e a repeticao do padrao com conteudo variado, que e o que treina uma
    # tarefa de preencher molde como esta (quem decide o nivel e o banco).
    gerados: list[tuple[dict, tuple[str, ...]]] = []
    for limiar in catalogo:
        teto = _teto_efetivo(limiar, catalogo)
        for local in limiar.locais:
            for posicao in range(len(POSICOES_NA_FAIXA)):
                gerados.append((_exemplo(limiar, teto, local, posicao), limiar.fontes))

    # Verde e o par de limiares nao pertencem a um limiar so: saem do catalogo
    # inteiro, e por isso citam todas as regras dele.
    todas_as_fontes = tuple(dict.fromkeys(f for limiar in catalogo for f in limiar.fontes))
    escopos = tuple(dict.fromkeys((l.escopo_tipo, l.locais) for l in catalogo))
    for escopo_tipo, locais in escopos:
        for local in locais:
            gerados.append((_exemplo_verde(escopo_tipo, local), todas_as_fontes))

    par = _par_de_limiares(catalogo)
    if par is not None:
        for local in par[0].locais:
            gerados.append((_exemplo_dois_limiares(par, catalogo, local), todas_as_fontes))

    # Rede de seguranca: se dois caminhos produzirem o mesmo texto, ele entra
    # uma vez, com as fontes de ambos. Exemplo repetido e peso extra no treino.
    unicos: dict[str, tuple[dict, tuple[str, ...]]] = {}
    for exemplo, fontes in gerados:
        chave = json.dumps(exemplo, sort_keys=True, ensure_ascii=False)
        anterior = unicos.get(chave)
        if anterior is None:
            unicos[chave] = (exemplo, fontes)
        else:
            unicos[chave] = (anterior[0], tuple(dict.fromkeys(anterior[1] + fontes)))
    exemplos = list(unicos.values())

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    with caminho_saida.open("w", encoding="utf-8") as arquivo:
        for exemplo, _ in exemplos:
            arquivo.write(json.dumps(exemplo, ensure_ascii=False) + "\n")
    with _proveniencia(caminho_saida).open("w", encoding="utf-8") as arquivo:
        for registro in _registrar(exemplos, rotulo):
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")

    print(f"Fonte dos limiares: {descricao}")
    print(f"{len(exemplos)} exemplos escritos em '{caminho_saida}'.")
    print(f"Proveniencia em '{_proveniencia(caminho_saida)}'.")
    niveis_cobertos = {e["completion"][0]["content"].split()[1] for e, _ in exemplos}
    print(f"Niveis cobertos: {', '.join(sorted(niveis_cobertos))}")
    faltando = {n.cor.upper() for n in ESCALA} - niveis_cobertos
    if faltando:
        print(
            f"ATENCAO: nenhum exemplo para {', '.join(sorted(faltando))} -- "
            "o modelo nao aprende a redigir esses niveis."
        )
    return len(exemplos)
