import torch
import os
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig

# 1. Caminhos e Configurações Iniciais
MODEL_ID = "Qwen/Qwen2.5-3B"
DATASET_PATH = "data/dataset_treino.jsonl"
OUTPUT_DIR = "models/lora_treinado"

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"Carregando dataset de {DATASET_PATH}...")
dataset = load_dataset("json", data_files=DATASET_PATH, split="train")

# 2. Truque de Memória (4-bit) para a NVIDIA T1000 de 8GB
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

print(f"Baixando e carregando o modelo base {MODEL_ID}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# Carrega o modelo direto na placa de vídeo
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    dtype=torch.bfloat16,
    device_map="cuda:0"
)

# 3. Preparação Otimizada e LoRA
model = prepare_model_for_kbit_training(model)
model.gradient_checkpointing_enable() # Economiza muita VRAM em troca de processamento

peft_config = LoraConfig(
    r=16, 
    lora_alpha=32, 
    lora_dropout=0.05, 
    bias="none", 
    task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]
)

model = get_peft_model(model, peft_config)
model.print_trainable_parameters()

# 4. Convertendo ChatML para texto corrido
def formatar_chat(exemplo):
    texto = ""
    for msg in exemplo['messages']:
        texto += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
    return {"text": texto}

dataset = dataset.map(formatar_chat, remove_columns=dataset.column_names)
# 5. Configuração Extrema para Hardware Limitado
args = SFTConfig(
    output_dir=OUTPUT_DIR,
    num_train_epochs=5,             
    per_device_train_batch_size=1,  
    gradient_accumulation_steps=4,  
    optim="paged_adamw_8bit",       
    learning_rate=2e-4,
    bf16=True,
    logging_steps=1,
    save_strategy="no",
    max_length=512,
    dataset_text_field="text",
)

# 6. Partida do Motor
print("Iniciando o treinamento...")
trainer = SFTTrainer(
    model=model,
    args=args,
    train_dataset=dataset,
    processing_class=tokenizer,
)

torch.cuda.empty_cache() 
trainer.train()

print("Salvando o adaptador treinado...")
trainer.model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"Sucesso! O cérebro do modelo foi salvo em '{OUTPUT_DIR}'.")