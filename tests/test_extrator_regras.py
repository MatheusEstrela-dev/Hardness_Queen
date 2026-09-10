import json
from pathlib import Path

from ingestao.contrato import Chunk
from ingestao.extrator_regras import INSTRUCAO, extrair_do_chunk, montar_prompt, processar
from ingestao.persistencia import ler_jsonl

TEXTO = "4.2 Solo gnaisse. A saturacao ocorre a partir de 100mm em 72h."


def _chunk(chunk_id: str = "c1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc="laudo.pdf",
        pagina=12,
        secao="4.2 Caracterizacao do solo",
        texto=TEXTO,
    )


def _gerador(payload: dict):
    def gerar(_prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    return gerar


def _uma_regra(
    valor_min: float | None = 100.0,
    valor_max: float | None = None,
    trecho: str = "saturacao ocorre a partir de 100mm em 72h",
    nivel: str = "roxo",
    escala: str = "alerta_cor",
    grandeza: str = "chuva_acumulada",
    unidade: str = "mm",
) -> dict:
    return {
        "regras": [
            {
                "dominio": "geologia",
                "entidade_tipo": "tipo_solo",
                "entidade_nome": "gnaisse",
                "grandeza": grandeza,
                "janela_horas": 72,
                "unidade": unidade,
                "escala": escala,
                "nivel": nivel,
                "valor_min": valor_min,
                "valor_max": valor_max,
                "fonte_trecho": trecho,
            }
        ]
    }


def test_prompt_contem_o_texto_e_a_secao_do_chunk():
    prompt = montar_prompt(_chunk())

    assert TEXTO in prompt
    assert "4.2 Caracterizacao do solo" in prompt


def test_instrucao_ensina_a_escala_por_cor():
    for cor in ("verde", "amarelo", "laranja", "vermelho", "roxo"):
        assert cor in INSTRUCAO


def test_instrucao_orienta_a_nao_quebrar_faixa_em_duas_regras():
    assert "UMA regra" in INSTRUCAO


def test_instrucao_orienta_entidade_estado_para_limiar_sem_entidade_propria():
    assert "minas gerais" in INSTRUCAO


def test_instrucao_orienta_a_distincao_entre_escala_de_cor_e_de_intensidade():
    assert "alerta_cor" in INSTRUCAO
    assert "intensidade" in INSTRUCAO
    assert "taxa_precipitacao" in INSTRUCAO
    assert "mm/h" in INSTRUCAO


def test_texto_do_chunk_vem_antes_da_instrucao_no_prompt():
    # Regressao: uma versao anterior do prompt colocava ~3400 caracteres de
    # instrucao antes do texto do documento, e o modelo respondia lista vazia
    # mesmo com limiares evidentes no trecho (ver task-11-report.md). O texto
    # do chunk precisa aparecer antes de qualquer instrucao de extracao.
    prompt = montar_prompt(_chunk())

    assert prompt.index(TEXTO) < prompt.index("Extraia TODOS")


def test_prompt_fica_curto_para_chunk_pequeno():
    # Regressao: a instrucao chegou a ~3400 caracteres antes do texto entrar
    # no prompt. Um chunk pequeno nao deveria produzir um prompt inchado --
    # cada linha extra de instrucao compete com o documento pela atencao do
    # modelo.
    prompt = montar_prompt(_chunk())

    assert len(prompt) < 1200


def test_extrair_anexa_procedencia_que_nao_veio_do_modelo():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert len(regras) == 1
    assert regras[0].fonte_doc == "laudo.pdf"
    assert regras[0].fonte_pagina == 12
    assert regras[0].fonte_secao == "4.2 Caracterizacao do solo"
    assert regras[0].chunk_id == "c1"


def test_extrair_do_chunk_marca_origem_modelo():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert regras[0].origem == "modelo"


def test_regra_boa_recebe_status_ok():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert regras[0].status == "ok"


def test_faixa_fechada_e_extraida_como_uma_unica_regra():
    payload = _uma_regra(
        valor_min=6.0,
        valor_max=30.0,
        trecho="saturacao ocorre a partir de 100mm em 72h",
    )
    regras = extrair_do_chunk(_chunk(), _gerador(payload))

    assert len(regras) == 1
    assert regras[0].valor_min == 6.0
    assert regras[0].valor_max == 30.0


def test_citacao_inventada_recebe_status_suspeito():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra(trecho="800mm em 24h")))

    assert regras[0].status == "suspeito"
    assert "trecho" in regras[0].motivo_suspeita


