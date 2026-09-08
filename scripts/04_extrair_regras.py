import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.contrato import Chunk
from ingestao.extrator_regras import criar_gerador_qwen, processar
from ingestao.persistencia import ler_jsonl

PASTA_CHUNKS = Path("data/chunks")
PROPOSTAS = Path("data/regras_propostas.jsonl")
OMISSOES = Path("data/possiveis_omissoes.jsonl")


def main() -> int:
    arquivos = sorted(PASTA_CHUNKS.glob("*.jsonl"))
    if not arquivos:
        print(f"Nenhum chunk em '{PASTA_CHUNKS}/'. Rode a etapa 03 primeiro.")
        return 1

    chunks = [Chunk(**registro) for arquivo in arquivos for registro in ler_jsonl(arquivo)]
    print(f"{len(chunks)} chunks para processar. Carregando o modelo...")

    gerar = criar_gerador_qwen()
    resumo = processar(chunks, gerar, PROPOSTAS, OMISSOES)

    print("\nResumo:")
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    if resumo["omissoes"]:
        print(f"\n{resumo['omissoes']} chunk(s) com padrao de limiar e zero regras em '{OMISSOES}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
