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
}

# Unidades multi-caractere (mm, m3/s, km/h, kg/m2, dbz, celsius) precisam vir
# antes de "m\b" e "h\b" na alternancia: "m\b" e "h\b" exigem fronteira de
# palavra logo apos a letra, entao sozinhos nao casam dentro de "mm" (m
# seguido de m, sem fronteira) nem de "km/h" (m seguido de /, que tem
# fronteira, mas so e alcancado se nada antes tiver casado -- por isso a
# ordem "km/h" antes de "m\b" evita depender so da fronteira de palavra).
_PADRAO_DE_LIMIAR = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:mm|m3/s|km/h|kg/m2|dbz|celsius|°c|m\b|h\b|c\b)",
    re.IGNORECASE,
)
_MARCACAO_MARKDOWN = re.compile(r"[#*_`|>-]+")
_ESPACOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    sem_markdown = _MARCACAO_MARKDOWN.sub(" ", sem_acento)
    return _ESPACOS.sub(" ", sem_markdown).strip().lower()


def trecho_confere(trecho: str, texto_chunk: str) -> bool:
    return normalizar(trecho) in normalizar(texto_chunk)


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
    if not trecho_confere(regra.fonte_trecho, texto_chunk):
        return "suspeito", "trecho citado nao encontrado no chunk de origem"
    if not valor_plausivel(regra.grandeza, regra.unidade, regra.valor_min, regra.valor_max):
        motivo = _motivo_de_implausibilidade(regra.grandeza, regra.unidade, regra.valor_min, regra.valor_max)
        return "suspeito", motivo
    return "ok", None


def suspeito_de_omissao(texto_chunk: str, total_de_regras: int) -> bool:
    if total_de_regras > 0:
        return False
    return bool(_PADRAO_DE_LIMIAR.search(texto_chunk))
