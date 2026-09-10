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
2. LIMIARES_DE_PARTIDA abaixo -- usados enquanto ninguem revisou nada. Sao
   transcritos do POP, nao inventados, mas nao passaram pelo portao humano.

O script diz qual fonte usou. Isso importa: um dataset gerado da fonte 2 treina
o modelo com limiares que nenhuma pessoa homologou, e quem for usar o adaptador
precisa saber disso.
"""

import json
from pathlib import Path

from ingestao.niveis import ESCALA, mais_grave, nivel_de

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
# associar um nivel a um lugar especifico.
LOCAIS = [
    ("Belo Horizonte", "Metropolitana"),
    ("Januaria", "Norte de Minas"),
    ("Teofilo Otoni", "Vale do Mucuri"),
    ("Uberlandia", "Triangulo Mineiro"),
    ("Juiz de Fora", "Zona da Mata"),
    ("Montes Claros", "Norte de Minas"),
]


def _ler_aprovadas(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def _limiares_de_regras_aprovadas(regras: list[dict]) -> list[tuple]:
    """Converte regras aprovadas no formato de limiar deste gerador.

    So aproveita regras de chuva na escala de alerta por cor: sao as que
    disparam alerta. Regra de intensidade descreve o fenomeno e nao vira
    alerta por si; regra de outra grandeza entraria como exemplo de um texto
    que o adaptador ainda nao precisa saber redigir.
    """
    limiares = []
    for regra in regras:
        if regra.get("escala") != "alerta_cor":
            continue
        if regra.get("grandeza") not in ("chuva_acumulada", "taxa_precipitacao"):
            continue
        if regra.get("valor_min") is None:
            continue
        limiares.append(
            (regra["nivel"], regra.get("janela_horas"), regra["valor_min"], regra.get("valor_max"))
        )
    return limiares


def _descrever_limiar(valor_min: float, valor_max: float | None, janela: int | None) -> str:
    faixa = f"entre {valor_min:g} mm e {valor_max:g} mm" if valor_max else f"superior a {valor_min:g} mm"
    if janela is None:
        return faixa
    return f"{faixa} em {janela} hora" + ("s" if janela != 1 else "")


def _observado(valor_min: float, valor_max: float | None) -> float:
    """Um valor observado plausivel dentro da faixa do limiar."""
    if valor_max is not None:
        return round(valor_min + (valor_max - valor_min) * 0.6, 1)
    return round(valor_min * 1.15, 1)


def _exemplo(cor: str, janela: int | None, valor_min: float, valor_max: float | None, local: tuple) -> dict:
    municipio, mesorregiao = local
    nivel = nivel_de(cor)
    observado = _observado(valor_min, valor_max)
    limiar = _descrever_limiar(valor_min, valor_max, janela)
    janela_txt = f"{janela}h" if janela else "1h"

    pergunta = (
        f"Municipio: {municipio} ({mesorregiao}). "
        f"Acumulado em {janela_txt}: {observado:g} mm. "
        f"Limiar do nivel {nivel.cor} ({nivel.situacao}): {limiar}. "
        "Redija o alerta."
    )
    resposta = (
        f"NIVEL {nivel.cor.upper()} - {nivel.situacao}. "
        f"O municipio de {municipio}, na mesorregiao {mesorregiao}, registrou acumulado de "
        f"{observado:g} mm em {janela_txt}, ultrapassando o limiar de {limiar} definido para "
        f"este nivel. {nivel.resposta}"
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": pergunta},
            {"role": "assistant", "content": resposta},
        ]
    }


def _exemplo_verde(local: tuple) -> dict:
    """O nivel verde nao tem limiar numerico, e precisa estar no dataset.

    Sem ele o modelo so ve situacoes de alerta e aprende a sempre alarmar --
    e "sem risco, monitoramento em regime normal" e uma saida legitima que ele
    tambem tem de saber redigir.
    """
    municipio, mesorregiao = local
    nivel = nivel_de("verde")
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Municipio: {municipio} ({mesorregiao}). Acumulado em 24h: 12 mm. "
                    "Nenhum limiar de alerta ultrapassado. Redija o informe."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    f"NIVEL {nivel.cor.upper()} - {nivel.situacao}. O municipio de {municipio}, "
                    f"na mesorregiao {mesorregiao}, registrou 12 mm em 24h, abaixo dos limiares "
                    f"de alerta. {nivel.resposta}"
                ),
            },
        ]
    }


def _exemplo_dois_limiares(local: tuple) -> dict:
    """Dois limiares ultrapassados ao mesmo tempo: vale o mais grave.

    Caso real: chuva forte numa hora e acumulado alto em 24h disparam niveis
    diferentes. Um alerta que reportasse o menos grave subestimaria a situacao.
    """
    municipio, mesorregiao = local
    nivel = mais_grave(["amarelo", "vermelho"])
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Municipio: {municipio} ({mesorregiao}). Acumulado em 1h: 78 mm "
                    "(limiar vermelho: entre 70 mm e 90 mm). Acumulado em 24h: 65 mm "
                    "(limiar amarelo: superior a 60 mm). Redija o alerta."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    f"NIVEL {nivel.cor.upper()} - {nivel.situacao}. O municipio de {municipio}, "
                    f"na mesorregiao {mesorregiao}, registrou 78 mm em 1h, ultrapassando o limiar "
                    "de entre 70 mm e 90 mm, e 65 mm em 24h, acima do limiar de 60 mm. Prevalece o "
                    f"nivel de maior gravidade. {nivel.resposta}"
                ),
            },
        ]
    }


def gerar(caminho_saida: Path = SAIDA, caminho_aprovadas: Path = APROVADAS) -> int:
    """Gera o dataset. A origem dos limiares e parametro, nao global de modulo:
    assim o teste passa um caminho em vez de remendar o modulo."""
    aprovadas = _ler_aprovadas(caminho_aprovadas)
    limiares = _limiares_de_regras_aprovadas(aprovadas)

    if limiares:
        fonte = f"{caminho_aprovadas} ({len(limiares)} limiares de regras aprovadas por revisor)"
    else:
        limiares = LIMIARES_DE_PARTIDA
        fonte = (
            f"LIMIARES_DE_PARTIDA ({len(limiares)} transcritos do POP) -- "
            f"'{caminho_aprovadas}' vazio ou inexistente, NENHUM limiar passou por revisao humana"
        )

    exemplos = []
    for indice, (cor, janela, valor_min, valor_max) in enumerate(limiares):
        exemplos.append(_exemplo(cor, janela, valor_min, valor_max, LOCAIS[indice % len(LOCAIS)]))
    exemplos.append(_exemplo_verde(LOCAIS[0]))
    exemplos.append(_exemplo_dois_limiares(LOCAIS[1]))

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    with caminho_saida.open("w", encoding="utf-8") as arquivo:
        for exemplo in exemplos:
            arquivo.write(json.dumps(exemplo, ensure_ascii=False) + "\n")

    print(f"Fonte dos limiares: {fonte}")
    print(f"{len(exemplos)} exemplos escritos em '{caminho_saida}'.")
    niveis_cobertos = {e["messages"][2]["content"].split()[1] for e in exemplos}
    print(f"Niveis cobertos: {', '.join(sorted(niveis_cobertos))}")
    faltando = {n.cor.upper() for n in ESCALA} - niveis_cobertos
    if faltando:
        print(f"ATENCAO: nenhum exemplo para {', '.join(sorted(faltando))} -- o modelo nao aprende a redigir esses niveis.")
    return len(exemplos)
