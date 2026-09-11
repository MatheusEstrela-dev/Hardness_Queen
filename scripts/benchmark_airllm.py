"""Comparacao local de inferencia: Qwen identico, prompts e limites identicos.

Cada backend roda em processo separado. Nao altera a esteira de producao.
O primeiro ensaio mede geracao apos carregar; os seguintes reutilizam o modelo.
"""

import argparse
import importlib.metadata
import json
import statistics
import subprocess
import time
from pathlib import Path


CASOS = [
    ("geo_96h", "Para deslizamentos em Ipatinga, em 96 horas: observacao 80 mm, "
     "atencao 90 mm, critico 110 mm, emergencial 120 mm.", [80, 90, 110, 120]),
    ("inundacao_15min", "Para inundacao e alagamento em Ipatinga, em 15 minutos: "
     "observacao 5 mm, atencao 10 mm, critico 15 mm, emergencial 50 mm.", [5, 10, 15, 50]),
    ("sem_limiar", "O plano descreve a organizacao das equipes municipais, "
     "mas nao informa valores numericos de chuva.", []),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["transformers_nf4", "airllm", "airllm_4bit"], required=True)
    parser.add_argument("--model", type=Path, required=True, help="Snapshot local Qwen2.5-7B-Instruct")
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--shards", type=Path, default=Path("venv/airllm-bench/shards"))
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--permitir-desktop", action="store_true", help="Aceita atividade grafica com VRAM abaixo de 2 GiB; registra a interferencia potencial")
    parser.add_argument("--disable-mmap", action="store_true", help="Leitura alternativa de pesos do Transformers para diagnosticar falhas nativas no Windows")
    parser.add_argument("--max-time", type=float, default=180, help="Limite por geracao em segundos; conferido ao fim de cada token")
    args = parser.parse_args()
    if args.repeticoes < 1 or not (args.model / "config.json").is_file():
        parser.error("Informe snapshot local valido e repeticoes >= 1.")
    estado = subprocess.check_output([
        "nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"
    ], text=True).splitlines()[0]
    utilizacao, memoria = [int(v.strip()) for v in estado.split(",")]
    if (utilizacao > 10 and not args.permitir_desktop) or memoria > 2048:
        parser.error("GPU ocupada; aguarde a extracao atual. Nenhum processo sera interrompido.")

    import psutil
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    ram_inicial = psutil.virtual_memory()._asdict()
    torch.manual_seed(42)
    torch.cuda.reset_peak_memory_stats()
    inicio = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    if args.backend == "transformers_nf4":
        modelo = AutoModelForCausalLM.from_pretrained(
            args.model, local_files_only=True, device_map="cuda:0", dtype=torch.bfloat16,
            disable_mmap=args.disable_mmap,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        )
    else:
        from airllm import AutoModel

        modelo = AutoModel.from_pretrained(
            str(args.model), device="cuda:0", dtype=torch.bfloat16, max_seq_len=512,
            layer_shards_saving_path=str(args.shards.resolve() / args.backend),
            compression="4bit" if args.backend == "airllm_4bit" else None,
            delete_original=False, prefetching=True,
        )
    torch.cuda.synchronize()
    carga_s = time.perf_counter() - inicio
    print(json.dumps({"evento": "modelo_carregado", "segundos": carga_s}), flush=True)
    resultados = []
    processo = psutil.Process()
    for repeticao in range(args.repeticoes):
        for nome, texto, esperado in CASOS:
            prompt = tokenizer.apply_chat_template([
                {"role": "system", "content": "Extraia os valores numericos de chuva em mm. "
                 "Responda somente com um array JSON na ordem em que aparecem. "
                 "Se nao houver valores, responda []. Nao inclua numeros de tempo."},
                {"role": "user", "content": texto},
            ], tokenize=False, add_generation_prompt=True)
            tokens = tokenizer(prompt, return_tensors="pt")["input_ids"].to("cuda:0")
            torch.cuda.reset_peak_memory_stats()
            inicio = time.perf_counter()
            class Progresso:
                def __init__(self):
                    self.prompt = True
                    self.tokens = 0
                def put(self, valor):
                    if self.prompt:
                        self.prompt = False
                        return
                    self.tokens += valor.numel()
                    print(json.dumps({"evento": "token", "caso": nome, "tokens": self.tokens,
                                      "segundos": time.perf_counter() - inicio}), flush=True)
                def end(self):
                    pass
            with torch.inference_mode():
                saida = modelo.generate(tokens, max_new_tokens=64, do_sample=False, use_cache=True,
                                        max_time=args.max_time, streamer=Progresso(),
                                        return_dict_in_generate=True, pad_token_id=tokenizer.eos_token_id)
            torch.cuda.synchronize()
            segundos = time.perf_counter() - inicio
            novos = saida.sequences[0, tokens.shape[1]:]
            resposta = tokenizer.decode(novos, skip_special_tokens=True).strip()
            try:
                correto = json.loads(resposta) == esperado
            except json.JSONDecodeError:
                correto = False
            resultados.append({"caso": nome, "repeticao": repeticao, "segundos": segundos,
                "tokens_entrada": tokens.shape[1], "tokens_saida": len(novos),
                "tokens_por_segundo": len(novos) / segundos, "saida": resposta,
                "json_e_valores_corretos": correto,
                "pico_vram_allocated_bytes": torch.cuda.max_memory_allocated(),
                "pico_vram_reserved_bytes": torch.cuda.max_memory_reserved(),
                "rss_apos_geracao_bytes": processo.memory_info().rss})
            print(json.dumps(resultados[-1], ensure_ascii=False), flush=True)
            args.saida.parent.mkdir(parents=True, exist_ok=True)
            args.saida.with_suffix(".parcial.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    relatorio = {"backend": args.backend, "modelo": str(args.model.resolve()),
        "ram_inicial": ram_inicial, "gpu_utilizacao_inicial": utilizacao,
        "gpu_memoria_inicial_mib": memoria, "desktop_permitido": args.permitir_desktop,
        "disable_mmap": args.disable_mmap,
        "max_time_por_geracao_s": args.max_time,
        "carga_e_preparacao_s": carga_s, "ensaios": resultados,
        "mediana_segundos": statistics.median(r["segundos"] for r in resultados),
        "acertos": sum(r["json_e_valores_corretos"] for r in resultados),
        "total": len(resultados), "torch": torch.__version__,
        "transformers": importlib.metadata.version("transformers"),
        "airllm": importlib.metadata.version("airllm") if args.backend.startswith("airllm") else None,
        "limites": ["Microbenchmark de inferencia; nao mede treino ou extracao com schema Outlines.",
                    "RSS e amostra apos geracao, nao pico de RAM.",
                    "VRAM PyTorch nao inclui memoria do desktop ou todo o contexto CUDA.",
                    "Nao e comparacao numerica equivalente: NF4 e streaming usam representacoes diferentes."]}
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
