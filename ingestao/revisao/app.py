from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, model_validator

from ingestao.contrato import Decisao, Veredito
from ingestao.persistencia import anexar_jsonl, escrever_jsonl, ler_jsonl

PAGINA = Path(__file__).parent / "index.html"


class PedidoDeDecisao(BaseModel):
    regra_id: str
    veredito: Veredito
    valor_min_corrigido: float | None = None
    valor_max_corrigido: float | None = None
    revisor: str

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

        saida = []
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
            saida.append(regra)
        escrever_jsonl(aprovadas, saida)

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
        return {"pendentes": fila, "total": len(fila)}

    @app.post("/api/decisao")
    def decidir(pedido: PedidoDeDecisao) -> dict:
        existe = any(regra["regra_id"] == pedido.regra_id for regra in ler_jsonl(propostas))
        if not existe:
            raise HTTPException(status_code=404, detail="regra_id nao encontrado nas propostas")

        decisao = Decisao(
            regra_id=pedido.regra_id,
            veredito=pedido.veredito,
            valor_min_corrigido=pedido.valor_min_corrigido,
            valor_max_corrigido=pedido.valor_max_corrigido,
            revisor=pedido.revisor,
            decidido_em=datetime.now(timezone.utc).isoformat(),
        )
        anexar_jsonl(decisoes, decisao.model_dump())
        _regenerar_aprovadas()
        return {"ok": True, "regra_id": pedido.regra_id}

    return app
