"""Parser deterministico de tabelas markdown para regras de limiar.

Responsabilidade unica: dado o texto de um chunk, devolver as regras que
suas tabelas markdown declaram. Nao conhece modelo, nao conhece GPU, nao faz
I/O -- por isso e testavel em milissegundos e confiavel em producao (ver
task-19). Onde o texto nao tem tabela reconhecivel, este modulo devolve lista
vazia; quem decide chamar o modelo como alternativa e ingestao/extrator_regras.

A gramatica de limiar e a de rotulos abaixo sao fechadas de proposito: cada
forma foi observada nos documentos reais da Cedec (ver task-19-brief.md). Uma
linha de tabela que nao casa com nenhuma forma conhecida nao vira regra -- ela
e contada como "ignorada" para o operador saber que existiu, sem que o parser
arrisque um palpite.
"""

import re

from pydantic import ValidationError

from ingestao.contrato import Chunk, Regra, RegraExtraida
from ingestao.identidade import regra_id
from ingestao.validacao import classificar, normalizar

# entidade_tipo/entidade_nome para toda regra lida de tabela: uma tabela
# normativa estadual (ex.: PROTOCOLO_ALERTAS_METEORO.docx, Instrucao
# Normativa) nao nomeia bacia, estacao ou municipio -- o limiar vale para
# Minas Gerais inteira. Mesmo par que o prompt do modelo ja instrui para o
# caso equivalente (ver INSTRUCAO em extrator_regras.py), para as duas
# origens ficarem consistentes.
_ENTIDADE_TIPO = "estado"
_ENTIDADE_NOME = "minas gerais"

# grandeza determina o dominio de origem no acervo real: taxa/acumulado de
# chuva, vento e os indices de radar/satelite (refletividade, VIL,
# temperatura de topo) sao lidos pelo monitoramento meteorologico do
# CINDEC (ver POP_MONITORAMENTO_METEOROLOGICO.docx); cota e vazao vem de
# estacao fluviometrica, hidrologia. Nenhuma tabela real deste acervo declara
# limiar de geologia (os limiares de solo/deslizamento chegam em prosa), por
# isso "geologia" nao aparece neste mapa -- adicionar uma entrada aqui sem um
# exemplo real seria alargar a gramatica fechada sem evidencia.
_GRANDEZA_PARA_DOMINIO: dict[str, str] = {
    "taxa_precipitacao": "meteorologia",
    "chuva_acumulada": "meteorologia",
    "vento": "meteorologia",
    "refletividade": "meteorologia",
    "vil": "meteorologia",
    "temperatura_topo": "meteorologia",
    "cota": "hidrologia",
    "vazao": "hidrologia",
}

# Vocabulario fechado de rotulos, colhido dos documentos reais (task-19-brief,
# secao "Vocabulario de rotulos"). Cada chave ja esta em forma normalizada
# (sem acento, minusculo, espacos simples) porque a comparacao usa
# normalizar() antes de consultar este dicionario -- nunca o contrario.
_ROTULOS: dict[str, tuple[str, str]] = {
    "fraca": ("intensidade", "fraca"),
    "moderada": ("intensidade", "moderada"),
    "forte": ("intensidade", "forte"),
    "muito forte": ("intensidade", "muito_forte"),
    "extremo": ("intensidade", "extremo"),
    "verde": ("alerta_cor", "verde"),
    "amarelo": ("alerta_cor", "amarelo"),
    "laranja": ("alerta_cor", "laranja"),
    "vermelho": ("alerta_cor", "vermelho"),
    "roxo": ("alerta_cor", "roxo"),
    # sinonimos que os protocolos usam junto das cores -- a Instrucao
    # Normativa escreve "Nivel Amarelo (Situacao de Atencao)", entao a
    # sinonimia precisa casar mesmo quando so a situacao aparece na celula.
    "sem risco": ("alerta_cor", "verde"),
    "atencao": ("alerta_cor", "amarelo"),
    "alerta": ("alerta_cor", "laranja"),
    "perigo": ("alerta_cor", "vermelho"),
    "critica": ("alerta_cor", "roxo"),
    "critico": ("alerta_cor", "roxo"),
}

