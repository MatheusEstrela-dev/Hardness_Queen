"""Relatorios de estado da esteira de ingestao e do treino.

Chamado pelo Justfile. Cada subcomando responde uma pergunta operacional:
o que espera processamento, o que foi produzido, e o que ficou suspeito.
"""

import json
import sys
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.contrato import RegraExtraida
from ingestao.validacao import classificar

PASTA_DOCS = Path("docs")
PASTA_CHUNKS = Path("data/chunks")
PROPOSTAS = Path("data/regras_propostas.jsonl")
APROVADAS = Path("data/regras_aprovadas.jsonl")
DECISOES = Path("data/decisoes.jsonl")
OMISSOES = Path("data/possiveis_omissoes.jsonl")
MANIFESTO = Path("data/manifesto.jsonl")
ADAPTADOR = Path("models/lora_treinado")
DATASET = Path("data/dataset_treino.jsonl")

EXTENSOES_SUPORTADAS = {".pdf", ".docx"}


def _ler_jsonl(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def _contar(registros: list[dict], campo: str) -> list[tuple[str, int]]:
    return sorted(Counter(registro[campo] for registro in registros).items())


def docs() -> None:
    arquivos = (
        sorted(a for a in PASTA_DOCS.glob("*") if a.suffix.lower() in EXTENSOES_SUPORTADAS)
        if PASTA_DOCS.exists()
        else []
    )
    print(f"{len(arquivos)} documento(s) em {PASTA_DOCS}/")
    for arquivo in arquivos:
        print(f"  {arquivo.name:50} {arquivo.stat().st_size / 1024:8.1f} KB")
    if not arquivos:
        print(f"  coloque os laudos em {PASTA_DOCS}/ e rode: just extrair-texto")


def chunks() -> None:
    arquivos = sorted(PASTA_CHUNKS.glob("*.jsonl")) if PASTA_CHUNKS.exists() else []
    if not arquivos:
        print("nenhum chunk ainda. rode: just extrair-texto")
        return

    total = 0
    print(f"{len(arquivos)} documento(s) processado(s)")
    for arquivo in arquivos:
        registros = _ler_jsonl(arquivo)
        total += len(registros)
        paginas = len({r["pagina"] for r in registros})
        print(f"  {arquivo.stem:40} {len(registros):4} chunks em {paginas:3} pagina(s)")
    print(f"total: {total} chunks")


def _formatar_faixa(regra: dict) -> str:
    minimo = regra.get("valor_min")
    maximo = regra.get("valor_max")
    unidade = regra.get("unidade", "")
    if minimo is not None and maximo is not None:
        return f"{minimo} - {maximo} {unidade}"
    if minimo is not None:
        return f">= {minimo} {unidade}"
    if maximo is not None:
        return f"<= {maximo} {unidade}"
    return "-"


def regras() -> None:
    propostas = _ler_jsonl(PROPOSTAS)
    if not propostas:
        print("nenhuma regra proposta ainda. rode: just extrair-regras")
        return

    print(f"{len(propostas)} regra(s) propostas")
    for status, quantidade in _contar(propostas, "status"):
        print(f"  status {status:10} {quantidade}")
    for dominio, quantidade in _contar(propostas, "dominio"):
        print(f"  dominio {dominio:14} {quantidade}")
    for nivel, quantidade in _contar(propostas, "nivel"):
        print(f"  nivel {nivel:14} {quantidade}")

    suspeitas = [r for r in propostas if r["status"] == "suspeito"]
    if suspeitas:
        print(f"\nmotivos de suspeita ({len(suspeitas)}):")
        for regra in suspeitas[:10]:
            print(
                f"  {regra['fonte_doc']} p{regra['fonte_pagina']} "
                f"[{_formatar_faixa(regra)}]: {regra['motivo_suspeita']}"
            )
        if len(suspeitas) > 10:
            print(f"  ... e outras {len(suspeitas) - 10}")

    decididos = {d["regra_id"] for d in _ler_jsonl(DECISOES)}
    pendentes = [r for r in propostas if r["regra_id"] not in decididos]
    print(f"\n{len(pendentes)} pendente(s) de revisao, {len(decididos)} ja decidida(s)")
    print(f"{len(_ler_jsonl(APROVADAS))} aprovada(s) em {APROVADAS}")


def _campos_de_regra_extraida(registro: dict) -> dict:
    return {campo: registro[campo] for campo in RegraExtraida.model_fields}


def _carregar_textos_de_chunks() -> dict[str, str]:
    textos: dict[str, str] = {}
    if not PASTA_CHUNKS.exists():
        return textos
    for arquivo in PASTA_CHUNKS.glob("*.jsonl"):
        for registro in _ler_jsonl(arquivo):
            textos[registro["chunk_id"]] = registro["texto"]
    return textos


def reclassificar() -> None:
    """Reaplica classificar() sobre as regras ja propostas, sem chamar o
    modelo -- reverifica trecho_confere, extremos_citados e valor_plausivel
    contra o chunk de origem que ja esta em disco. Util para propagar uma
    mudanca na logica de validacao (ex.: um novo check) sem repetir os ~140s
    por chunk da etapa 04.
    """
    propostas = _ler_jsonl(PROPOSTAS)
    if not propostas:
        print("nenhuma regra proposta ainda. rode: just extrair-regras")
        return

    contagem_antes = dict(_contar(propostas, "status"))
    textos_por_chunk = _carregar_textos_de_chunks()

    nao_verificaveis = 0
    for proposta in propostas:
        texto_chunk = textos_por_chunk.get(proposta["chunk_id"])
        if texto_chunk is None:
            proposta["status"] = "suspeito"
            proposta["motivo_suspeita"] = (
                f"chunk {proposta['chunk_id']} nao encontrado em {PASTA_CHUNKS}/, "
                "regra nao pode ser reverificada"
            )
            nao_verificaveis += 1
            continue

        regra_extraida = RegraExtraida(**_campos_de_regra_extraida(proposta))
        status, motivo = classificar(regra_extraida, texto_chunk)
        proposta["status"] = status
        proposta["motivo_suspeita"] = motivo

    with PROPOSTAS.open("w", encoding="utf-8") as arquivo:
        for proposta in propostas:
            arquivo.write(json.dumps(proposta, ensure_ascii=False) + "\n")

    contagem_depois = dict(_contar(propostas, "status"))

    print(f"{len(propostas)} regra(s) reclassificadas")
    print("antes:")
    for status_nome, quantidade in sorted(contagem_antes.items()):
        print(f"  status {status_nome:10} {quantidade}")
    print("depois:")
    for status_nome, quantidade in sorted(contagem_depois.items()):
        print(f"  status {status_nome:10} {quantidade}")
    if nao_verificaveis:
        print(f"\n{nao_verificaveis} regra(s) sem chunk de origem, marcada(s) suspeito por nao poder reverificar")


def omissoes() -> None:
    itens = _ler_jsonl(OMISSOES)
    print(f"{len(itens)} chunk(s) com padrao de limiar e zero regras extraidas")
    if not itens:
        return
    print("(o extrator pode ter omitido regra nestes trechos)")
    for item in itens[:15]:
        trecho = " ".join(item["texto"].split())[:90]
        print(f"  {item['doc']} p{item['pagina']}: {trecho}")
    if len(itens) > 15:
        print(f"  ... e outros {len(itens) - 15}")


def manifesto() -> None:
    registros = _ler_jsonl(MANIFESTO)
    print(f"{len(registros)} documento(s) no manifesto")
    estados = dict(_contar(registros, "estado"))
    for estado, quantidade in sorted(estados.items()):
        print(f"  {estado:20} {quantidade}")
    if estados.get("sem_camada_texto"):
        print(
            f"\nATENCAO: {estados['sem_camada_texto']} documento(s) sem camada de texto "
            "nao produziram chunk algum."
        )
        print("Isso NAO e ausencia de regras, e falta de OCR. Verifique: just tesseract")


def artefatos() -> None:
    alvos = [
        ("dataset", DATASET),
        ("adaptador", ADAPTADOR),
        ("chunks", PASTA_CHUNKS),
        ("manifesto", MANIFESTO),
        ("propostas", PROPOSTAS),
        ("omissoes", OMISSOES),
        ("decisoes", DECISOES),
        ("aprovadas", APROVADAS),
    ]
    for nome, caminho in alvos:
        marca = "existe " if caminho.exists() else "ausente"
        print(f"  {nome:12} {marca}  {caminho}")


PACOTES_CRITICOS = [
    "torch",
    "transformers",
    "trl",
    "peft",
    "datasets",
    "bitsandbytes",
    "pymupdf",
    "pymupdf4llm",
    "outlines",
    "pydantic",
    "fastapi",
    "python-docx",
]

VERSOES_PREGADAS = {"transformers": "5.16.1", "trl": "1.12.0"}


def versoes() -> None:
    """Versoes do stack. transformers e trl estao pregadas: o treino depende delas."""
    for pacote in PACOTES_CRITICOS:
        try:
            instalada = version(pacote)
        except PackageNotFoundError:
            print(f"  {pacote:16} AUSENTE")
            continue

        esperada = VERSOES_PREGADAS.get(pacote)
        if esperada is None:
            print(f"  {pacote:16} {instalada}")
        elif instalada == esperada:
            print(f"  {pacote:16} {instalada}  (pregada)")
        else:
            print(f"  {pacote:16} {instalada}  DIVERGE da pregada {esperada} - o treino quebra")


COMANDOS = {
    "versoes": versoes,
    "docs": docs,
    "chunks": chunks,
    "regras": regras,
    "reclassificar": reclassificar,
    "omissoes": omissoes,
    "manifesto": manifesto,
    "artefatos": artefatos,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMANDOS:
        print(f"uso: status.py [{'|'.join(COMANDOS)}]")
        return 1
    COMANDOS[argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
