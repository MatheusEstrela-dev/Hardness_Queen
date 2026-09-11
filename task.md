frequentes

O AirLLM reduz drasticamente o uso de memória de inferência, permitindo que modelos de linguagem de até 70 bytes sejam executados em uma única placa de GPU de 4 GB — sem quantização, destilação ou poda. Você pode até mesmo executar o Kimi K3 (2,8T) — o maior modelo de código aberto lançado até o momento — com menos de 4 GB de VRAM , o Qwen3.8-Flash-Next (125B) com 6 GB e o DeepSeek-V3 (671B) com cerca de 12 GB . Agora também oferecemos suporte ao treinamento de modelos enormes com pouca VRAM: Qwen3.8-Flash-Next (125B) com menos de 6 GB .

Estrelas do repositório do GitHub Downloads

Licença de código crachá genérico Discórdia PyPI - AirLLM Site Site Apoie-me no Patreon Patrocinadores do GitHub

Recomendação de agentes de IA:
Melhor Gerador de Sprites para Jogos com IA

O melhor editor de expressões faciais com IA

Atualizações
[2026/09] Suporte ao treinamento : transmita pesos congelados uma camada por vez e mantenha os adaptadores na GPU. Qwen3.8-Flash-Next (125B) treina com menos de 6GB (RTX 3060 Ti); Qwen3.8-27B treina com ~2GB na sequência 512. Veja Treinamento .