_NUM = r"\d+(?:[.,]\d+)?"

# Ordem fechada e deliberada: "mm/h" precisa ser tentada antes de "mm" (uma
# taxa nao pode virar acumulado), "m3/s", "km/h" e "kg/m2" antes de "m" solto
# (senao a fronteira de palavra sozinha nao bastaria -- "kg/m2" contem "m").
# "m" fica por ultimo porque e a mais generica: qualquer unidade multi-
# caractere desta lista, se presente, tem que vencer a corrida antes que "m"
# solto seja sequer tentado.
_UNIDADES: list[tuple[str, str, str]] = [
    (r"mm/h", "mm/h", "taxa_precipitacao"),
    (r"mm", "mm", "chuva_acumulada"),
    (r"km/h", "km/h", "vento"),
    (r"m3/s", "m3/s", "vazao"),
    (r"kg/m2", "kg/m2", "vil"),
    (r"dbz", "dBZ", "refletividade"),
    (r"(?:°|º)\s*c\b|graus\s+celsius|celsius", "celsius", "temperatura_topo"),
    (r"(?<![a-zA-Z])m(?![a-zA-Z])", "m", "cota"),
]


def _limpar_celula(celula: str) -> str:
    texto = re.sub(r"<br\s*/?>", " ", celula, flags=re.IGNORECASE)
    texto = texto.replace("**", "").replace("*", "")
    return " ".join(texto.split())


def _e_linha_separadora(linha: str) -> bool:
    interior = linha.strip()
    if "|" not in interior:
        return False
    interior = interior.strip("|")
    celulas = [c.strip() for c in interior.split("|")]
    return bool(celulas) and all(re.fullmatch(r":?-+:?", c) for c in celulas)


def _celulas(linha: str) -> list[str]:
    interior = linha.strip()
    if interior.startswith("|"):
        interior = interior[1:]
    if interior.endswith("|"):
        interior = interior[:-1]
    return [_limpar_celula(c) for c in interior.split("|")]


def _tabelas(texto: str) -> list[tuple[list[str], list[tuple[str, list[str]]]]]:
    """Localiza tabelas markdown no texto do chunk.

    Devolve, por tabela: (cabecalho, [(linha_bruta, celulas), ...]) -- a
    linha bruta e preservada porque fonte_trecho precisa ser a linha verbatim,
    nao uma reconstrucao a partir das celulas limpas.
    """
    linhas = texto.splitlines()
    tabelas: list[tuple[list[str], list[tuple[str, list[str]]]]] = []
    i = 0
    n = len(linhas)
    while i < n:
        linha = linhas[i]
        if "|" in linha and i + 1 < n and _e_linha_separadora(linhas[i + 1]):
            cabecalho = _celulas(linha)
            i += 2
            linhas_dados: list[tuple[str, list[str]]] = []
            while i < n and "|" in linhas[i]:
                linhas_dados.append((linhas[i], _celulas(linhas[i])))
                i += 1
            tabelas.append((cabecalho, linhas_dados))
        else:
            i += 1
    return tabelas


_MAIOR_CHAVE_DE_ROTULO = max(len(chave.split()) for chave in _ROTULOS)


def _rotulos_na_celula(celula: str) -> set[tuple[str, str]]:
    # Tokenizacao gulosa por casamento mais longo primeiro: "muito forte"
    # tem que vencer antes que "forte" sozinho seja tentado, senao toda
    # celula "Muito Forte" pareceria casar com dois rotulos diferentes
    # (muito_forte E forte) so porque "forte" e uma palavra dentro dela.
    # Uma vez consumidos, os tokens de uma chave nao sao reconsiderados.
    tokens = normalizar(celula).split()
    n = len(tokens)
    encontrados: set[tuple[str, str]] = set()
    i = 0
    while i < n:
        casou = False
        for tamanho in range(min(_MAIOR_CHAVE_DE_ROTULO, n - i), 0, -1):
            candidato = " ".join(tokens[i : i + tamanho])
            resultado = _ROTULOS.get(candidato)
            if resultado is not None:
                encontrados.add(resultado)
                i += tamanho
                casou = True
                break
        if not casou:
            i += 1
    return encontrados


