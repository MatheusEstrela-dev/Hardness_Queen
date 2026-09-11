# ============================================================================
# HARDNESS IA - JUSTFILE ORQUESTRADOR
# Assistente tecnico da Defesa Civil de Minas Gerais
# ============================================================================
# Uso: just <comando> | just --list | just help
# ----------------------------------------------------------------------------
# DOIS FLUXOS, UMA FONTE DE VERDADE:
#   ingestao  -> laudos PDF/DOCX viram limiares revisados  (etapas 03..06)
#   treino    -> limiares viram exemplos e adaptador LoRA   (etapas 01..02)
#
# O banco decide, o modelo redige. Limiar e DADO, nunca peso de rede.
# ============================================================================

# Windows: caminho explicito do Git Bash (o "bash" do PATH e o do WSL)
set windows-shell := ["C:/Program Files/Git/bin/bash.exe", "-uc"]
set shell := ["bash", "-uc"]

# ============================================================================
# CORES ANSI
# ============================================================================
GREEN  := '\033[32m'
YELLOW := '\033[33m'
BLUE   := '\033[34m'
RED    := '\033[31m'
CYAN   := '\033[36m'
GRAY   := '\033[90m'
BOLD   := '\033[1m'
RESET  := '\033[0m'

# Python do projeto. NUNCA o global: o stack de treino esta pregado neste venv.
python := "venv/Scripts/python.exe"

# Area de trabalho: cada equipe tem docs/<area>/ e data/<area>/. Troque com
#   just area=Geologia extrair-texto
# Os scripts leem a mesma escolha pela variavel exportada (ingestao/caminhos.py).
area := env_var_or_default("HARDNESS_AREA", "Meteorologia")
export HARDNESS_AREA := area

# Artefatos da esteira, na area escolhida
chunks_dir := "data/" + area + "/chunks"
propostas  := "data/" + area + "/regras_propostas.jsonl"
aprovadas  := "data/" + area + "/regras_aprovadas.jsonl"
decisoes   := "data/" + area + "/decisoes.jsonl"
omissoes   := "data/" + area + "/possiveis_omissoes.jsonl"
manifesto  := "data/" + area + "/manifesto.jsonl"
adaptador  := "models/lora_treinado"

# Receita padrao
[group('00 AJUDA')]
@default: help

# ============================================================================
# 00 AJUDA
# ============================================================================

# painel de comandos agrupado por fluxo
[group('00 AJUDA')]
@help:
    echo ""
    printf "{{BOLD}}{{CYAN}}+--------------------------------------------------------------------+{{RESET}}\n"
    printf "{{BOLD}}{{CYAN}}|   HARDNESS IA - Assistente Tecnico da Defesa Civil de MG           |{{RESET}}\n"
    printf "{{BOLD}}{{CYAN}}+--------------------------------------------------------------------+{{RESET}}\n"
    printf "  area atual: {{BOLD}}{{area}}{{RESET}}  {{GRAY}}(docs/{{area}}/ e data/{{area}}/ -- troque com: just area=Geologia <comando>){{RESET}}\n"
    echo ""
    printf "{{BOLD}}AMBIENTE (checar antes de rodar qualquer coisa pesada):{{RESET}}\n"
    printf "  {{CYAN}}%-20s{{RESET}} %s\n" "doctor" "diagnostico completo: GPU, versoes, artefatos, OCR"
    printf "  {{CYAN}}%-20s{{RESET}} %s\n" "gpu" "a T1000 esta visivel? o que ela suporta?"
    printf "  {{CYAN}}%-20s{{RESET}} %s\n" "deps" "versoes do stack (o que costuma quebrar a API)"
    printf "  {{CYAN}}%-20s{{RESET}} %s\n" "tesseract" "o OCR esta disponivel? (laudo digitalizado depende dele)"
    echo ""
    printf "{{BOLD}}INGESTAO - laudos viram limiares revisados:{{RESET}}\n"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "docs-status" "quantos PDF/DOCX esperam em docs/<area>/"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "extrair-texto" "etapa 03: docs/<area>/ -> chunks com procedencia"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "extrair-regras" "etapa 04: chunks -> regras (Qwen 7B local, LENTO)"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "importar-ialc PLAN" "etapa 06: IALC -> regras por municipio (sem GPU)"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "revisar" "etapa 05: sobe a fila de revisao em http://127.0.0.1:8100"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "ingestao" "esteira completa: extrai texto, extrai regras e abre a revisao"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "chunks-stats" "o que a etapa 03 produziu, por documento"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "regras-stats" "o que a etapa 04 propos, e quantas suspeitas"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "omissoes-stats" "chunks com padrao de limiar e zero regras"
    printf "  {{GREEN}}%-20s{{RESET}} %s\n" "manifesto-stats" "estado de cada documento ja processado"
    echo ""
    printf "{{BOLD}}TREINO - limiares viram adaptador LoRA (QLoRA 4-bit na T1000):{{RESET}}\n"
    printf "  {{YELLOW}}%-20s{{RESET}} %s\n" "dataset" "etapa 01: gera data/<area>/dataset_treino.jsonl"
    printf "  {{YELLOW}}%-20s{{RESET}} %s\n" "dataset-stats" "quantos exemplos existem hoje"
    printf "  {{YELLOW}}%-20s{{RESET}} %s\n" "train" "etapa 02: treina o adaptador (bf16, NAO troque)"
    printf "  {{YELLOW}}%-20s{{RESET}} %s\n" "all" "dataset + train em sequencia"
    printf "  {{YELLOW}}%-20s{{RESET}} %s\n" "adapter" "mostra o adaptador salvo"
    printf "  {{YELLOW}}%-20s{{RESET}} %s\n" "vram" "acompanha VRAM durante o treino (Ctrl+C sai)"
    echo ""
    printf "{{BOLD}}TESTES:{{RESET}}\n"
    printf "  {{BLUE}}%-20s{{RESET}} %s\n" "test" "suite completa (exclui os marcados gpu)"
    printf "  {{BLUE}}%-20s{{RESET}} %s\n" "test-um FILTRO" "so os testes que casam (ex: just test-um validacao)"
    printf "  {{BLUE}}%-20s{{RESET}} %s\n" "test-gpu" "os que exigem GPU e modelo baixado (LENTO)"
    echo ""
    printf "{{BOLD}}{{RED}}LIMPEZA (destrutivo, pede confirmacao):{{RESET}}\n"
    printf "  {{RED}}%-20s{{RESET}} %s\n" "clean-adapter" "apaga o adaptador treinado"
    printf "  {{RED}}%-20s{{RESET}} %s\n" "clean-ingestao" "apaga chunks e propostas (PRESERVA decisoes)"
    echo ""
    printf "{{GRAY}}Etapa 06 (carga PostGIS) bloqueada: depende do schema das camadas da Cedec.{{RESET}}\n"
    printf "{{GRAY}}Detalhes em README.md e docs/superpowers/specs/{{RESET}}\n"
    echo ""

