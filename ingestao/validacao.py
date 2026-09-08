import re
import unicodedata

from ingestao.contrato import RegraExtraida

FAIXAS_PLAUSIVEIS: dict[tuple[str, str], tuple[float, float]] = {
    ("chuva_acumulada", "mm"): (1.0, 1000.0),
    ("cota", "m"): (0.1, 50.0),
    ("vazao", "m3/s"): (0.1, 100000.0),
}

_PADRAO_DE_LIMIAR = re.compile(r"\d+(?:[.,]\d+)?\s*(?:mm|m3/s|m\b|h\b)", re.IGNORECASE)
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


def valor_plausivel(grandeza: str, unidade: str, valor: float) -> bool:
    faixa = FAIXAS_PLAUSIVEIS.get((grandeza, unidade))
    if faixa is None:
        return False
    minimo, maximo = faixa
    return minimo <= valor <= maximo


def classificar(regra: RegraExtraida, texto_chunk: str) -> tuple[str, str | None]:
    if not trecho_confere(regra.fonte_trecho, texto_chunk):
        return "suspeito", "trecho citado nao encontrado no chunk de origem"
    if not valor_plausivel(regra.grandeza, regra.unidade, regra.valor):
        return "suspeito", f"valor {regra.valor} fora da faixa para {regra.grandeza} em {regra.unidade}"
    return "ok", None


def suspeito_de_omissao(texto_chunk: str, total_de_regras: int) -> bool:
    if total_de_regras > 0:
        return False
    return bool(_PADRAO_DE_LIMIAR.search(texto_chunk))