def _achar_rotulo(celulas: list[str]) -> tuple[list[int], str, str] | None:
    candidatos: list[tuple[int, str, str]] = []
    for indice, celula in enumerate(celulas):
        resultados = _rotulos_na_celula(celula)
        if len(resultados) > 1:
            # Uma unica celula que casa com mais de uma escala/nivel e
            # ambigua por construcao -- a linha inteira vira nao reconhecida
            # em vez de adivinhar qual escala vale (ver "quando estar em
            # duvida" no brief).
            return None
        if len(resultados) == 1:
            escala, nivel = next(iter(resultados))
            candidatos.append((indice, escala, nivel))

    distintos = {(escala, nivel) for _, escala, nivel in candidatos}
    if len(distintos) != 1:
        # Zero celulas com rotulo conhecido: linha nao e de limiar. Mais de
        # um rotulo distinto entre celulas da mesma linha: ambiguo sobre qual
        # e o rotulo -- mesma regra de prudencia acima.
        return None

    escala, nivel = next(iter(distintos))
    indices = [indice for indice, *_ in candidatos]
    return indices, escala, nivel


def _unidade_em(texto: str) -> tuple[str, str, str] | None:
    for padrao, unidade, grandeza in _UNIDADES:
        if re.search(padrao, texto, re.IGNORECASE):
            return padrao, unidade, grandeza
    return None


def _num(bruto: str) -> float:
    return float(bruto.replace(",", "."))


def _casar_intervalo(texto: str, padrao_unidade: str) -> tuple[float, float] | None:
    padrao_entre = rf"entre\s*({_NUM})\s*(?:{padrao_unidade})?\s*e\s*({_NUM})\s*(?:{padrao_unidade})"
    padrao_a = rf"({_NUM})\s*(?:{padrao_unidade})?\s*(?:a|at[ée]|-)\s*({_NUM})\s*(?:{padrao_unidade})"
    m = re.search(padrao_entre, texto, re.IGNORECASE) or re.search(padrao_a, texto, re.IGNORECASE)
    if not m:
        return None
    return _num(m.group(1)), _num(m.group(2))


def _casar_maximo(texto: str, padrao_unidade: str) -> float | None:
    padrao = rf"(?:<=|≤|at[ée]|no\s+m[áa]ximo|abaixo\s+de)\s*({_NUM})\s*(?:{padrao_unidade})"
    m = re.search(padrao, texto, re.IGNORECASE)
    return _num(m.group(1)) if m else None


def _casar_minimo(texto: str, padrao_unidade: str) -> float | None:
    padrao_prefixo = rf"(?:>=|≥|>|acima\s+de|superior\s+a)\s*({_NUM})\s*(?:{padrao_unidade})"
    m = re.search(padrao_prefixo, texto, re.IGNORECASE)
    if m:
        return _num(m.group(1))
    padrao_sufixo = rf"({_NUM})\s*(?:{padrao_unidade})\s*ou\s*mais"
    m = re.search(padrao_sufixo, texto, re.IGNORECASE)
    return _num(m.group(1)) if m else None


def _casar_solto(texto: str, padrao_unidade: str) -> float | None:
    m = re.search(rf"({_NUM})\s*(?:{padrao_unidade})", texto, re.IGNORECASE)
    return _num(m.group(1)) if m else None


