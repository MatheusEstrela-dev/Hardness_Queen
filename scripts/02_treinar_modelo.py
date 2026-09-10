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

# 4. O dataset vai ao TRL no formato conversacional, sem achatar
#
# A versao anterior achatava as mensagens num unico campo de texto e usava
# dataset_text_field="text". Isso fazia o TRL tratar o exemplo como completacao
# de texto puro, e a loss cobria a sequencia INTEIRA -- inclusive os turnos de
# sistema e de usuario. O adaptador aprendia a gerar a conversa toda: na
# geracao ele terminava o alerta e comecava um novo turno ("Human: Translate to
# English..."), sem nunca emitir <|im_end|>. Medido com 156 exemplos.
#
# Passando a coluna `messages` direto, o TRL aplica o chat template do modelo e
# mascara o prompt, entao a loss cobre apenas a resposta do assistente -- a
# unica coisa que este adaptador precisa aprender a escrever.
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
    # Mascara o prompt: a loss cobre so a resposta. Sem isto o modelo aprende a
    # gerar a conversa INTEIRA e, na geracao, termina o alerta e comeca um novo
    # turno em vez de parar -- medido: 180 tokens gerados sem nunca emitir
    # <|im_end|>.
    #
    # O dataset e prompt-completion (colunas `prompt` e `completion`), nao
    # conversacional de turno unico. Duas razoes:
    #
    # 1. Descreve melhor a tarefa. Este adaptador nao conversa: recebe uma
    #    decisao ja tomada pelo banco e escreve o texto do alerta. E um
    #    mapeamento de entrada para saida.
    # 2. assistant_only_loss, a flag para dataset conversacional, exige que o
    #    chat template do modelo marque a resposta com {% generation %}. O
    #    template do Qwen2.5 base nao tem esses marcadores e o TRL falha alto:
    #    "The chat template is not training-compatible". Com prompt-completion
    #    o mascaramento nao depende do template.
    #
    # Historico que vale nao repetir: antes disto o script achatava as
    # mensagens num campo de texto unico com dataset_text_field, e a loss
    # cobria a sequencia inteira. Depois tentou-se completion_only_loss sobre
    # dataset conversacional -- e o TRL IGNOROU A FLAG EM SILENCIO, sem aviso
    # no log, gastando uma hora de GPU no comportamento errado. A loss caiu de
    # 0,36 para 0,20 e o defeito continuou identico: loss mede ajuste ao alvo,
    # e o alvo estava errado.
    completion_only_loss=True,
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