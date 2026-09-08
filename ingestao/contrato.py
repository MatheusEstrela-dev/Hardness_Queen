from typing import Literal

from pydantic import BaseModel

Dominio = Literal["geologia", "hidrologia", "meteorologia"]
EntidadeTipo = Literal["tipo_solo", "bacia", "estacao", "municipio"]
Grandeza = Literal["chuva_acumulada", "cota", "vazao"]
Unidade = Literal["mm", "m", "m3/s"]
Nivel = Literal["atencao", "critico"]
Status = Literal["ok", "suspeito"]
Veredito = Literal["aprovado", "rejeitado", "corrigido"]


class RegraExtraida(BaseModel):
    """Exatamente o que o modelo produz. A procedencia de arquivo nao passa
    pelo modelo: quem anexa e o script, a partir dos metadados do chunk."""

    dominio: Dominio
    entidade_tipo: EntidadeTipo
    entidade_nome: str
    grandeza: Grandeza
    janela_horas: int | None
    unidade: Unidade
    nivel: Nivel
    valor: float
    fonte_trecho: str


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
    status: Status
    motivo_suspeita: str | None = None


class Decisao(BaseModel):
    regra_id: str
    veredito: Veredito
    valor_corrigido: float | None = None
    revisor: str
    decidido_em: str
