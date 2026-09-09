import re
import unicodedata

from ingestao.contrato import RegraExtraida

FAIXAS_PLAUSIVEIS: dict[tuple[str, str], tuple[float, float]] = {
    ("chuva_acumulada", "mm"): (1.0, 1000.0),
    ("cota", "m"): (0.1, 50.0),
    ("vazao", "m3/s"): (0.1, 100000.0),
    ("vento", "km/h"): (10.0, 400.0),
    ("vil", "kg/m2"): (0.1, 100.0),
    ("refletividade", "dBZ"): (5.0, 80.0),
    ("temperatura_topo", "celsius"): (-90.0, 40.0),
    # A propria tabela de intensidade (PROTOCOLO_ALERTAS_METEORO.docx) usa
    # "> 90mm/h" como classe mais severa (Extremo). O maximo fisico plausivel
    # vem de registro historico, nao de intuicao: o recorde mundial de chuva
    # acumulada em 1 hora e de 401,7 mm (Foc-Foc, La Reuniao, 1966, OMM) --
    # 400.0 arredonda isso com folga de "alguns poucos" mm, sem abrir espaco
    # para um valor de ordem de grandeza maior (ex.: erro de OCR ou
    # alucinacao do modelo emitindo milhares de mm/h) passar como plausivel.
    # O minimo de 0.1 mm/h e o piso de chuvisco mensuravel, na mesma ordem de
    # grandeza do minimo ja usado para vil (0.1 kg/m2) e cota (0.1 m).
    ("taxa_precipitacao", "mm/h"): (0.1, 400.0),
}

# Unidades multi-caractere (mm/h, mm, m3/s, km/h, kg/m2, dbz, celsius)
# precisam vir antes de "m\b" e "h\b" na alternancia: "m\b" e "h\b" exigem
# fronteira de palavra logo apos a letra, entao sozinhos nao casam dentro de
# "mm" (m seguido de m, sem fronteira) nem de "km/h" (m seguido de /, que tem
# fronteira, mas so e alcancado se nada antes tiver casado -- por isso a
# ordem "km/h" antes de "m\b" evita depender so da fronteira de palavra).
# "mm/h" precisa vir antes de "mm" pelo mesmo motivo -- "mm" e prefixo literal
# de "mm/h", entao sem essa ordem a alternancia sempre resolveria em "mm" e
# nunca chegaria a testar "mm/h" (o "/h" sobrando nao muda o resultado deste
# regex, que so verifica presenca de limiar para fins de recall, mas deixar
# "mm/h" implicito nesse acidente de prefixo tornaria o reconhecimento fragil
# a qualquer reordenacao futura da alternancia).
_PADRAO_DE_LIMIAR = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:mm/h|mm|m3/s|km/h|kg/m2|dbz|celsius|°c|m\b|h\b|c\b)",
    re.IGNORECASE,
)


def normalizar(texto: str) -> str:
    # O chunk de origem vem do pymupdf4llm como markdown (ex.: "**termo**
    # , resto"), enquanto o modelo cita a prosa limpa (ex.: "termo, resto").
    # As duas formas divergem em pontuacao e espacamento por construcao,
    # mesmo quando a citacao esta correta -- comparar caractere a caractere
    # (ou so trocar a marcacao por espaco) gera falso "suspeito" nesse caso.
    # A sequencia de tokens alfanumericos, porem, e igual nos dois lados.
    # Extrair tokens com regex (em vez de so remover a pontuacao) tambem
    # preserva a fronteira entre palavras que a marcacao separava --
    # "**gnaisse**100mm" produz os tokens "gnaisse" e "100mm" em vez de se
    # fundir em "gnaisse100mm", o que evitaria a fusao criar uma citacao
    # falsa que nao existia no texto original.
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento.lower()))


def trecho_confere(trecho: str, texto_chunk: str) -> bool:
    return normalizar(trecho) in normalizar(texto_chunk)


# Numero solto, com separador decimal opcional em ponto ou virgula --
# documentos brasileiros escrevem os dois indiferentemente ("31,5" e
# "31.5"). Sem sinal: a citacao de um limiar de alerta nao depende de
# reconhecer negativo aqui, e mistura mal com hifen de intervalo ("26-50").
_PADRAO_DE_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")

