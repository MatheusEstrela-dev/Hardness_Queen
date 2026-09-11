"""Inventaria Geo e Plancon, extrai evidencias e parametriza candidatos locais."""

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.extracao_geo import (
    PADRAO_CANDIDATO, auditar_ialc, classes_qgis, dividir_texto, extrair_tabelas_alerta,
    ler_documento, ler_planilhas, normalizar, registro_ialc,
)
from ingestao.identidade import chunk_id
from ingestao.persistencia import escrever_jsonl, hash_arquivo


def gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def parametrizacao(cabecalhos: dict) -> dict:
    return {
        "versao": 1, "etapa": "extracao", "status": "pendente_homologacao",
        "uso_operacional": False, "granularidade_temporal": "minutos",
        "ialc": {
            "aba": "Limiar de Aproximação", "entidade": "municipio",
            "codigo_ibge_coluna": "D", "chuva_referencia_coluna": "I",
            "unidade": "mm", "janela_minutos": None,
            "percentuais_cabecalho": {
                c: float(match.group(1).replace(",", "."))
                for c in "KLMNO"
                if (match := re.search(r"(\d+(?:[.,]\d+)?)\s*%", cabecalhos.get(c, "")))
            },
            "aplicar_percentuais": False, "formula": None,
            "observacao": "Percentuais sao rotulos da fonte, nao formulas homologadas",
        },
        "plancon": {"preservar_evento": True, "preservar_escala_fonte": True,
                    "operador_limiar": None, "mapa_cores": None,
                    "precedencia_sobre_ialc": None},
        "qgis": {"natureza": "simbologia_cartografica", "preservar_valor_e_legenda": True},
        "revisao": {"exige_fonte": True, "exige_revisor": True,
                    "exige_data_homologacao": True, "conversao_para_regra_meteorologia": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geo", type=Path, required=True)
    parser.add_argument("--plancon", type=Path, required=True)
    parser.add_argument("--saida", type=Path, default=Path("data/curadoria/geo"))
    args = parser.parse_args()
    for raiz in (args.geo, args.plancon):
        if not raiz.is_dir():
            parser.error(f"Acervo inexistente: {raiz}")
    saida = args.saida.resolve()
    for raiz in (args.geo.resolve(), args.plancon.resolve()):
        if saida == raiz or raiz in saida.parents:
            parser.error("A saida deve ficar fora dos acervos de origem.")

    ialc = args.geo / "IALCxlsx 1.xlsx"
    abas = ler_planilhas(ialc)
    gravar_json(saida / "auditoria_ialc.json", auditar_ialc(abas))
    linhas = abas["Limiar de Aproximação"]
    cabecalhos = linhas[0]["valores"]
    parametros = []
    fonte_ialc = {"fonte_doc": str(ialc.resolve()), "fonte_hash": hash_arquivo(ialc)}
    gravar_json(saida / "parametrizacao.json", parametrizacao(cabecalhos))
    indice_path = args.plancon / "_INDICE.csv"
    indice_plancon = {}
    registros_indice = []
    if indice_path.exists():
        bruto = indice_path.read_bytes()
        try:
            texto_indice = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto_indice = bruto.decode("cp1252")
        registros_indice = list(csv.DictReader(io.StringIO(texto_indice), delimiter=";"))
        hash_indice = hash_arquivo(indice_path)
        escrever_jsonl(saida / "indice_plancon.jsonl", [
            {**r, "fonte_doc": str(indice_path.resolve()), "fonte_hash": hash_indice}
            for r in registros_indice
        ])
        for r in registros_indice:
            if r.get("arquivo_nesta_pasta"):
                indice_plancon.setdefault(r["arquivo_nesta_pasta"], []).append(r)
    registros_abas = []
    for aba, registros in abas.items():
        for registro in registros:
            registros_abas.append({**fonte_ialc, "fonte_aba": aba, **registro})
    escrever_jsonl(saida / "ialc_celulas.jsonl", registros_abas)
    for linha in linhas[1:]:
        if not linha["valores"].get("A"):
            continue
        registro = registro_ialc(linha["linha"], linha["valores"], cabecalhos)
        registro.update(fonte_ialc)
        registro["formulas_fonte"] = linha["formulas"]
        registro["parametro_id"] = chunk_id(str(ialc.resolve()), None, json.dumps(linha, sort_keys=True))
        parametros.append(registro)
    escrever_jsonl(saida / "ialc_municipios.jsonl", parametros)

    inventario, manifesto, candidatos, regras, classes, cruzamento = [], [], [], [], [], []
    for acervo, raiz in (("geo", args.geo), ("plancon", args.plancon)):
        arquivos = sorted(p for p in raiz.rglob("*") if p.is_file())
        for caminho in arquivos:
            relativo = caminho.relative_to(raiz).as_posix()
            origem = {"acervo": acervo, "fonte_doc": str(caminho.resolve()), "caminho_relativo": relativo}
            item = {**origem, "formato": caminho.suffix.lower(), "bytes": caminho.stat().st_size}
            inventario.append(item)
            if caminho.name.startswith(("._", "~$")) or "__MACOSX" in caminho.parts:
                item["estado"] = "metadado_auxiliar"
                continue
            if caminho.suffix.lower() not in {".pdf", ".docx", ".qgz"}:
                item["estado"] = "inventariado_sem_leitura_conteudo"
                continue
            origem["fonte_hash"] = hash_arquivo(caminho)
            try:
                if caminho.suffix.lower() == ".qgz":
                    extraidas = [{**origem, **c} for c in classes_qgis(caminho)]
                    classes.extend(extraidas)
                    item["estado"] = "simbologia_catalogada"
                    continue
                id_doc = f"{acervo}/{relativo}"
                arquivo_chunks = saida / "chunks" / f"{chunk_id(id_doc, None, '')}.jsonl"
                registros, paginas_sem_texto = [], []
                paginas = 0
                for pagina, secao, texto in ler_documento(caminho):
                    paginas += 1
                    if len(texto.strip()) < 10:
                        paginas_sem_texto.append(pagina)
                        continue
                    for regra in extrair_tabelas_alerta(texto):
                        regras.append({**origem, **regra, "fonte_pagina": pagina,
                                       "documento_contexto": caminho.stem,
                                       "candidato_id": chunk_id(id_doc, pagina, json.dumps(regra, sort_keys=True))})
                    for chunk in dividir_texto(id_doc, pagina, secao, texto):
                        registro = chunk.model_dump()
                        registros.append(registro)
                        if PADRAO_CANDIDATO.search(chunk.texto):
                            candidatos.append({**origem, "chunk_id": chunk.chunk_id,
                                               "fonte_pagina": pagina, "fonte_secao": secao,
                                               "arquivo_chunks": str(arquivo_chunks),
                                               "natureza": "trecho_candidato_nao_homologado"})
                escrever_jsonl(arquivo_chunks, registros)
                estado = "sem_camada_texto" if not registros else (
                    "texto_parcial" if paginas_sem_texto else "texto_nativo")
                item["estado"] = estado
                manifesto.append({**origem, "estado": estado, "paginas_ou_secoes": paginas,
                                  "paginas_sem_texto": paginas_sem_texto, "chunks": len(registros),
                                  "arquivo_chunks": str(arquivo_chunks), "metodo_pdf": "texto_nativo_ordenado_sem_ocr"})
                if acervo == "plancon":
                    entradas_indice = indice_plancon.get(caminho.name, [])
                    entrada = entradas_indice[0] if len(entradas_indice) == 1 else {}
                    nome = normalizar(entrada.get("municipio") or caminho.stem.rsplit("_", 1)[0].replace("_", " "))
                    municipios = [p for p in parametros if normalizar(p["entidade_nome"]) == nome]
                    cruzamento.append({**origem, "municipios_candidatos": [p["codigo_ibge_fonte"] for p in municipios],
                                       "vinculo": "nome_indice_nao_homologado" if entrada else "nome_arquivo_nao_homologado",
                                       "codigo_cedec_fonte": entrada.get("cod_cedec"),
                                       "data_plano_indice": entrada.get("data_do_plano"),
                                       "estado_extracao": estado})
            except Exception as erro:
                item["estado"] = "erro_extracao"
                manifesto.append({**origem, "estado": "erro_extracao", "erro": str(erro)})
            if len(manifesto) % 100 == 0:
                print(f"Documentos examinados: {len(manifesto)}", flush=True)

    for nome, registros in (("inventario", inventario), ("manifesto", manifesto),
                            ("trechos_candidatos", candidatos), ("limiares_plancon", regras),
                            ("classes_qgis", classes), ("vinculos_plancon_ialc", cruzamento)):
        escrever_jsonl(saida / f"{nome}.jsonl", registros)
    resumo = {
        "fontes": {"geo": str(args.geo.resolve()), "plancon": str(args.plancon.resolve())},
        "arquivos_por_acervo": dict(Counter(i["acervo"] for i in inventario)),
        "estados_documentos": dict(Counter(i["estado"] for i in manifesto)),
        "estados_por_acervo": {
            acervo: dict(Counter(i["estado"] for i in manifesto if i["acervo"] == acervo))
            for acervo in ("geo", "plancon")
        },
        "total_chunks": sum(i.get("chunks", 0) for i in manifesto),
        "municipios_ialc": len(parametros),
        "municipios_com_faixas_preenchidas": sum(bool(p["faixas_preenchidas"]) for p in parametros),
        "entradas_indice_plancon": len(registros_indice),
        "entradas_indice_com_observacao": sum(bool(r.get("observacao")) for r in registros_indice),
        "trechos_candidatos": len(candidatos), "limiares_plancon_candidatos": len(regras),
        "classes_qgis": len(classes),
        "classes_qgis_raster": sum(c["tipo_renderer"] == "raster" for c in classes),
        "uso_operacional": False,
        "limites": ["PDF sem OCR; paginas sem texto ficam registradas para conferencia visual",
                    "KML, SHP, DBF, rasters, DOC legado e demais planilhas apenas inventariados",
                    "Parser de limiares restrito a tabelas de quatro niveis com janela e unidade explicitas",
                    "Classes QGIS sao simbologia, nao limiares de alerta",
                    "Operadores, percentuais IALC, janelas e precedencia aguardam homologacao"],
    }
    gravar_json(saida / "resumo.json", resumo)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