# ============================================================================
# 01 AMBIENTE
# ============================================================================

# diagnostico completo do ambiente e dos artefatos
[group('01 AMBIENTE')]
@doctor:
    printf "{{BOLD}}{{CYAN}}== GPU =={{RESET}}\n"
    just gpu || printf "{{RED}}GPU indisponivel{{RESET}}\n"
    printf "\n{{BOLD}}{{CYAN}}== VERSOES =={{RESET}}\n"
    just deps
    printf "\n{{BOLD}}{{CYAN}}== OCR =={{RESET}}\n"
    just tesseract
    printf "\n{{BOLD}}{{CYAN}}== ARTEFATOS =={{RESET}}\n"
    just artefatos

# checa se a T1000 esta visivel e o que ela suporta
[group('01 AMBIENTE')]
@gpu:
    {{python}} -c "import torch; c=torch.cuda.get_device_capability(0); print('GPU:', torch.cuda.get_device_name(0)); print('compute capability:', c); print('VRAM total:', round(torch.cuda.get_device_properties(0).total_memory/1024**3,1), 'GB'); print('fp16 tensor cores:', c >= (7,0)); print('bf16 nativo:', c >= (8,0), '(abaixo de 8.0 o PyTorch emula, e ainda assim ganha aqui)')"

# versoes do stack (o que costuma quebrar a API entre releases)
[group('01 AMBIENTE')]
@deps:
    {{python}} scripts/status.py versoes

# o Tesseract existe? sem ele, laudo digitalizado nao e lido
[group('01 AMBIENTE')]
@tesseract:
    if command -v tesseract >/dev/null 2>&1; then printf "{{GREEN}}disponivel:{{RESET}} %s\n" "$(tesseract --version 2>&1 | head -1)"; else printf "{{YELLOW}}AUSENTE.{{RESET}} PDF sem camada de texto fica retido como 'sem_camada_texto'.\n         Laudo digitalizado NAO sera lido. Ver Pendencias no README.\n"; fi

# inventario dos artefatos da esteira e do treino
[group('01 AMBIENTE')]
@artefatos:
    {{python}} scripts/status.py artefatos

# ============================================================================
# 02 INGESTAO
# ============================================================================

# quantos PDF/DOCX esperam processamento em docs/
[group('02 INGESTAO')]
@docs-status:
    {{python}} scripts/status.py docs

# etapa 03: extrai texto e chunks dos documentos em docs/
[group('02 INGESTAO')]
extrair-texto:
    {{python}} scripts/03_extrair_texto.py

