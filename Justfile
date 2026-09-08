set windows-shell := ["powershell.exe", "-NoProfile", "-Command"]

python := "venv/Scripts/python.exe"

# lista as receitas disponiveis
default:
    @just --list --unsorted

# checa se a T1000 esta visivel e o que ela suporta
gpu:
    @{{python}} -c "import torch; c=torch.cuda.get_device_capability(0); print('GPU:', torch.cuda.get_device_name(0)); print('compute capability:', c); print('VRAM total:', round(torch.cuda.get_device_properties(0).total_memory/1024**3,1), 'GB'); print('fp16 tensor cores:', c >= (7,0)); print('bf16 nativo:', c >= (8,0), '(abaixo de 8.0 o PyTorch emula)')"

# versoes do stack de treino (o que costuma quebrar a API)
deps:
    @{{python}} -c "import torch, transformers, trl, peft, datasets, bitsandbytes; [print(f'{n:14} {v}') for n,v in [('torch',torch.__version__),('transformers',transformers.__version__),('trl',trl.__version__),('peft',peft.__version__),('datasets',datasets.__version__),('bitsandbytes',bitsandbytes.__version__)]]"

# roda a suite de testes
test:
    {{python}} -m pytest -v

# roda tambem os testes que exigem GPU e modelo baixado
test-gpu:
    {{python}} -m pytest -v -m gpu

# gera o dataset_treino.jsonl a partir das regras dos especialistas
dataset:
    {{python}} scripts/01.gerar_dataset.py

# quantos exemplos existem hoje no dataset
dataset-stats:
    @{{python}} -c "import json; L=[json.loads(l) for l in open('data/dataset_treino.jsonl',encoding='utf-8')]; print('exemplos:', len(L)); print('turnos por exemplo:', sorted({len(e['messages']) for e in L})); print('chars no maior assistant:', max(len(m['content']) for e in L for m in e['messages'] if m['role']=='assistant'))"

# treina o adaptador LoRA (QLoRA 4-bit) na T1000
train:
    {{python}} scripts/02_treinar_modelo.py

# pipeline completo: dataset + treino
all: dataset train

# acompanha uso de VRAM durante o treino (Ctrl+C para sair)
vram:
    nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv -l 2

# mostra o adaptador treinado que esta salvo
adapter:
    @if (Test-Path models/lora_treinado/adapter_model.safetensors) { Get-ChildItem models/lora_treinado | Select-Object Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}, LastWriteTime } else { Write-Host 'Nenhum adaptador treinado ainda. Rode: just train' }

# apaga o adaptador treinado para comecar do zero
clean:
    @if (Test-Path models/lora_treinado) { Remove-Item -Recurse -Force models/lora_treinado; Write-Host 'Adaptador removido.' } else { Write-Host 'Nada para limpar.' }
