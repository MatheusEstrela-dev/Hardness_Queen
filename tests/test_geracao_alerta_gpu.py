"""O adaptador escreve o alerta certo e PARA de escrever.

Estes testes existem porque a loss nao ve nenhuma das duas coisas. Historico
medido nesta esteira, tres vezes: a loss melhorou (2,76 -> 2,48 -> 1,57 -> 0,36
-> 0,20 -> 0,08) enquanto o defeito de comportamento ficou identico. A ultima
vez foi a mais instrutiva -- o piso de 0,08 ERA o token de parada, uma posicao
entre as 113 que contam por exemplo, e nenhuma metrica de treino apontou para
ela. So gerar texto e ler mostra.

Marcados gpu: exigem a T1000 e o adaptador treinado em models/lora_treinado.
Rodar com: just test-gpu
"""

import re

import pytest

from ingestao.niveis import POR_COR

# O pytest.ini transforma todo aviso em erro, e deve continuar assim. Este aviso
# e a excecao prevista: a linha do <|im_end|> e treinavel de proposito
# (trainable_token_indices, ver scripts/02_treinar_modelo.py) e o Qwen2.5 amarra
# lm_head ao embedding. A PEFT avisa que isso complica MESCLAR o adaptador no
# modelo -- e aqui ele e apenas carregado por cima da base, nunca mesclado.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Model has `tie_word_embeddings=True` and a tied layer is part of the adapter"
    ":UserWarning"
)

MODELO_BASE = "Qwen/Qwen2.5-3B"
ADAPTADOR = "models/lora_treinado"

# Teto generoso de proposito: as respostas do dataset tem no maximo 455 chars,
# perto de 120 tokens. Se o adaptador precisar de mais de 200, ele nao esta
# escrevendo um alerta, esta desandando.
TETO_TOKENS = 200

SYSTEM_PROMPT = (
    "Voce redige alertas hidrometeorologicos para a Defesa Civil de Minas Gerais. "
    "Recebe uma decisao ja tomada -- nivel de alerta, limiar ultrapassado e local -- "
    "e escreve o texto tecnico do alerta. Nao decida o nivel: ele ja vem decidido."
)


