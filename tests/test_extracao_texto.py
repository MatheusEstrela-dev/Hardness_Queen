import importlib.util
import json
from pathlib import Path

import pymupdf
import pytest
from docx import Document

from ingestao.extracao_texto import extrair, extrair_docx, extrair_pdf, titulo_da_secao

_SCRIPT_CLI = Path(__file__).resolve().parents[1] / "scripts" / "03_extrair_texto.py"


def _carregar_cli():
    especificacao = importlib.util.spec_from_file_location("cli_extrair_texto", _SCRIPT_CLI)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def _pdf_com_texto(caminho: Path) -> Path:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 100), "4.2 Caracterizacao do solo gnaisse", fontsize=16)
    pagina.insert_text((72, 140), "A saturacao ocorre a partir de 100mm em 72h.", fontsize=11)
    documento.save(caminho)
    documento.close()
    return caminho


def _pdf_sem_camada_texto(caminho: Path) -> Path:
    documento = pymupdf.open()
    documento.new_page()
    documento.save(caminho)
    documento.close()
    return caminho


def _docx_com_secao(caminho: Path) -> Path:
    documento = Document()
    documento.add_heading("1 Limiares hidrologicos", level=1)
    documento.add_paragraph("A cota de transbordamento do Rio Arrudas e 3.8m.")
    documento.save(caminho)
    return caminho


def test_pdf_produz_chunk_com_numero_de_pagina(tmp_path: Path):
    chunks, estado = extrair_pdf(_pdf_com_texto(tmp_path / "laudo.pdf"))

    assert estado == "texto_nativo"
    assert len(chunks) == 1
    assert chunks[0].pagina == 1


def test_pdf_preserva_o_corpo_da_pagina_no_chunk(tmp_path: Path):
    chunks, _ = extrair_pdf(_pdf_com_texto(tmp_path / "laudo.pdf"))

    assert "gnaisse" in chunks[0].texto
    assert "100mm" in chunks[0].texto


def test_pdf_com_tabela_preserva_as_colunas_em_markdown(tmp_path: Path):
    caminho = tmp_path / "tabela.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    html = """
    <table border="1">
      <tr><th>Solo</th><th>Limiar 72h (mm)</th></tr>
      <tr><td>gnaisse</td><td>100</td></tr>
      <tr><td>argiloso</td><td>80</td></tr>
    </table>
    """
    pagina.insert_htmlbox(pymupdf.Rect(50, 50, 500, 300), html)
    documento.save(caminho)
    documento.close()

    chunks, _ = extrair_pdf(caminho)

    texto = chunks[0].texto
    assert "gnaisse" in texto and "argiloso" in texto
    assert "100" in texto and "80" in texto
    # a associacao solo -> valor precisa sobreviver: gnaisse e 100 na mesma linha
    linha_do_gnaisse = next(l for l in texto.splitlines() if "gnaisse" in l)
    assert "100" in linha_do_gnaisse


def _pdf_multipagina_com_secoes(caminho: Path) -> Path:
    documento = pymupdf.open()

    pagina1 = documento.new_page()
    pagina1.insert_text((72, 100), "4.2 Caracterizacao do solo gnaisse", fontsize=16)
    pagina1.insert_text((72, 140), "Corpo da secao 4.2 na pagina 1.", fontsize=11)

    pagina2 = documento.new_page()
    pagina2.insert_text((72, 100), "A saturacao ocorre a partir de 100mm em 72h.", fontsize=11)

    pagina3 = documento.new_page()
    pagina3.insert_text((72, 100), "5.1 Limiares de vazao", fontsize=16)
    pagina3.insert_text((72, 140), "Corpo da secao 5.1 na pagina 3.", fontsize=11)

    documento.save(caminho)
    documento.close()
    return caminho


def test_pdf_propaga_secao_para_pagina_seguinte_sem_cabecalho(tmp_path: Path):
    chunks, _ = extrair_pdf(_pdf_multipagina_com_secoes(tmp_path / "multipagina.pdf"))

    assert len(chunks) == 3
    # pagina 2 nao tem cabecalho proprio: herda a secao da pagina 1
    assert chunks[1].secao == "4.2 Caracterizacao do solo gnaisse"


def test_pdf_novo_cabecalho_substitui_a_secao_herdada(tmp_path: Path):
    chunks, _ = extrair_pdf(_pdf_multipagina_com_secoes(tmp_path / "multipagina.pdf"))

    # pagina 3 tem cabecalho proprio: nao deve vazar a secao da pagina 1
    assert chunks[2].secao == "5.1 Limiares de vazao"


def test_pdf_sem_camada_de_texto_nao_produz_zero_em_silencio(tmp_path: Path):
    chunks, estado = extrair_pdf(_pdf_sem_camada_texto(tmp_path / "digitalizado.pdf"))

    assert estado in {"sem_camada_texto", "ocr_aplicado"}
    if estado == "sem_camada_texto":
        assert chunks == []


def test_docx_produz_pagina_nula_e_secao_preenchida(tmp_path: Path):
    chunks, estado = extrair_docx(_docx_com_secao(tmp_path / "laudo.docx"))

    assert estado == "texto_nativo"
    assert chunks[0].pagina is None
    assert chunks[0].secao == "1 Limiares hidrologicos"


def test_chunk_id_e_preenchido(tmp_path: Path):
    chunks, _ = extrair_pdf(_pdf_com_texto(tmp_path / "laudo.pdf"))

    assert len(chunks[0].chunk_id) == 16


def test_extrair_despacha_por_extensao(tmp_path: Path):
    chunks_pdf, _ = extrair(_pdf_com_texto(tmp_path / "a.pdf"))
    chunks_docx, _ = extrair(_docx_com_secao(tmp_path / "a.docx"))

    assert chunks_pdf and chunks_docx


def test_extrair_rejeita_extensao_desconhecida(tmp_path: Path):
    arquivo = tmp_path / "planilha.xlsx"
    arquivo.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        extrair(arquivo)


def test_titulo_da_secao_pega_o_primeiro_cabecalho():
    assert titulo_da_secao("## 4.2 Solo gnaisse\n\ncorpo") == "4.2 Solo gnaisse"


def test_titulo_da_secao_sem_cabecalho_devolve_nulo():
    assert titulo_da_secao("apenas corpo de texto") is None


def test_cli_documento_invalido_nao_interrompe_o_lote(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pasta_docs = tmp_path / "docs"
    pasta_docs.mkdir()
    (pasta_docs / "a_corrompido.pdf").write_bytes(b"nao sou um pdf valido")
    _pdf_com_texto(pasta_docs / "b_valido.pdf")

    modulo = _carregar_cli()
    resultado = modulo.main()

    saida = capsys.readouterr().out
    assert resultado == 0
    # documento invalido nao interrompe o lote: o proximo documento ainda e processado
    assert "[erro_extracao] a_corrompido.pdf" in saida
    assert "[texto_nativo] b_valido.pdf: 1 chunks" in saida
    assert "erro_extracao: 1" in saida
    assert "texto_nativo: 1" in saida

    registros = {
        registro["doc"]: registro
        for registro in (
            json.loads(linha)
            for linha in (tmp_path / "data" / "manifesto.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    assert registros["a_corrompido.pdf"]["estado"] == "erro_extracao"
    assert registros["b_valido.pdf"]["estado"] == "texto_nativo"
