"""Etapa 06: importa o IALC (limiar de chuva por municipio) como regras propostas.

Deterministico, sem GPU. As regras entram em data/regras_propostas.jsonl ao lado
das extraidas dos documentos e seguem para a mesma fila de revisao humana; a
evidencia de cada linha vai para data/chunks/, onde o reclassificar a procura.

Idempotente: reimportar a mesma versao nao duplica nada. Uma versao nova so
acrescenta os municipios cujo limiar mudou.

Uso:
    python scripts/06_importar_ialc.py "C:/.../IALCxlsx 1.xlsx"
    python scripts/06_importar_ialc.py "C:/.../IALCxlsx 1.xlsx" --municipio Ipatinga
"""

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.ialc import ler_abas, linhas_do_ialc, regra_do_ialc
from ingestao.persistencia import anexar_jsonl, ids_ja_vistos
from ingestao.validacao import normalizar

PROPOSTAS = Path("data/regras_propostas.jsonl")
PASTA_CHUNKS = Path("data/chunks")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("planilha", type=Path)
    parser.add_argument("--municipio", help="importa so este municipio (amostra)")
    parser.add_argument(
        "--versao",
        help="data da versao da planilha (AAAA-MM-DD); padrao: data de modificacao do arquivo",
    )
    args = parser.parse_args(argv)
    if not args.planilha.is_file():
        parser.error(f"planilha inexistente: {args.planilha}")

    # A planilha muda todo dia; sem a data, uma regra aprovada nao diz de
    # qual versao saiu.
    versao = args.versao or date.fromtimestamp(args.planilha.stat().st_mtime).isoformat()
    linhas, cabecalho = linhas_do_ialc(ler_abas(args.planilha))
    if args.municipio:
        linhas = [linha for linha in linhas if normalizar(linha.municipio) == normalizar(args.municipio)]
        if not linhas:
            print(f"Municipio '{args.municipio}' nao encontrado na aba de limiares.")
            return 1

    arquivo_chunks = PASTA_CHUNKS / f"{args.planilha.stem}.jsonl"
    regras_vistas = ids_ja_vistos(PROPOSTAS, "regra_id")
    chunks_vistos = ids_ja_vistos(arquivo_chunks, "chunk_id")
    novas: Counter = Counter()
    repetidas = 0
    for linha in linhas:
        regra, chunk = regra_do_ialc(linha, cabecalho, args.planilha.name, versao)
        if chunk.chunk_id not in chunks_vistos:
            anexar_jsonl(arquivo_chunks, chunk.model_dump())
            chunks_vistos.add(chunk.chunk_id)
        if regra.regra_id in regras_vistas:
            repetidas += 1
            continue
        anexar_jsonl(PROPOSTAS, regra.model_dump())
        regras_vistas.add(regra.regra_id)
        novas[regra.motivo_suspeita or "ok"] += 1

    print(f"IALC versao {versao}: {len(linhas)} municipio(s) lidos, janela {cabecalho.janela_horas:g}h")
    print(f"  {sum(novas.values())} regra(s) nova(s) em {PROPOSTAS}, {repetidas} ja existiam")
    for motivo, quantidade in novas.most_common():
        rotulo = "ok" if motivo == "ok" else f"suspeito: {motivo.split(':')[0].split('(')[0].strip()}"
        print(f"    {quantidade:4}  {rotulo}")
    print("Revise em: just revisar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
