from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ingestao.contrato import Decisao, Veredito
from ingestao.persistencia import anexar_jsonl, escrever_jsonl, ler_jsonl

PAGINA = Path(__file__).parent / "index.html"


class PedidoDeDecisao(BaseModel):
    regra_id: str
    veredito: Veredito
    valor_corrigido: float | None = None
    revisor: str


def criar_app(propostas: Path, decisoes: Path, aprovadas: Path) -> FastAPI:
    app = FastAPI(title="Revisao de limiares")

    def _decididos() -> set[str]:
        return {registro["regra_id"] for registro in ler_jsonl(decisoes)}

    def _regenerar_aprovadas() -> None:
        por_id = {registro["regra_id"]: registro for registro in ler_jsonl(propostas)}
        saida = []
        for decisao in ler_jsonl(decisoes):
            if decisao["veredito"] == "rejeitado":
                continue
            regra = dict(por_id.get(decisao["regra_id"], {}))
            if not regra:
                continue
            if decisao["veredito"] == "corrigido" and decisao.get("valor_corrigido") is not None:
                regra["valor_original"] = regra["valor"]
                regra["valor"] = decisao["valor_corrigido"]
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
            valor_corrigido=pedido.valor_corrigido,
            revisor=pedido.revisor,
            decidido_em=datetime.now(timezone.utc).isoformat(),
        )
        anexar_jsonl(decisoes, decisao.model_dump())
        _regenerar_aprovadas()
        return {"ok": True, "regra_id": pedido.regra_id}

    return app
