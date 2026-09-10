import json
import re

import pytest

from ingestao import dataset as gerador


def regra(**campos):
    return {
        "regra_id": "fonte-1", "escala": "alerta_cor",
        "grandeza": "chuva_acumulada", "unidade": "mm",
        "entidade_tipo": "estado", "entidade_nome": "minas gerais",
        "nivel": "roxo", "janela_horas": 24,
        "valor_min": 175.0, "valor_max": None,
        "fonte_doc": "protocolo.docx", "fonte_trecho": "Acima de 175 mm em 24 horas",
        **campos,
    }


def gerar(tmp_path, regras=None):
    origem = tmp_path / "aprovadas.jsonl"
    if regras is not None:
        origem.write_text("".join(json.dumps(r) + "\n" for r in regras), encoding="utf-8")
    saida = tmp_path / "dataset.jsonl"
    gerador.gerar(saida, origem)
    return saida, [json.loads(l) for l in saida.read_text(encoding="utf-8").splitlines()]


def test_amostras_de_24h_nao_subestimam_nivel_do_catalogo(tmp_path):
    _, exemplos = gerar(tmp_path)
    ordem = {"AMARELO": 1, "LARANJA": 2, "VERMELHO": 3, "ROXO": 4}
    avaliados = 0
    for exemplo in exemplos:
        texto = exemplo["prompt"][-1]["content"]
        valor = re.search(r"Acumulado em 24h: ([\d.]+) mm\. Limiar", texto)
        if valor is None:
            continue
        observado = float(valor[1])
        nivel = exemplo["completion"][0]["content"].split()[1]
        esperados = [cor for cor, limiar in [("AMARELO", 60), ("LARANJA", 90),
                                            ("VERMELHO", 120), ("ROXO", 170)]
                     if observado > limiar]
        assert ordem[nivel] == max(ordem[c] for c in esperados), texto
        avaliados += 1
    assert avaliados >= 12


def test_catalogo_aprovado_nao_recebe_limiares_fixos_de_outro_catalogo(tmp_path):
    _, exemplos = gerar(tmp_path, [regra()])
    texto = json.dumps(exemplos)
    assert "175" in texto
    assert "limiar vermelho" not in texto
    assert "limiar amarelo" not in texto
    assert "170 mm" not in texto


def test_regra_municipal_nao_e_aplicada_a_outros_municipios(tmp_path):
    _, exemplos = gerar(tmp_path, [regra(entidade_tipo="municipio", entidade_nome="Diamantina")])
    texto = json.dumps(exemplos)
    assert "Diamantina" in texto
    assert all(nome not in texto for nome, _ in gerador.LOCAIS)


def test_taxa_preserva_unidade_sem_inventar_acumulado_ou_janela(tmp_path):
    _, exemplos = gerar(tmp_path, [regra(grandeza="taxa_precipitacao", unidade="mm/h",
                                       janela_horas=None, valor_min=100)])
    alertas = [e for e in exemplos if "NIVEL ROXO" in e["completion"][0]["content"]]
    assert alertas
    for exemplo in alertas:
        texto = json.dumps(exemplo)
        assert "mm/h" in texto
        assert "Acumulado" not in texto
        assert "24h" not in texto


@pytest.mark.parametrize("campos", [
    {"janela_horas": None}, {"unidade": "mm/h"},
    {"valor_max": 100}, {"valor_min": float("nan")},
    {"entidade_nome": ""}, {"grandeza": "taxa_precipitacao", "unidade": "mm/h"},
])
def test_catalogo_invalido_nao_e_transformado_em_exemplos(tmp_path, campos):
    with pytest.raises(ValueError):
        gerar(tmp_path, [regra(**campos)])


def test_aprovadas_sem_alerta_utilizavel_nao_aciona_fallback(tmp_path):
    with pytest.raises(ValueError):
        gerar(tmp_path, [regra(escala="intensidade", nivel="extremo")])


def test_exemplo_verde_nao_inventa_medicao_de_12mm(tmp_path):
    _, exemplos = gerar(tmp_path, [regra()])
    verdes = [e for e in exemplos if "NIVEL VERDE" in e["completion"][0]["content"]]
    assert verdes
    assert all("12 mm" not in json.dumps(e) for e in verdes)
    assert all("verde" in e["prompt"][-1]["content"].lower() for e in verdes)


def test_proveniencia_acompanha_cada_exemplo_sem_mudar_formato_treino(tmp_path):
    saida, exemplos = gerar(tmp_path, [regra()])
    registros = [json.loads(l) for l in saida.with_suffix(".proveniencia.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert len(registros) == len(exemplos)
    for numero, (exemplo, registro) in enumerate(zip(exemplos, registros), 1):
        assert set(exemplo) == {"prompt", "completion"}
        assert registro["linha"] == numero
        assert registro["tipo"] == "sintetico"
        assert registro["fonte_catalogo"] == "regras_aprovadas"
        assert registro["exemplo_sha256"]
    assert "fonte-1" in json.dumps(registros)


def test_regras_equivalentes_nao_duplicam_exemplos_e_preservam_fontes(tmp_path):
    saida, exemplos = gerar(tmp_path, [regra(), regra(regra_id="fonte-2")])
    assert len(exemplos) == len({json.dumps(e, sort_keys=True) for e in exemplos})
    fontes = saida.with_suffix(".proveniencia.jsonl").read_text(encoding="utf-8")
    assert "fonte-1" in fontes and "fonte-2" in fontes
