from pathlib import Path

from ingestao.persistencia import (
    anexar_jsonl,
    documento_inalterado,
    escrever_jsonl,
    hash_arquivo,
    ids_ja_vistos,
    ler_jsonl,
    registrar_documento,
)


def test_ler_jsonl_de_arquivo_inexistente_devolve_vazio(tmp_path: Path):
    assert ler_jsonl(tmp_path / "nao_existe.jsonl") == []


def test_anexar_e_ler_preserva_ordem(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"

    anexar_jsonl(caminho, {"i": 1})
    anexar_jsonl(caminho, {"i": 2})

    assert [r["i"] for r in ler_jsonl(caminho)] == [1, 2]


def test_anexar_cria_diretorio_pai(tmp_path: Path):
    caminho = tmp_path / "sub" / "dir" / "saida.jsonl"

    anexar_jsonl(caminho, {"i": 1})

    assert caminho.exists()


def test_acentos_sobrevivem_ao_roundtrip(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"

    anexar_jsonl(caminho, {"texto": "saturacao da encosta em Belo Horizonte, regiao sul"})

    assert "regiao sul" in ler_jsonl(caminho)[0]["texto"]


def test_escrever_jsonl_substitui_conteudo(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"
    escrever_jsonl(caminho, [{"i": 1}, {"i": 2}])

    total = escrever_jsonl(caminho, [{"i": 9}])

    assert total == 1
    assert [r["i"] for r in ler_jsonl(caminho)] == [9]


def test_ids_ja_vistos_coleta_o_campo(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"
    escrever_jsonl(caminho, [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "a"}])

    assert ids_ja_vistos(caminho, "chunk_id") == {"a", "b"}


def test_hash_arquivo_muda_com_o_conteudo(tmp_path: Path):
    um = tmp_path / "um.txt"
    outro = tmp_path / "outro.txt"
    um.write_text("conteudo original", encoding="utf-8")
    outro.write_text("conteudo alterado", encoding="utf-8")

    assert hash_arquivo(um) != hash_arquivo(outro)


def test_documento_inalterado_reconhece_o_mesmo_hash(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "texto_nativo", 10, 10)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is True
    assert documento_inalterado(manifesto, "laudo.pdf", "h2") is False


def test_documento_nao_registrado_nao_esta_inalterado(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"

    assert documento_inalterado(manifesto, "novo.pdf", "h1") is False


def test_documento_com_erro_extracao_nunca_esta_inalterado(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "erro_extracao", 0, 0)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is False


def test_documento_texto_nativo_com_mesmo_hash_esta_inalterado(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "texto_nativo", 10, 10)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is True


def test_documento_ocr_aplicado_com_mesmo_hash_esta_inalterado(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "ocr_aplicado", 10, 10)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is True


def test_documento_sem_camada_texto_com_mesmo_hash_esta_inalterado(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "sem_camada_texto", 10, 0)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is True


def test_falha_depois_sucesso_a_entrada_mais_recente_prevalece(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "erro_extracao", 0, 0)
    registrar_documento(manifesto, "laudo.pdf", "h1", "texto_nativo", 10, 10)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is True


def test_sucesso_depois_falha_a_entrada_mais_recente_prevalece(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "texto_nativo", 10, 10)
    registrar_documento(manifesto, "laudo.pdf", "h1", "erro_extracao", 0, 0)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is False
