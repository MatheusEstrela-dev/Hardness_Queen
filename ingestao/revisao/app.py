from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from ingestao.contrato import Decisao, Veredito
from ingestao.persistencia import anexar_jsonl, escrever_jsonl, ler_jsonl
from ingestao.revisao.agrupamento import CAMPOS_FONTE, agrupar_por_limiar

PAGINA = Path(__file__).parent / "index.html"

# Campos que cada fonte carrega dentro de um grupo em regras_aprovadas.jsonl:
# os mesmos da fila (CAMPOS_FONTE) mais o que so existe depois de decidido --
# quem revisou, quando, e o par original quando a decisao foi "corrigido"
# (None quando nao foi, para manter o esquema uniforme entre fontes).
CAMPOS_FONTE_APROVADA = CAMPOS_FONTE + (
    "revisado_por",
    "revisado_em",
    "valor_min_original",
    "valor_max_original",
)


class PedidoDeDecisao(BaseModel):
    # regra_ids substitui o antigo regra_id singular: uma decisao agora se
    # aplica a um grupo inteiro (todas as regras que afirmam o mesmo
    # limiar), nao a uma regra isolada. O validador "before" abaixo aceita
    # o payload antigo {"regra_id": "..."} e o converte para uma lista de
    # um elemento, entao clientes que ainda mandam regra_id continuam
    # funcionando sem alteracao.
    regra_ids: list[str] = Field(min_length=1)
    veredito: Veredito
    valor_min_corrigido: float | None = None
    valor_max_corrigido: float | None = None
    revisor: str

    @model_validator(mode="before")
    @classmethod
    def _aceita_regra_id_singular(cls, dados):
        if isinstance(dados, dict) and "regra_id" in dados and "regra_ids" not in dados:
            dados = dict(dados)
            dados["regra_ids"] = [dados.pop("regra_id")]
        return dados

    @model_validator(mode="after")
    def _corrigido_exige_extremo(self) -> "PedidoDeDecisao":
        # Sem isso, veredito="corrigido" com os dois extremos nulos passa
        # despercebido por _regenerar_aprovadas e aprova o numero original do
        # modelo como se tivesse sido conferido -- exatamente o que a fila de
        # revisao existe para impedir.
        if (
            self.veredito == "corrigido"
            and self.valor_min_corrigido is None
            and self.valor_max_corrigido is None
        ):
            raise ValueError(
                "veredito 'corrigido' exige valor_min_corrigido ou valor_max_corrigido"
            )
        return self

    @model_validator(mode="after")
    def _revisor_nao_pode_ser_vazio(self) -> "PedidoDeDecisao":
        # A trilha de auditoria depende de um nome em toda decisao. Sem este
        # guard o servidor aceitaria "" (o cliente ja manda um nome vazio se
        # o prompt for cancelado, antes do fix em index.html).
        if not self.revisor.strip():
            raise ValueError("revisor nao pode ser vazio")
        return self


def criar_app(propostas: Path, decisoes: Path, aprovadas: Path) -> FastAPI:
    app = FastAPI(title="Revisao de limiares")

    def _decididos() -> set[str]:
        return {registro["regra_id"] for registro in ler_jsonl(decisoes)}

    def _regenerar_aprovadas() -> None:
        # decisoes.jsonl e append-only (trilha de auditoria: nunca perde uma
        # decisao, mesmo trocada). aprovadas.jsonl e o estado final derivado
        # -- so a ULTIMA decisao por regra_id conta, senao aprovar-depois-
        # rejeitar deixa a regra aprovada (o "continue" do rejeitado nao
        # desfaz a linha ja escrita pela decisao anterior) e duas decisoes
        # para a mesma regra duplicam a linha.
        por_id = {registro["regra_id"]: registro for registro in ler_jsonl(propostas)}
        ultima_decisao_por_regra: dict[str, dict] = {}
        for decisao in ler_jsonl(decisoes):
            ultima_decisao_por_regra[decisao["regra_id"]] = decisao

        aprovadas_individuais = []
        for regra_id, decisao in ultima_decisao_por_regra.items():
            if decisao["veredito"] == "rejeitado":
                continue
            regra = dict(por_id.get(regra_id, {}))
            if not regra:
                continue
            if decisao["veredito"] == "corrigido":
                regra["valor_min_original"] = regra["valor_min"]
                regra["valor_max_original"] = regra["valor_max"]
                regra["valor_min"] = decisao.get("valor_min_corrigido")
                regra["valor_max"] = decisao.get("valor_max_corrigido")
            regra["revisado_por"] = decisao["revisor"]
            regra["revisado_em"] = decisao["decidido_em"]
            aprovadas_individuais.append(regra)

        # Agrupar SOBRE o valor final (ja corrigido quando aplicavel): duas
        # regras aprovadas que convergem para o mesmo limiar depois de
        # corrigidas viram uma linha so, com as citacoes das duas -- e o
        # mesmo raciocinio da fila, so que aplicado ao que foi de fato
        # decidido em vez de ao que foi proposto.
        grupos = agrupar_por_limiar(aprovadas_individuais, campos_fonte=CAMPOS_FONTE_APROVADA)
        escrever_jsonl(aprovadas, grupos)

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return PAGINA.read_text(encoding="utf-8")

    @app.get("/api/pendentes")
    def pendentes() -> dict:
        decididos = _decididos()
        fila = [
            regra
            for regra in ler_jsonl(propostas)
            if regra["regra_id"] not in decididos
        ]
        # Agrupadas por limiar: tres regras que afirmam o mesmo limiar em
        # tres documentos viram UM item de fila com tres fontes, nao tres
        # itens que o revisor decidiria em separado sobre o mesmo numero.
        grupos = agrupar_por_limiar(fila)
        return {"pendentes": grupos, "total": len(grupos)}

    @app.post("/api/decisao")
    def decidir(pedido: PedidoDeDecisao) -> dict:
        disponiveis = {regra["regra_id"] for regra in ler_jsonl(propostas)}
        faltantes = [regra_id for regra_id in pedido.regra_ids if regra_id not in disponiveis]
        if faltantes:
            # Checagem precisa cobrir TODO o grupo antes de qualquer escrita
            # -- um regra_id desconhecido em qualquer posicao do grupo tem
            # que recusar a requisicao inteira. Aplicacao parcial (decidir
            # as regras validas e ignorar a invalida em silencio) seria pior
            # que a recusa: deixaria a trilha de auditoria incompleta para
            # metade de um grupo sem nenhum sinal de erro.
            raise HTTPException(
                status_code=404,
                detail=f"regra_id nao encontrado nas propostas: {faltantes}",
            )

        agora = datetime.now(timezone.utc).isoformat()
        for regra_id in pedido.regra_ids:
            decisao = Decisao(
                regra_id=regra_id,
                veredito=pedido.veredito,
                valor_min_corrigido=pedido.valor_min_corrigido,
                valor_max_corrigido=pedido.valor_max_corrigido,
                revisor=pedido.revisor,
                decidido_em=agora,
            )
            anexar_jsonl(decisoes, decisao.model_dump())
        _regenerar_aprovadas()
        return {"ok": True, "regra_ids": pedido.regra_ids}

    return app
