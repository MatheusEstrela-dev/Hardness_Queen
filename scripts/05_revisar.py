import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.caminhos import caminhos
import uvicorn

from ingestao.revisao.app import criar_app

AREA = caminhos()
PROPOSTAS = AREA.propostas
DECISOES = AREA.decisoes
APROVADAS = AREA.aprovadas


def main() -> int:
    if not PROPOSTAS.exists():
        print(f"'{PROPOSTAS}' nao existe. Rode a etapa 04 primeiro.")
        return 1

    print("Revisao em http://127.0.0.1:8100 (Ctrl+C para encerrar)")
    uvicorn.run(criar_app(PROPOSTAS, DECISOES, APROVADAS), host="127.0.0.1", port=8100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
