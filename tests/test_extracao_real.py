import time

import pytest

from ingestao.contrato import Chunk
from ingestao.extrator_regras import criar_gerador_qwen, extrair_do_chunk

TEXTO = (
    "4.2 Caracterizacao do solo. Para o solo gnaisse, a saturacao critica "
    "ocorre a partir de 100mm de chuva acumulada em 72h. Para o solo argiloso, "
    "o limiar critico e de 80mm em 72h."
)


@pytest.mark.gpu
def test_modelo_real_extrai_os_dois_limiares_do_trecho():
    import torch

    chunk = Chunk(chunk_id="c1", doc="laudo.pdf", pagina=12, secao="4.2 Caracterizacao do solo", texto=TEXTO)

    torch.cuda.reset_peak_memory_stats()
    # Pino explicitamente o 3B base em vez de herdar MODELO_PADRAO: essa
    # constante e o modelo de producao (7B-Instruct), e este teste so mede o
    # que coube em disco nesta sessao. Nao deixar essa medicao arrastar o
    # padrao de producao junto.
    gerar = criar_gerador_qwen(model_id="Qwen/Qwen2.5-3B")
    inicio = time.time()
    regras = extrair_do_chunk(chunk, gerar)
    decorrido = time.time() - inicio
    pico_gb = torch.cuda.max_memory_allocated() / 1024**3

    print(f"\ntempo por chunk: {decorrido:.1f}s | VRAM pico: {pico_gb:.2f}GB | regras: {len(regras)}")

    assert len(regras) == 2
    valores = sorted(regra.valor for regra in regras)
    assert valores == [80.0, 100.0]
    assert all(regra.status == "ok" for regra in regras)
    assert pico_gb < 8.0