def test_valor_implausivel_recebe_status_suspeito():
    payload = _uma_regra(valor_min=90000.0, trecho="saturacao ocorre a partir de 100mm em 72h")
    regras = extrair_do_chunk(_chunk(), _gerador(payload))

    assert regras[0].status == "suspeito"


def test_faixa_invertida_recebe_status_suspeito():
    payload = _uma_regra(
        valor_min=100.0,
        valor_max=1.0,
        trecho="saturacao ocorre a partir de 100mm em 72h",
    )
    regras = extrair_do_chunk(_chunk(), _gerador(payload))

    assert regras[0].status == "suspeito"


def test_lista_vazia_e_resultado_legitimo():
    assert extrair_do_chunk(_chunk(), _gerador({"regras": []})) == []


def test_regra_id_e_estavel_entre_execucoes():
    primeira = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))
    segunda = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert primeira[0].regra_id == segunda[0].regra_id


def test_regra_id_muda_quando_extremo_da_faixa_muda():
    original = extrair_do_chunk(_chunk(), _gerador(_uma_regra(valor_min=100.0)))
    alterada = extrair_do_chunk(_chunk("c2"), _gerador(_uma_regra(valor_min=90.0)))

    assert original[0].regra_id != alterada[0].regra_id


def test_processar_grava_regras_e_conta(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"

    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes, falhas, sem_padrao)

    assert resumo["regras"] == 1
    assert resumo["chunks_processados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_processar_retoma_e_pula_chunk_ja_feito(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    processar([_chunk()], _gerador(_uma_regra()), saida, omissoes, falhas, sem_padrao)

    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes, falhas, sem_padrao)

    assert resumo["chunks_pulados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_chunk_com_limiar_e_zero_regras_vai_para_omissoes(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"

    resumo = processar([_chunk()], _gerador({"regras": []}), saida, omissoes, falhas, sem_padrao)

    assert resumo["omissoes"] == 1
    assert ler_jsonl(omissoes)[0]["chunk_id"] == "c1"


def _gerador_com_falha(textos_que_falham: set[str], payload: dict):
    def gerar(prompt: str) -> str:
        for texto in textos_que_falham:
            if texto in prompt:
                raise RuntimeError("saida truncada: JSON invalido")
        return json.dumps(payload, ensure_ascii=False)

    return gerar


def test_chunk_que_falha_nao_interrompe_os_demais(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    chunk_ruim = _chunk("c1")
    chunk_bom = Chunk(
        chunk_id="c2",
        doc="laudo.pdf",
        pagina=13,
        secao="4.3 Outra secao",
        texto="outro trecho qualquer, com limiar de 50mm em 24h",
    )

    resumo = processar(
        [chunk_ruim, chunk_bom],
        _gerador_com_falha({chunk_ruim.texto}, _uma_regra()),
        saida,
        omissoes,
        falhas,
        sem_padrao,
    )

    assert resumo["chunks_processados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_falha_e_registrada_no_arquivo_de_falhas_com_o_erro(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"

    processar([_chunk()], _gerador_com_falha({TEXTO}, _uma_regra()), saida, omissoes, falhas, sem_padrao)

    registros = ler_jsonl(falhas)
    assert len(registros) == 1
    assert registros[0]["chunk_id"] == "c1"
    assert registros[0]["doc"] == "laudo.pdf"
    assert registros[0]["pagina"] == 12
    assert "saida truncada" in registros[0]["erro"]


def test_resumo_conta_falhas(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"

    resumo = processar([_chunk()], _gerador_com_falha({TEXTO}, _uma_regra()), saida, omissoes, falhas, sem_padrao)

    assert resumo["falhas"] == 1


def test_reexecucao_pula_chunk_ja_marcado_como_falha(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    processar([_chunk()], _gerador_com_falha({TEXTO}, _uma_regra()), saida, omissoes, falhas, sem_padrao)

    # o gerador desta segunda chamada nao falharia mais, mas o chunk ja esta
    # marcado como falha e deve ser pulado -- o operador reprocessa apagando
    # data/possiveis_falhas.jsonl, nao automaticamente.
    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes, falhas, sem_padrao)

    assert resumo["chunks_pulados"] == 1
    assert resumo["falhas"] == 0


def _gerador_com_saida_truncada(textos_que_truncam: set[str], payload: dict):
    # Diferente de _gerador_com_falha (que simula a falha com um
    # RuntimeError deliberado), este gerador reproduz a forma exata do
    # defeito real (task-16): a geracao bate no teto de tokens no meio de
    # uma string, entao o JSON devolvido nao fecha as aspas nem os
    # colchetes. O erro que processar precisa engolir aqui vem de dentro de
    # Extracao.model_validate_json (pydantic_core.ValidationError), nao de
    # uma excecao que o proprio gerador levanta.
    def gerar(prompt: str) -> str:
        for texto in textos_que_truncam:
            if texto in prompt:
                bruto = json.dumps(payload, ensure_ascii=False)
                return bruto[: len(bruto) // 2]
        return json.dumps(payload, ensure_ascii=False)

    return gerar


def test_json_truncado_no_meio_de_uma_string_vira_falha_registrada_e_nao_para_o_lote(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    chunk_truncado = _chunk("c1")
    chunk_bom_1 = Chunk(
        chunk_id="c2",
        doc="laudo.pdf",
        pagina=13,
        secao="4.3 Outra secao",
        texto="outro trecho qualquer, com limiar de 50mm em 24h",
    )
    chunk_bom_2 = Chunk(
        chunk_id="c3",
        doc="laudo.pdf",
        pagina=14,
        secao="4.4 Mais uma secao",
        texto="ainda outro trecho, com limiar de 60mm em 24h",
    )

    resumo = processar(
        [chunk_truncado, chunk_bom_1, chunk_bom_2],
        _gerador_com_saida_truncada({chunk_truncado.texto}, _uma_regra()),
        saida,
        omissoes,
        falhas,
        sem_padrao,
    )

    assert resumo["falhas"] == 1
    assert resumo["chunks_processados"] == 2
    registros = ler_jsonl(falhas)
    assert len(registros) == 1
    assert registros[0]["chunk_id"] == "c1"
    assert len(ler_jsonl(saida)) == 2


TABELA_DE_INTENSIDADE = """
| INTENSIDADE | TAXA DE PRECIPITACAO |
| --- | --- |
| Fraca | <= 6,0 mm/h |
| Moderada | 6 mm/h a 30 mm/h |
| Forte | 30 mm/h a 70 mm/h |
| Muito Forte | 70 mm/h a 90 mm/h |
| Extremo | > 90mm/h |
"""


def _gerador_que_conta_chamadas(payload: dict):
    chamadas = {"total": 0}

    def gerar(_prompt: str) -> str:
        chamadas["total"] += 1
        return json.dumps(payload, ensure_ascii=False)

    return gerar, chamadas


def test_chunk_com_tabela_reconhecida_nao_chama_o_gerador(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    chunk_com_tabela = Chunk(
        chunk_id="c1",
        doc="protocolo.docx",
        pagina=5,
        secao="3. Intensidade",
        texto=TABELA_DE_INTENSIDADE,
    )
    gerar, chamadas = _gerador_que_conta_chamadas(_uma_regra())

    resumo = processar([chunk_com_tabela], gerar, saida, omissoes, falhas, sem_padrao)

    assert chamadas["total"] == 0
    assert resumo["chunks_via_tabela"] == 1
    assert resumo["chunks_via_modelo"] == 0
    assert resumo["regras_via_tabela"] == 5
    assert resumo["regras"] == 5
    propostas = ler_jsonl(saida)
    assert len(propostas) == 5
    assert all(p["origem"] == "tabela" for p in propostas)


def test_chunk_sem_tabela_chama_o_gerador_normalmente(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    gerar, chamadas = _gerador_que_conta_chamadas(_uma_regra())

    resumo = processar([_chunk()], gerar, saida, omissoes, falhas, sem_padrao)

    assert chamadas["total"] == 1
    assert resumo["chunks_via_tabela"] == 0
    assert resumo["chunks_via_modelo"] == 1
    assert resumo["regras_via_modelo"] == 1
    propostas = ler_jsonl(saida)
    assert propostas[0]["origem"] == "modelo"


def test_linhas_de_tabela_ignoradas_contam_mesmo_quando_o_chunk_vai_para_o_modelo(tmp_path: Path):
    # Um chunk cuja unica tabela e a de dados historicos (nao produz regra)
    # ainda deve cair no modelo -- e a contagem de linhas ignoradas precisa
    # aparecer no resumo mesmo assim, senao ela fica invisivel justamente no
    # caso em que mais importa (task-19-brief).
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    texto_com_tabela_historica = (
        "|Cidades|N de evento|Data|Limiar|CAD|\n"
        "|---|---|---|---|---|\n"
        "|Januaria|3|08/12/2023 - 45mm|40mm|2|\n"
    )
    chunk = Chunk(chunk_id="c1", doc="protocolo.docx", pagina=2, secao="2. Historico", texto=texto_com_tabela_historica)
    gerar, chamadas = _gerador_que_conta_chamadas({"regras": []})

    resumo = processar([chunk], gerar, saida, omissoes, falhas, sem_padrao)

    assert chamadas["total"] == 1
    assert resumo["linhas_de_tabela_ignoradas"] == 1
    assert resumo["chunks_via_modelo"] == 1


def test_chunk_sem_padrao_de_limiar_nao_chama_o_gerador_e_e_contado(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    chunk_sem_padrao = Chunk(
        chunk_id="c1",
        doc="laudo.pdf",
        pagina=1,
        secao="1. Introducao",
        texto="este capitulo descreve a metodologia adotada no estudo, sem nenhum limiar numerico.",
    )
    gerar, chamadas = _gerador_que_conta_chamadas(_uma_regra())

    resumo = processar([chunk_sem_padrao], gerar, saida, omissoes, falhas, sem_padrao)

    assert chamadas["total"] == 0
    assert resumo["chunks_sem_padrao"] == 1
    assert resumo["chunks_via_modelo"] == 0
    assert len(ler_jsonl(saida)) == 0


def test_chunk_com_padrao_de_limiar_chama_o_gerador(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    gerar, chamadas = _gerador_que_conta_chamadas(_uma_regra())

    resumo = processar([_chunk()], gerar, saida, omissoes, falhas, sem_padrao)

    assert chamadas["total"] == 1
    assert resumo["chunks_sem_padrao"] == 0


def test_chunk_sem_padrao_e_gravado_e_pulado_na_reexecucao(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    falhas = tmp_path / "falhas.jsonl"
    sem_padrao = tmp_path / "sem_padrao.jsonl"
    chunk_sem_padrao = Chunk(
        chunk_id="c1",
        doc="laudo.pdf",
        pagina=1,
        secao="1. Introducao",
        texto="este capitulo descreve a metodologia adotada no estudo, sem nenhum limiar numerico.",
    )

    processar([chunk_sem_padrao], _gerador(_uma_regra()), saida, omissoes, falhas, sem_padrao)

    registros = ler_jsonl(sem_padrao)
    assert len(registros) == 1
    assert registros[0]["chunk_id"] == "c1"
    assert registros[0]["doc"] == "laudo.pdf"
    assert registros[0]["pagina"] == 1
    assert "texto" not in registros[0]

    resumo = processar([chunk_sem_padrao], _gerador(_uma_regra()), saida, omissoes, falhas, sem_padrao)

    assert resumo["chunks_pulados"] == 1
    assert resumo["chunks_sem_padrao"] == 0