@pytest.fixture(scope="module")
def gerar():
    """Carrega base + adaptador uma vez para o modulo inteiro.

    Carregar por teste custaria mais de um minuto cada na T1000, e o objeto e
    somente leitura aqui.
    """
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tokenizador = AutoTokenizer.from_pretrained(MODELO_BASE)
    if tokenizador.pad_token is None:
        tokenizador.pad_token = tokenizador.eos_token
    fim_de_turno = tokenizador.convert_tokens_to_ids("<|im_end|>")

    base = AutoModelForCausalLM.from_pretrained(
        MODELO_BASE,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        ),
        dtype=torch.bfloat16,
        device_map="cuda:0",
    )
    modelo = PeftModel.from_pretrained(base, ADAPTADOR)
    modelo.eval()

    def _gerar(pedido: str) -> tuple[str, bool]:
        """Devolve o texto gerado e se o adaptador encerrou o turno sozinho."""
        entrada = (
            f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{pedido}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        ids = tokenizador(entrada, return_tensors="pt", add_special_tokens=False).to("cuda:0")
        with torch.no_grad():
            saida = modelo.generate(
                **ids,
                max_new_tokens=TETO_TOKENS,
                do_sample=False,
                pad_token_id=tokenizador.pad_token_id,
                eos_token_id=fim_de_turno,
            )
        gerados = saida[0][ids["input_ids"].shape[1] :].tolist()
        texto = tokenizador.decode(gerados, skip_special_tokens=True).strip()
        return texto, fim_de_turno in gerados

    yield _gerar

    del modelo, base
    torch.cuda.empty_cache()


# Municipios que NAO estao no dataset de treino: o teste mede se o adaptador
# aprendeu a tarefa, nao se decorou os seis municipios de LOCAIS.
FORA_DO_TREINO = "Ouro Preto (Metropolitana)"

PEDIDO_VERMELHO = (
    f"Municipio: {FORA_DO_TREINO}. Acumulado em 1h: 82 mm. "
    "Limiar do nivel vermelho (Situacao de Perigo): entre 70 mm e 90 mm em 1 hora. "
    "Redija o alerta."
)


@pytest.mark.gpu
def test_adaptador_encerra_o_turno_em_vez_de_recomecar(gerar):
    # O defeito que este teste tranca: o adaptador escrevia o alerta correto e
    # seguia gerando, recomecando o texto ate o teto de tokens, porque a linha
    # do lm_head do <|im_end|> nunca foi treinada no Qwen2.5-3B base e uma LoRA
    # restrita a q/k/v/o nao alcanca a saida. Se este teste falhar, confira se
    # o <|im_end|> continua em trainable_token_indices no LoraConfig de
    # scripts/02_treinar_modelo.py.
    texto, encerrou = gerar(PEDIDO_VERMELHO)

    assert encerrou, f"nao emitiu <|im_end|> em {TETO_TOKENS} tokens: {texto[:300]}"
    # Um alerta so. Cabecalho repetido significa que ele recomecou antes de parar.
    assert texto.count("NIVEL ") == 1, texto[:300]


@pytest.mark.gpu
@pytest.mark.parametrize(
    "pedido,cor",
    [
        (PEDIDO_VERMELHO, "vermelho"),
        (
            # O nivel vem do prompt, e aqui ele contraria o que um dataset mal
            # curado ensinaria: 108 mm em 24h ja foi rotulado AMARELO no
            # gerador antigo, quando o protocolo diz LARANJA a partir de 90 mm.
            f"Municipio: {FORA_DO_TREINO}. Acumulado em 24h: 108 mm. "
            "Limiar do nivel laranja (Situacao de Alerta): superior a 90 mm em 24 horas. "
            "Redija o alerta.",
            "laranja",
        ),
        (
            "Municipio: Diamantina (Jequitinhonha). Acumulado em 24h: 195 mm. "
            "Limiar do nivel roxo (Situacao Critica): superior a 170 mm em 24 horas. "
            "Redija o alerta.",
            "roxo",
        ),
    ],
    ids=["vermelho-1h", "laranja-24h-contradiz-dataset-antigo", "roxo-24h"],
)
def test_alerta_traz_o_nivel_do_prompt_e_a_resposta_do_protocolo(gerar, pedido, cor):
    # Quem decide o nivel e o banco. O adaptador que troca o nivel decidido pelo
    # que ele associou ao numero destroi a garantia inteira da arquitetura.
    texto, _ = gerar(pedido)
    baixo = texto.lower()
    nivel = POR_COR[cor]

    assert texto.startswith(f"NIVEL {cor.upper()}"), texto[:200]
    assert nivel.situacao.lower() in baixo, texto[:200]
    outras = [c for c in POR_COR if c != cor and c != "verde"]
    assert not [c for c in outras if c in baixo], f"citou outro nivel: {texto[:250]}"
    # A resposta operacional e o motivo de o alerta existir: sem ela o texto diz
    # o nivel sem dizer o que se espera de quem le.
    primeiras = nivel.resposta.split(".")[0].lower()
    assert any(palavra in baixo for palavra in primeiras.split() if len(palavra) > 7), texto[:250]


@pytest.mark.gpu
@pytest.mark.parametrize(
    "municipio,mesorregiao",
    [
        ("Ouro Preto", "Metropolitana"),
        ("Diamantina", "Jequitinhonha"),
        ("Sao Joao del Rei", "Campo das Vertentes"),
        ("Governador Valadares", "Vale do Rio Doce"),
    ],
)
def test_alerta_copia_o_municipio_letra_por_letra(gerar, municipio, mesorregiao):
    # Um alerta oficial com o municipio errado manda a resposta para o lugar
    # errado -- e sai com a mesma autoridade de um alerta certo. Medido: com
    # LoRA no lm_head inteiro, treinada com seis municipios, o adaptador passou a
    # parar corretamente e a escrever "Ouro Prete", "Ouro Preco", "Diamantis".
    # O antigo copiava certo. Os outros testes deste modulo passaram com o nome
    # corrompido, porque nenhum conferia o nome -- por isso este existe.
    texto, _ = gerar(
        f"Municipio: {municipio} ({mesorregiao}). Acumulado em 1h: 82 mm. "
        "Limiar do nivel vermelho (Situacao de Perigo): entre 70 mm e 90 mm em 1 hora. "
        "Redija o alerta."
    )

    assert municipio in texto, f"municipio corrompido: {texto[:220]}"


@pytest.mark.gpu
@pytest.mark.xfail(
    strict=True,
    reason=(
        "o dataset nao tem nenhum exemplo de taxa: nenhum limiar de ALERTA em mm/h "
        "no catalogo (o POP so define intensidade em mm/h), e o gerador corretamente "
        "nao inventa. Medido: o adaptador escreve '130 mm/h em 1 hora', emprestando "
        "a janela dos exemplos de 1h. strict=True: quando uma regra de alerta em "
        "mm/h for aprovada e o dataset for regerado, este xfail vira falha e avisa."
    ),
)
def test_taxa_nao_vira_acumulado_com_janela_inventada(gerar):
    # mm/h e taxa instantanea; mm numa janela e acumulado. Trocar um pelo outro
    # muda o fenomeno, e o texto sairia com autoridade de alerta oficial. Foi o
    # erro mais comum da extracao na curadoria da Meteorologia (10 de 16).
    texto, _ = gerar(
        f"Municipio: {FORA_DO_TREINO}. Taxa de precipitacao: 130 mm/h. "
        "Limiar do nivel roxo (Situacao Critica): superior a 100 mm/h. Redija o alerta."
    )
    baixo = texto.lower()

    assert "mm/h" in baixo, texto[:250]
    assert "acumulado" not in baixo, texto[:250]
    # Qualquer janela numa taxa e erro, nao so a de 24h: a versao anterior
    # deste teste proibia so "24h" e deixou passar "130 mm/h em 1 hora".
    janela = re.search(r"\bem\s+\d+\s*(?:h\b|horas?\b)", baixo)
    assert janela is None, f"taxa com janela '{janela and janela.group()}': {texto[:250]}"


@pytest.mark.gpu
def test_informe_verde_nao_inventa_medicao(gerar):
    # "Sem risco" e saida legitima, e nao pode vir com um numero que ninguem
    # mediu -- o informe seria uma medicao falsa assinada pela Defesa Civil.
    texto, _ = gerar(
        f"Municipio: {FORA_DO_TREINO}. Nenhum limiar de alerta ultrapassado -- "
        "situacao de nivel verde. Redija o informe."
    )

    assert texto.startswith("NIVEL VERDE"), texto[:200]
    assert "12 mm" not in texto, texto[:250]
    assert " mm" not in texto.replace(" mm/h", ""), f"inventou medicao: {texto[:250]}"
