"""Onde cada etapa le e grava -- um lugar so, por area.

A esteira roda por AREA de origem: cada equipe (Meteorologia, Geologia,
Hidrologia) tem seus documentos em docs/<Area>/ e o espaco de trabalho da
esteira em data/<Area>/. A area vem da variavel HARDNESS_AREA, que o Justfile
exporta (just area=Geologia ...); sem ela, Meteorologia.

Area e de onde o documento veio, nao o dominio de cada regra. A Nota Tecnica
da Meteorologia gera regras dos tres dominios, e o PlanCon de Ipatinga de
geologia e de hidrologia: um documento tem uma area so, e cada regra continua
dizendo o proprio dominio no campo `dominio`.

Antes deste modulo, o mesmo "data/regras_propostas.jsonl" estava escrito em
quatro scripts. Um caminho duplicado e um caminho que um dia diverge.
"""

import os
from dataclasses import dataclass
from pathlib import Path

AREAS = ("Meteorologia", "Geologia", "Hidrologia")
AREA_PADRAO = "Meteorologia"
VARIAVEL = "HARDNESS_AREA"


@dataclass(frozen=True)
class Caminhos:
    area: str

    @property
    def raiz(self) -> Path:
        return Path("data") / self.area

    @property
    def docs(self) -> Path:
        return Path("docs") / self.area

    @property
    def chunks(self) -> Path:
        return self.raiz / "chunks"

    @property
    def manifesto(self) -> Path:
        return self.raiz / "manifesto.jsonl"

    @property
    def propostas(self) -> Path:
        return self.raiz / "regras_propostas.jsonl"

    @property
    def aprovadas(self) -> Path:
        return self.raiz / "regras_aprovadas.jsonl"

    @property
    def decisoes(self) -> Path:
        return self.raiz / "decisoes.jsonl"

    @property
    def omissoes(self) -> Path:
        return self.raiz / "possiveis_omissoes.jsonl"

    @property
    def falhas(self) -> Path:
        return self.raiz / "possiveis_falhas.jsonl"

    @property
    def sem_padrao(self) -> Path:
        return self.raiz / "possiveis_sem_padrao.jsonl"

    @property
    def rejeitadas(self) -> Path:
        return self.raiz / "regras_rejeitadas.jsonl"

    @property
    def dataset(self) -> Path:
        return self.raiz / "dataset_treino.jsonl"


def area_atual() -> str:
    area = os.environ.get(VARIAVEL, AREA_PADRAO)
    if area not in AREAS:
        # Falha alto: uma area digitada errado criaria data/<erro>/ em silencio
        # e a esteira rodaria sobre uma pasta vazia, dizendo "nada a fazer".
        raise SystemExit(f"{VARIAVEL}={area!r} desconhecida; use uma de {', '.join(AREAS)}")
    return area


def caminhos(area: str | None = None) -> Caminhos:
    return Caminhos(area or area_atual())
