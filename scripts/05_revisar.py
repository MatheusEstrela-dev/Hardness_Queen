import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from ingestao.revisao.app import criar_app

PROPOSTAS = Path("data/regras_propostas.jsonl")
DECISOES = Path("data/decisoes.jsonl")
APROVADAS = Path("data/regras_aprovadas.jsonl")


def main() -> int:
    if not PROPOSTAS.exists():
        print(f"'{PROPOSTAS}' nao existe. Rode a etapa 04 primeiro.")
        return 1

    print("Revisao em http://127.0.0.1:8100 (Ctrl+C para encerrar)")
    uvicorn.run(criar_app(PROPOSTAS, DECISOES, APROVADAS), host="127.0.0.1", port=8100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