_TOLERANCIA_NUMERICA = 1e-9


def _numeros_do_trecho(trecho: str) -> list[float]:
    return [float(bruto.replace(",", ".")) for bruto in _PADRAO_DE_NUMERO.findall(trecho)]


def extremos_citados(valor_min: float | None, valor_max: float | None, trecho: str) -> bool:
    numeros = _numeros_do_trecho(trecho)
    for extremo in (valor_min, valor_max):
        if extremo is None:
            continue
        if not any(abs(extremo - numero) < _TOLERANCIA_NUMERICA for numero in numeros):
            return False
    return True


def _motivo_de_extremo_nao_citado(
    valor_min: float | None,
    valor_max: float | None,
    trecho: str,
) -> str:
    numeros = _numeros_do_trecho(trecho)
    for nome, extremo in (("valor_min", valor_min), ("valor_max", valor_max)):
        if extremo is None:
            continue
        if not any(abs(extremo - numero) < _TOLERANCIA_NUMERICA for numero in numeros):
            return f"{nome} {extremo} nao aparece como numero no trecho citado"
    return "extremo nao aparece como numero no trecho citado"


def valor_plausivel(
    grandeza: str,
    unidade: str,
    valor_min: float | None,
    valor_max: float | None,
) -> bool:
    faixa = FAIXAS_PLAUSIVEIS.get((grandeza, unidade))
    if faixa is None:
        return False
    minimo, maximo = faixa
    if valor_min is not None and not (minimo <= valor_min <= maximo):
        return False
    if valor_max is not None and not (minimo <= valor_max <= maximo):
        return False
    if valor_min is not None and valor_max is not None and valor_min > valor_max:
        return False
    return True


def _motivo_de_implausibilidade(
    grandeza: str,
    unidade: str,
    valor_min: float | None,
    valor_max: float | None,
) -> str:
    faixa = FAIXAS_PLAUSIVEIS.get((grandeza, unidade))
    if faixa is None:
        return f"combinacao {grandeza}/{unidade} desconhecida"
    minimo, maximo = faixa
    if valor_min is not None and valor_max is not None and valor_min > valor_max:
        return f"faixa invertida: valor_min {valor_min} maior que valor_max {valor_max}"
    if valor_min is not None and not (minimo <= valor_min <= maximo):
        return f"valor_min {valor_min} fora da faixa para {grandeza} em {unidade}"
    if valor_max is not None and not (minimo <= valor_max <= maximo):
        return f"valor_max {valor_max} fora da faixa para {grandeza} em {unidade}"
    return f"valor fora da faixa para {grandeza} em {unidade}"


def classificar(regra: RegraExtraida, texto_chunk: str) -> tuple[str, str | None]:
    # A ordem das tres checagens importa: cada uma e mais barata e mais
    # fundamental que a seguinte, e a primeira a falhar e a mensagem mais
    # util para o revisor.
    # 1) o trecho citado existe no chunk? Um trecho que o modelo inventou
    #    de saida torna as outras duas checagens sem sentido.
    if not trecho_confere(regra.fonte_trecho, texto_chunk):
        return "suspeito", "trecho citado nao encontrado no chunk de origem"
    # 2) os numeros da faixa aparecem nesse trecho? Um trecho real do chunk
    #    mas que nao contem os proprios numeros da regra nao sustenta a
    #    regra, seja o valor plausivel ou nao -- essa e a fabricacao que
    #    passava despercebida antes desta checagem existir.
    if not extremos_citados(regra.valor_min, regra.valor_max, regra.fonte_trecho):
        motivo = _motivo_de_extremo_nao_citado(regra.valor_min, regra.valor_max, regra.fonte_trecho)
        return "suspeito", motivo
    # 3) o valor e fisicamente sensato para a grandeza e unidade?
    if not valor_plausivel(regra.grandeza, regra.unidade, regra.valor_min, regra.valor_max):
        motivo = _motivo_de_implausibilidade(regra.grandeza, regra.unidade, regra.valor_min, regra.valor_max)
        return "suspeito", motivo
    return "ok", None


def suspeito_de_omissao(texto_chunk: str, total_de_regras: int) -> bool:
    if total_de_regras > 0:
        return False
    return bool(_PADRAO_DE_LIMIAR.search(texto_chunk))
