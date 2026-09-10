import json

import pytest

from ingestao import dataset as gerador
from ingestao.niveis import ESCALA, POR_COR, mais_grave, nivel_de


def test_escala_tem_os_cinco_niveis_do_protocolo():
    assert [n.cor for n in ESCALA] == ["verde", "amarelo", "laranja", "vermelho", "roxo"]


def test_gravidade_cresce_do_verde_ao_roxo():
    gravidades = [n.gravidade for n in ESCALA]

    assert gravidades == sorted(gravidades)
    assert len(set(gravidades)) == len(gravidades)


def test_todo_nivel_tem_resposta_operacional():
    # A resposta e o que o modelo aprende a escrever: sem ela o alerta diria
    # o nivel sem dizer o que se espera de quem le.
    for nivel in ESCALA:
        assert len(nivel.resposta) > 40, f"{nivel.cor} sem resposta operacional"


def test_mais_grave_escolhe_o_maior():
    # Dois limiares ultrapassados ao mesmo tempo: vale o mais grave. Reportar o
    # menos grave subestimaria a situacao.
    assert mais_grave(["amarelo", "vermelho"]).cor == "vermelho"
    assert mais_grave(["roxo", "verde"]).cor == "roxo"
    assert mais_grave(["laranja"]).cor == "laranja"


def test_nivel_de_cor_desconhecida_falha_alto():
    with pytest.raises(KeyError):
        nivel_de("azul")


def test_dataset_cobre_os_cinco_niveis(tmp_path):
    # Sem exemplo de verde o modelo so ve situacao de alerta e aprende a sempre
    # alarmar -- "sem risco" e uma saida legitima que ele tem de saber redigir.
    saida = tmp_path / "dataset.jsonl"

    gerador.gerar(saida, tmp_path / "nao_existe.jsonl")

    exemplos = [json.loads(l) for l in saida.read_text(encoding="utf-8").splitlines()]
    niveis = {e["completion"][0]["content"].split()[1] for e in exemplos}
    assert niveis == {n.cor.upper() for n in ESCALA}


def test_dataset_usa_regras_aprovadas_quando_existem(tmp_path):
    aprovadas = tmp_path / "aprovadas.jsonl"
    aprovadas.write_text(
        json.dumps(
            {
                "escala": "alerta_cor",
                "grandeza": "chuva_acumulada",
                "nivel": "roxo",
                "janela_horas": 24,
                "valor_min": 175.0,
                "valor_max": None,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    saida = tmp_path / "dataset.jsonl"

    gerador.gerar(saida, aprovadas)

    conteudo = saida.read_text(encoding="utf-8")
    assert "175" in conteudo, "o limiar aprovado deveria aparecer no dataset"
    # e o limiar de partida do roxo em 24h, 170, nao deve estar
    assert "170 mm" not in conteudo


def test_regra_de_intensidade_nao_vira_exemplo_de_alerta(tmp_path):
    # Intensidade descreve o fenomeno; nivel de alerta decide a resposta. Uma
    # classe de intensidade nao dispara alerta por si.
    aprovadas = tmp_path / "aprovadas.jsonl"
    aprovadas.write_text(
        json.dumps(
            {
                "escala": "intensidade",
                "grandeza": "taxa_precipitacao",
                "nivel": "moderada",
                "janela_horas": None,
                "valor_min": 6.0,
                "valor_max": 30.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    limiares = gerador._limiares_de_regras_aprovadas(
        [json.loads(l) for l in aprovadas.read_text(encoding="utf-8").splitlines()]
    )

    assert limiares == []


def test_toda_resposta_do_dataset_cita_o_nivel_e_a_situacao(tmp_path):
    saida = tmp_path / "dataset.jsonl"

    gerador.gerar(saida, tmp_path / "nao_existe.jsonl")

    for linha in saida.read_text(encoding="utf-8").splitlines():
        resposta = json.loads(linha)["completion"][0]["content"]
        assert resposta.startswith("NIVEL "), resposta[:40]
        cor = resposta.split()[1].lower()
        assert POR_COR[cor].situacao in resposta


def test_dataset_e_prompt_completion_nao_conversacional(tmp_path):
    # O formato importa: assistant_only_loss, a flag de mascara para dataset
    # conversacional, exige marcadores {% generation %} no chat template, que o
    # Qwen2.5 base nao tem -- o TRL falha alto. Com prompt/completion o
    # mascaramento nao depende do template.
    saida = tmp_path / "dataset.jsonl"

    gerador.gerar(saida, tmp_path / "nao_existe.jsonl")

    for linha in saida.read_text(encoding="utf-8").splitlines():
        exemplo = json.loads(linha)
        assert set(exemplo) == {"prompt", "completion"}, exemplo.keys()
        assert [m["role"] for m in exemplo["prompt"]] == ["system", "user"]
        assert [m["role"] for m in exemplo["completion"]] == ["assistant"]