# etapa 04: extrai as regras dos chunks com o Qwen 7B local (LENTO, em lote)
[group('02 INGESTAO')]
extrair-regras:
    {{python}} scripts/04_extrair_regras.py

# etapa 05: sobe a fila de revisao em http://127.0.0.1:8100
[group('02 INGESTAO')]
revisar:
    {{python}} scripts/05_revisar.py

# etapa 06: importa o IALC (limiar de chuva por municipio) para a fila de revisao, sem GPU
# ex.: just importar-ialc "C:/Users/x24679188/Documents/GEOPROCESSAMENTO/IALCxlsx 1.xlsx" --municipio Ipatinga
[group('02 INGESTAO')]
importar-ialc PLANILHA *ARGS:
    {{python}} scripts/06_importar_ialc.py "{{PLANILHA}}" {{ARGS}}

# esteira completa: extrai texto, extrai regras e abre a revisao
[group('02 INGESTAO')]
ingestao: extrair-texto extrair-regras revisar

# o que a etapa 03 produziu, por documento
[group('02 INGESTAO')]
@chunks-stats:
    {{python}} scripts/status.py chunks

# o que a etapa 04 propos, e quantas caíram como suspeitas
[group('02 INGESTAO')]
@regras-stats:
    {{python}} scripts/status.py regras

# chunks com padrao de limiar que produziram zero regras (possivel omissao)
[group('02 INGESTAO')]
@omissoes-stats:
    {{python}} scripts/status.py omissoes

# estado de cada documento ja processado pela etapa 03
[group('02 INGESTAO')]
@manifesto-stats:
    {{python}} scripts/status.py manifesto

# ============================================================================
# 03 TREINO
# ============================================================================

# etapa 01: gera o dataset_treino.jsonl a partir das regras dos especialistas
[group('03 TREINO')]
dataset:
    {{python}} scripts/01.gerar_dataset.py

# quantos exemplos existem hoje no dataset, e de qual catalogo sairam
[group('03 TREINO')]
@dataset-stats:
    {{python}} scripts/status.py dataset

# etapa 02: treina o adaptador LoRA (QLoRA 4-bit) na T1000
[group('03 TREINO')]
train:
    {{python}} scripts/02_treinar_modelo.py

# pipeline de treino completo: dataset + train
[group('03 TREINO')]
all: dataset train

# mostra o adaptador treinado que esta salvo
[group('03 TREINO')]
@adapter:
    if [ -f "{{adaptador}}/adapter_model.safetensors" ]; then printf "{{GREEN}}adaptador em {{adaptador}}{{RESET}}\n"; ls -1 "{{adaptador}}" | while read -r f; do printf "  %-30s %8s\n" "$f" "$(du -h "{{adaptador}}/$f" | cut -f1)"; done; else printf "{{YELLOW}}Nenhum adaptador treinado ainda.{{RESET}} Rode: just train\n"; fi

# acompanha uso de VRAM durante o treino (Ctrl+C para sair)
[group('03 TREINO')]
vram:
    nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv -l 2

# ============================================================================
# 04 TESTES
# ============================================================================

# suite completa (exclui os marcados como gpu)
[group('04 TESTES')]
test:
    {{python}} -m pytest -v

# so os testes cujo nome casa com o filtro (ex: just test-um validacao)
[group('04 TESTES')]
test-um FILTRO:
    {{python}} -m pytest -v -k "{{FILTRO}}"

# os testes que exigem a T1000 e o modelo baixado (LENTO)
[group('04 TESTES')]
test-gpu:
    {{python}} -m pytest -v -m gpu -s

# ============================================================================
# 05 LIMPEZA
# ============================================================================

# apaga o adaptador treinado para comecar do zero
[group('05 LIMPEZA')]
@clean-adapter:
    if [ -d "{{adaptador}}" ]; then read -p "Apagar {{adaptador}}? [s/N] " r; if [ "$r" = "s" ]; then rm -rf "{{adaptador}}"; printf "{{GREEN}}Adaptador removido.{{RESET}}\n"; else printf "Cancelado.\n"; fi; else printf "Nada para limpar.\n"; fi

# apaga chunks e regras propostas para reprocessar. PRESERVA as decisoes humanas.
[group('05 LIMPEZA')]
@clean-ingestao:
    printf "{{YELLOW}}Isto apaga chunks, propostas, omissoes e manifesto.{{RESET}}\n"
    printf "{{GREEN}}As decisoes humanas em {{decisoes}} sao PRESERVADAS.{{RESET}}\n"
    read -p "Confirmar? [s/N] " r; if [ "$r" = "s" ]; then rm -rf "{{chunks_dir}}" "{{propostas}}" "{{omissoes}}" "{{manifesto}}"; printf "{{GREEN}}Artefatos de ingestao removidos.{{RESET}}\n"; else printf "Cancelado.\n"; fi
