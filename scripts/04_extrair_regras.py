import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.contrato import Chunk
from ingestao.extrator_regras import criar_gerador_qwen, processar
from ingestao.persistencia import ler_jsonl

PASTA_CHUNKS = Path("data/chunks")
PROPOSTAS = Path("data/regras_propostas.jsonl")
OMISSOES = Path("data/possiveis_omissoes.jsonl")
FALHAS = Path("data/possiveis_falhas.jsonl")
SEM_PADRAO = Path("data/possiveis_sem_padrao.jsonl")


def main() -> int:
    arquivos = sorted(PASTA_CHUNKS.glob("*.jsonl"))
    if not arquivos:
        print(f"Nenhum chunk em '{PASTA_CHUNKS}/'. Rode a etapa 03 primeiro.")
        return 1

    chunks = [Chunk(**registro) for arquivo in arquivos for registro in ler_jsonl(arquivo)]
    print(f"{len(chunks)} chunks para processar. Carregando o modelo...")

    gerar = criar_gerador_qwen()
    resumo = processar(chunks, gerar, PROPOSTAS, OMISSOES, FALHAS, SEM_PADRAO)

    print("\nResumo:")
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    if resumo["omissoes"]:
        print(f"\n{resumo['omissoes']} chunk(s) com padrao de limiar e zero regras em '{OMISSOES}'.")
    if resumo["chunks_sem_padrao"]:
        print(
            f"\n{resumo['chunks_sem_padrao']} chunk(s) sem padrao de limiar foram descartados sem "
            f"passar pelo modelo e registrados em '{SEM_PADRAO}'."
        )
    if resumo["falhas"]:
        print(
            f"\n{resumo['falhas']} chunk(s) falharam durante a extracao e foram registrados em "
            f"'{FALHAS}'. Apague esse arquivo para reprocessa-los na proxima execucao."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