[2026/08] Suporte ao Qwen3.8-Flash-Next : O carro-chefe do Qwen, Qwen4ExpForConditionalGenerationcom 125B MoE ( ), e uma incorporação de n-gramas de ~51B, utiliza 5,95 GB de VRAM, medida de ponta a ponta em uma RTX 4090. A tabela de n-gramas é mapeada em arquivo no host (uma máquina com 64 GB é suficiente); as camadas do decodificador são transmitidas em fluxo contínuo. Requer uma transformerscompilação com código in-tree qwen4_exp( pip install git+https://github.com/huggingface/transformers.gitatualmente) e ~360 GB de disco de checkpoint ( delete_original=Truerecupera os originais após a divisão).

[2026/08] Suporte para Qwen3.8-27B : O novo VL denso do Qwen (Gated DeltaNet + Gated Attention, visão nativa) roda em 3,33 GB de VRAM, medido de ponta a ponta em uma RTX 3090. Requer transformersAndroid 5.8 ou superior.

[2026/07] Suporte para Kimi K3 (2.8T) : o maior modelo de código aberto roda em uma única placa com 3,72 GB de VRAM, medido de ponta a ponta em uma RTX 6000 Ada. O streaming por especialista carrega apenas os especialistas para os quais um token é roteado. O K3 traz três requisitos próprios: pip install compressed-tensors flash-attn(seu código de modelo exige atenção à memória flash independentemente do que você solicitar), uma versão do torch para CUDA 12, já que ainda não existe um pacote flash-attn pré-compilado para CUDA 13, e a transformersversão 4.56.x, pois seu código remoto não carrega na versão 5.x.

[2026/06] v3.0 : Suporte ao modelo FP8 + os modelos mais recentes. Execute DeepSeek-V3 (671B) em ~12GB e Qwen3-235B em ~3GB , além de Qwen3, Llama 3.x/4, DeepSeek V2/V3, Phi-4, Gemma e mais — tudo através de um único AutoModel.

[20/08/2024] v2.11.0: Suporte para Qwen2.5

[18/08/2024] v2.10.1 Suporte para inferência de CPU. Suporte para modelos não fragmentados. Obrigado @NavodPeiris pelo excelente trabalho!

[2024/07/30] Suporte para Llama3.1 405B ( exemplo de notebook ). Suporte para quantização de 8 bits/4 bits .

[20/04/2024] O AirLLM já oferece suporte nativo ao Llama3. Execute o Llama3 70B em uma GPU única de 4 GB.

[25/12/2023] v2.8.2: Suporte para MacOS executando modelos de linguagem grandes de 70 bits.

[20/12/2023] v2.7: Suporte para AirLLMMixtral.

[20/12/2023] v2.6: Adicionado o AutoModel, que detecta automaticamente o tipo de modelo, sem necessidade de fornecer a classe do modelo para inicializá-lo.

[18/12/2023] v2.5: Adicionada pré-busca para sobrepor o carregamento e o processamento do modelo. Melhoria de velocidade de 10%.

[03/12/2023] Adicionado suporte para ChatGLM , QWen , Baichuan , Mistral e InternLM !

[02/12/2023] Adicionado suporte para safetensors. Agora suporta todos os 10 melhores modelos no ranking Open LLM.

[01/12/2023] airllm 2.0. Suporte a compressões: aumento de 3x na velocidade de execução!

[20/11/2023] airllm Versão inicial!

História das Estrelas
Mapa histórico das estrelas
Índice
Início rápido
Compressão de modelo
Configurações
Executar no MacOS
Exemplos de cadernos
Modelos suportados
Treinamento
Reconhecimento
Perguntas frequentes
Início rápido
1. Instale o pacote
Primeiro, instale o pacote pip airllm.

pip install airllm
2. Inferência
Em seguida, inicialize o AirLLMLlama2, passe o ID do repositório Hugging Face do modelo que está sendo usado ou o caminho local, e a inferência poderá ser realizada de forma semelhante a um modelo Transformer comum.

Você também pode especificar o caminho para salvar o modelo em camadas dividido através de layer_shards_saving_path ao inicializar o AirLLMLlama2.

from airllm import AutoModel

MAX_LENGTH = 128
# just pass a hugging face repo id — works with almost any popular model:
model = AutoModel.from_pretrained("Qwen/Qwen3-32B")

# go bigger with the exact same one line:
#model = AutoModel.from_pretrained("Qwen/Qwen3.8-27B")          # 27B dense VL, 3.33GB
#model = AutoModel.from_pretrained("Qwen/Qwen3.8-Flash-Next")    # 125B MoE + 51B PLE, 5.95GB
#model = AutoModel.from_pretrained("Qwen/Qwen3-235B-A22B")     # 235B, runs in ~3GB
#model = AutoModel.from_pretrained("deepseek-ai/DeepSeek-V3")  # 671B, runs in ~12GB

# or use a model's local path...
#model = AutoModel.from_pretrained("/home/ubuntu/.cache/huggingface/hub/models--Qwen--Qwen3-32B/snapshots/...")

input_text = [
        'What is the capital of United States?',
        #'I like',
    ]

input_tokens = model.tokenizer(input_text,
    return_tensors="pt", 
    return_attention_mask=False, 
    truncation=True, 
    max_length=MAX_LENGTH, 
    padding=False)
           
generation_output = model.generate(
    input_tokens['input_ids'].cuda(), 
    max_new_tokens=20,
    use_cache=True,
    return_dict_in_generate=True)

output = model.tokenizer.decode(generation_output.sequences[0])

print(output)
Observação: Durante a inferência, o modelo original será decomposto e salvo camada por camada. Certifique-se de que haja espaço suficiente em disco no diretório de cache do Hugging Face.

Compressão de modelos - Aceleração de inferência em 3x!
Acabamos de adicionar compressão de modelo baseada em quantização por blocos. Isso pode acelerar ainda mais a inferência em até 3 vezes , com perda de precisão quase insignificante! (Veja mais avaliações de desempenho e por que usamos quantização por blocos neste artigo .)

melhoria_de_velocidade

Como ativar a aceleração da compressão de modelos:
Passo 1. Certifique-se de ter o BitsandBytes instalado.pip install -U bitsandbytes 
Passo 2. Certifique-se de que a versão do airllm seja posterior a 2.0.0:pip install -U airllm
Etapa 3. Ao inicializar o modelo, passe o argumento de compressão ('4 bits' ou '8 bits'):
model = AutoModel.from_pretrained("garage-bAInd/Platypus2-70B-instruct",
                     compression='4bit' # specify '8bit' for 8-bit block-wise quantization 
                    )
Quais são as diferenças entre compressão de modelos e quantização?
Normalmente, a quantização precisa quantizar tanto os pesos quanto as ativações para realmente acelerar o processo. Isso torna mais difícil manter a precisão e evitar o impacto de valores discrepantes em todos os tipos de entradas.

Embora, no nosso caso, o gargalo esteja principalmente no carregamento do disco, precisamos apenas reduzir o tamanho do carregamento do modelo. Assim, conseguimos quantizar apenas a parte dos pesos, o que facilita a garantia da precisão.

Configurações
Ao inicializar o modelo, oferecemos suporte às seguintes configurações:

Compressão : opções suportadas: 4 bits, 8 bits para quantização em blocos de 4 ou 8 bits, ou, por padrão, None para nenhuma compressão.
profiling_mode : opções suportadas: True para exibir os tempos de consumo ou False por padrão.
layer_shards_saving_path : opcionalmente, outro caminho para salvar o modelo dividido.
hf_token : o token do Hugging Face pode ser fornecido aqui ao baixar modelos restritos como: meta-llama/Llama-2-7b-hf
Pré-busca : a pré-busca sobrepõe o carregamento e o processamento do modelo. Ativada por padrão. No momento, apenas o AirLLMLlama2 oferece suporte a isso.
delete_original : se você não tiver muito espaço em disco, pode definir delete_original como true para excluir o modelo original do rosto abraçado baixado, mantendo apenas o transformado para economizar metade do espaço em disco.
MacOS
Basta instalar o airllm e executar o código da mesma forma que no Linux. Veja mais em Início Rápido .

Certifique-se de ter instalado o mlx e o torch.
Você provavelmente precisa instalar o Python nativo. Veja mais aqui.
Somente o Apple Silicon é compatível.
Exemplo [notebook Python] ( https://github.com/lyogavin/airllm/blob/main/air_llm/examples/run_on_macos.ipynb )

Exemplo de Notebook Python
Exemplos de colaborações aqui:

Abrir no Colab
Exemplo de outros modelos (ChatGLM, QWen, Baichuan, Mistral, etc):
Detalhes
Para solicitar suporte para outros modelos: aqui
Modelos suportados
O AirLLM funciona imediatamente com praticamente todos os LLMs abertos populares — basta passar seu ID do Hugging Face para AutoModel.from_pretrained(...). Isso abrange todas as principais famílias:

Llama (2 / 3 / 3.1 / 3.3 / 4) · Qwen (1 / 2 / 2.5 / 3 / 3.5 / 3.8, incluindo MoE, Flash-Next, FP8 e VL nativo) · DeepSeek (V2 / V3 / R1) · Mistral & Mixtral · Phi · Gemma · ChatGLM · Baichuan · InternLM · Yi · Kimi K3 — e a maioria dos novos modelos no dia do lançamento.

GPU minúscula, modelos enormes
O segredo: o AirLLM mantém apenas uma camada na GPU por vez , então a VRAM necessária depende do tamanho da camada do modelo — e não do seu tamanho total. É assim que um modelo 671B cabe em uma placa de vídeo para entusiastas:

Modelo	Tamanho	VRAM da GPU
Qwen3 / Mistral / Phi (≈8B)	8B	~1–2 GB
Qwen3-30B / Mixtral (MoE)	30–47B	~1–3 GB
Qwen3.8-27B (VL denso)	27B	3,33 GB
Qwen3.8-Flash-Next (MoE + PLE)	~180B	5,95 GB
Qwen3-235B (MoE)	235B	~3 GB
Lhama 3.x 70B (precisão total)	70B	~4 GB
Lhama 3.1 405B	405B	~8 GB
DeepSeek-V3	671B	~12 GB
A mesma linha de código para todos eles — nenhuma configuração especial.

Treinamento
O AirLLM consegue ajustar modelos enormes em uma GPU pequena. Os pesos base congelados são transferidos do disco, uma camada de decodificador por vez; apenas os adaptadores permanecem residentes. O Qwen3.8-Flash-Next (125B) treina em menos de 6GB ; o Qwen3.8-27B treina em cerca de 2GB na sequência 512.

Este não é o Hugging Face Trainer / bitsandbytes QLoRA. O Flash-Next precisa de uma transformerscompilação com código integrado qwen4_exp( pip install git+https://github.com/huggingface/transformers.githoje).

1. Prepare um conjunto de dados
Um objeto JSON por linha ( .jsonl). O campo usual é text— previsão do próximo token em toda a string:

{"text": "Your first training document. Can be a few sentences or a few paragraphs."}
{"text": "Your second training document."}
Pares de instruções também funcionam. A perda é aplicada somente na conclusão:

{"prompt": "What is AirLLM?", "completion": "A library that runs and trains huge models on small VRAM."}
{"instruction": "Translate to English", "input": "bonjour", "output": "hello"}
Um .txtarquivo também serve: um exemplo por bloco separado por linhas em branco. Um arquivo inicial de duas linhas está localizado em air_llm/examples/sft_example.jsonl.

2. Treinamento de corrida
A partir da raiz do repositório, aponte --datapara o seu arquivo:

python air_llm/examples/train_qwen38_flash_next_lora.py \
  --data my_data.jsonl \
  --seq-len 512 \
  --epochs 1 \
  --save-adapter qwen38-flash-next-lora.pt
Para o modelo denso 27B:

python air_llm/examples/train_qwen38_lora.py \
  --data my_data.jsonl \
  --seq-len 512 \
  --epochs 1 \
  --save-adapter qwen38-27b-lora.pt
--steps NO script para após N exemplos (útil para um teste rápido). Omitir --dataessa opção fará com que o script se ajuste excessivamente a um trecho de código predefinido.

API Python
from airllm import AirLLMLoRAQwen4Exp

trainer = AirLLMLoRAQwen4Exp(
    "Qwen/Qwen3.8-Flash-Next",
    max_seq_len=512,
    lora_r=16,
    delete_original=True,
)

tok = trainer.tokenizer
if tok.pad_token_id is None:
    tok.pad_token = tok.eos_token

encoded = tok(
    "Your training text here.",
    return_tensors="pt",
    truncation=True,
    max_length=512,
)
loss = trainer.train_step(
    encoded["input_ids"].cuda(),
    attention_mask=encoded.get("attention_mask"),
)
print(loss)
trainer.save_adapter("qwen38-flash-next-lora.pt")
AirLLMLoRAé a mesma API para Qwen/Qwen3.8-27B.

Reconhecimento
Boa parte do código é baseado no excelente trabalho de SimJeg na competição de exames do Kaggle. Um grande agradecimento a SimJeg!

Conta do GitHub @SimJeg , o código no Kaggle , a discussão associada .

Perguntas frequentes
1. MetadataIncompleteBuffer
safetensors_rust.SafetensorError: Erro ao desserializar o cabeçalho: MetadataIncompleteBuffer

Se você se deparar com esse erro, a causa mais provável é a falta de espaço em disco. O processo de divisão do modelo consome muitos recursos do disco. Veja isto . Talvez seja necessário liberar espaço em disco, limpar o cache do Hugging Face e executar o comando novamente.

2. ValueError: o argumento max() é uma sequência vazia
Muito provavelmente você está carregando o modelo QWen ou ChatGLM com a classe Llama2. Tente o seguinte:

Para o modelo QWen:

from airllm import AutoModel #<----- instead of AirLLMLlama2
AutoModel.from_pretrained(...)
Para o modelo ChatGLM:

from airllm import AutoModel #<----- instead of AirLLMLlama2
AutoModel.from_pretrained(...)
3. Erro 401 do cliente....O modelo de repositório ... é controlado.
Alguns modelos são restritos e exigem um token da API do Hugging Face. Você pode fornecer o hf_token:

model = AutoModel.from_pretrained("meta-llama/Llama-2-7b-hf", #hf_token='HF_API_TOKEN')
4. ValueError: Solicitação de preenchimento, mas o analisador léxico não possui um token de preenchimento.
O tokenizador de alguns modelos não possui um token de preenchimento, então você pode definir um token de preenchimento ou simplesmente desativar a configuração de preenchimento:

input_tokens = model.tokenizer(input_text,
   return_tensors="pt", 
   return_attention_mask=False, 
   truncation=True, 
   max_length=MAX_LENGTH, 
   padding=False  #<-----------   turn off padding 
)
Citando AirLLM
Se você achar o AirLLM útil em sua pesquisa e desejar citá-lo, utilize a seguinte entrada BibTeX:

@software{airllm2023,
  author = {Gavin Li},
  title = {AirLLM: scaling large language models on low-end commodity computers},
  url = {https://github.com/lyogavin/airllm/},
  version = {0.0},
  year = {2023},
}