def _analisar_valor(celula: str) -> dict | None:
    achado = _unidade_em(celula)
    if achado is None:
        return None
    padrao_unidade, unidade, grandeza = achado

    intervalo = _casar_intervalo(celula, padrao_unidade)
    if intervalo is not None:
        valor_min, valor_max = intervalo
        return {"valor_min": valor_min, "valor_max": valor_max, "unidade": unidade, "grandeza": grandeza}

    maximo = _casar_maximo(celula, padrao_unidade)
    if maximo is not None:
        return {"valor_min": None, "valor_max": maximo, "unidade": unidade, "grandeza": grandeza}

    minimo = _casar_minimo(celula, padrao_unidade)
    if minimo is not None:
        return {"valor_min": minimo, "valor_max": None, "unidade": unidade, "grandeza": grandeza}

    solto = _casar_solto(celula, padrao_unidade)
    if solto is not None:
        return {"valor_min": solto, "valor_max": None, "unidade": unidade, "grandeza": grandeza}

    return None


def _janela_horas(grandeza: str, celula_valor: str, texto_cabecalho: str) -> int | None:
    # Uma taxa em mm/h ja codifica o tempo na propria unidade -- janela_horas
    # fica nulo sempre para taxa_precipitacao, por construcao (task-19-brief).
    if grandeza == "taxa_precipitacao":
        return None
    for fonte in (celula_valor, texto_cabecalho):
        m = re.search(r"\b(\d+)\s*horas?\b", fonte, re.IGNORECASE) or re.search(r"\b(\d+)h\b", fonte, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def extrair_de_tabelas(chunk: Chunk) -> tuple[list[Regra], int]:
    regras: list[Regra] = []
    ignoradas = 0

    for cabecalho, linhas_dados in _tabelas(chunk.texto):
        texto_cabecalho = " ".join(cabecalho)
        for linha_bruta, celulas in linhas_dados:
            if len(celulas) != len(cabecalho):
                # Markdown malformado (numero de celulas nao bate com o
                # cabecalho): a linha nao pode ser mapeada com confianca,
                # entao conta como ignorada em vez de arriscar alinhamento
                # errado entre rotulo e valor.
                ignoradas += 1
                continue

            rotulo = _achar_rotulo(celulas)
            if rotulo is None:
                ignoradas += 1
                continue
            indices_rotulo, escala, nivel = rotulo

            valor = None
            celula_valor = None
            for indice, celula in enumerate(celulas):
                if indice in indices_rotulo:
                    continue
                resultado = _analisar_valor(celula)
                if resultado is not None:
                    valor = resultado
                    celula_valor = celula
                    break

            if valor is None:
                ignoradas += 1
                continue

            janela_horas = _janela_horas(valor["grandeza"], celula_valor, texto_cabecalho)

            try:
                extraida = RegraExtraida(
                    dominio=_GRANDEZA_PARA_DOMINIO[valor["grandeza"]],
                    entidade_tipo=_ENTIDADE_TIPO,
                    entidade_nome=_ENTIDADE_NOME,
                    grandeza=valor["grandeza"],
                    janela_horas=janela_horas,
                    unidade=valor["unidade"],
                    escala=escala,
                    nivel=nivel,
                    valor_min=valor["valor_min"],
                    valor_max=valor["valor_max"],
                    fonte_trecho=linha_bruta.strip()[:100],
                )
            except ValidationError:
                # Ex.: linha bruta mais curta que o minimo de fonte_trecho.
                # Prefere contar como nao reconhecida a propagar excecao --
                # este modulo nao deve nunca derrubar o chamador.
                ignoradas += 1
                continue

            # Mesmo caminho unico de validacao que o modelo usa (task-19-brief,
            # "as tres defesas, em ordem"): uma origem nao pode escapar das
            # defesas so por ser lida de tabela.
            status, motivo = classificar(extraida, chunk.texto)

            regras.append(
                Regra(
                    **extraida.model_dump(),
                    regra_id=regra_id(
                        chunk.chunk_id,
                        extraida.entidade_tipo,
                        extraida.entidade_nome,
                        extraida.grandeza,
                        extraida.escala,
                        extraida.nivel,
                        extraida.valor_min,
                        extraida.valor_max,
                    ),
                    chunk_id=chunk.chunk_id,
                    fonte_doc=chunk.doc,
                    fonte_pagina=chunk.pagina,
                    fonte_secao=chunk.secao,
                    origem="tabela",
                    status=status,
                    motivo_suspeita=motivo,
                )
            )

    return regras, ignoradas
