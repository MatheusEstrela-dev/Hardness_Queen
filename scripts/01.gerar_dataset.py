import json
import sqlite3
import os

# ==========================================
# 1. LIVRO DE REGRAS (Extraído dos PDFs/Word)
# ==========================================
REGRAS = {
    "meteorologia": {
        "atencao_24h": 50.0,
        "critico_24h": 80.0
    },
    "hidrologia": {
        "rio_das_velhas": {"alerta": 4.0, "transbordamento": 5.0},
        "rio_arrudas": {"alerta": 2.5, "transbordamento": 3.8}
    },
    "geologia": {
        "solo_gnaisse": {"acumulado_72h_critico": 100.0},
        "solo_argiloso": {"acumulado_72h_critico": 80.0}
    }
}

# ==========================================
# 2. FUNÇÕES ESPECIALISTAS (O Raciocínio)
# ==========================================
def analise_meteorologica(estacao, chuva_1h, chuva_24h):
    limiar_atencao = REGRAS["meteorologia"]["atencao_24h"]
    limiar_critico = REGRAS["meteorologia"]["critico_24h"]
    
    if chuva_24h >= limiar_critico:
        return f"CRÍTICO: A estação {estacao} registrou {chuva_24h}mm em 24h, superando o limiar crítico ({limiar_critico}mm). Chuva na última hora: {chuva_1h}mm. Recomenda-se emissão imediata de alerta vermelho."
    elif chuva_24h >= limiar_atencao:
        return f"ATENÇÃO: A estação {estacao} registrou {chuva_24h}mm em 24h, superando o limiar de atenção ({limiar_atencao}mm). Manter monitoramento contínuo."
    return f"NORMAL: Acumulado de {chuva_24h}mm em 24h na estação {estacao} está dentro da normalidade."

def analise_hidrologica(bacia, cota_atual):
    chave = bacia.lower().replace(" ", "_")
    limiares = REGRAS["hidrologia"].get(chave)
    
    if not limiares:
        return f"Dados da bacia {bacia} não parametrizados."
        
    if cota_atual >= limiares["transbordamento"]:
        return f"EMERGÊNCIA: Cota do {bacia} atingiu {cota_atual}m, superando o limite de transbordamento ({limiares['transbordamento']}m). Iniciar protocolo de evacuação da calha."
    elif cota_atual >= limiares["alerta"]:
        return f"ALERTA HIDROLÓGICO: Cota do {bacia} em {cota_atual}m. O limiar de alerta ({limiares['alerta']}m) foi ultrapassado."
    return f"NORMAL: Cota do {bacia} em {cota_atual}m, capacidade operacional mantida."

def analise_geologica(regiao, tipo_solo, acumulado_72h):
    chave_solo = tipo_solo.lower().replace(" ", "_")
    limiar = REGRAS["geologia"].get(chave_solo)
    
    if not limiar:
        return "Tipo de solo não mapeado nos estudos geológicos."
        
    if acumulado_72h >= limiar["acumulado_72h_critico"]:
        return f"ALTO RISCO GEOLÓGICO: Na região {regiao}, o acumulado de {acumulado_72h}mm em 72h superou o limite crítico de {limiar['acumulado_72h_critico']}mm para {tipo_solo}. Saturação severa do perfil. Recomenda-se vistoria imediata para risco de movimento de massa."
    return f"RISCO BAIXO: Acumulado de {acumulado_72h}mm em 72h na região {regiao} não atinge saturação crítica para {tipo_solo}."

# ==========================================
# 3. SIMULAÇÃO DO BANCO DE DADOS (Produção)
# ==========================================
def configurar_banco_mock():
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE telemetria (
            id INTEGER PRIMARY KEY, dominio TEXT, local TEXT, 
            parametro_1 REAL, parametro_2 TEXT
        )
    """)
    
    # Injetando dados reais x regras
    dados_mock = [
        # Meteorologia: chuva_1h, chuva_24h
        ("meteorologia", "A521-BH", 15.0, "85.0"), 
        ("meteorologia", "A522-Contagem", 2.0, "30.0"),
        # Hidrologia: cota_atual, null
        ("hidrologia", "Rio das Velhas", 5.2, "0.0"), 
        ("hidrologia", "Rio Arrudas", 2.6, "0.0"),
        # Geologia: acumulado_72h, tipo_solo
        ("geologia", "Encosta Norte", 110.0, "solo gnaisse"),
        ("geologia", "Setor Sul", 60.0, "solo argiloso")
    ]
    
    cursor.executemany("INSERT INTO telemetria (dominio, local, parametro_1, parametro_2) VALUES (?, ?, ?, ?)", dados_mock)
    return conn

# ==========================================
# 4. GERAÇÃO DO DATASET CHATML
# ==========================================
def gerar_dataset_jsonl(caminho_saida="data/dataset_treino.jsonl"):
    os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
    
    conn = configurar_banco_mock()
    cursor = conn.cursor()
    cursor.execute("SELECT dominio, local, parametro_1, parametro_2 FROM telemetria")
    
    exemplos_gerados = 0
    with open(caminho_saida, "w", encoding="utf-8") as f:
        for linha in cursor.fetchall():
            dominio, local, param1, param2 = linha
            
            if dominio == "meteorologia":
                chuva_1h = param1
                chuva_24h = float(param2)
                prompt_user = f"Estação: {local}. Chuva 1h: {chuva_1h}mm. Acumulado 24h: {chuva_24h}mm. Qual a análise da tendência?"
                resposta_assistente = analise_meteorologica(local, chuva_1h, chuva_24h)
                system_prompt = "Você é um meteorologista sênior analisando dados de estações automáticas."
                
            elif dominio == "hidrologia":
                cota = param1
                prompt_user = f"Bacia: {local}. Cota atual: {cota}m. Faça a avaliação de risco."
                resposta_assistente = analise_hidrologica(local, cota)
                system_prompt = "Você é uma hidróloga sênior analisando o nível de calhas de rios."
                
            elif dominio == "geologia":
                acumulado_72h = param1
                tipo_solo = param2
                prompt_user = f"Região: {local}. Geologia: {tipo_solo}. Acumulado 72h: {acumulado_72h}mm. Atualize o status de risco."
                resposta_assistente = analise_geologica(local, tipo_solo, acumulado_72h)
                system_prompt = "Você é um geólogo especialista em movimentos de massa e estabilidade de encostas."
            
            # Formato Rigoroso ChatML
            exemplo = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_user},
                    {"role": "assistant", "content": resposta_assistente}
                ]
            }
            f.write(json.dumps(exemplo, ensure_ascii=False) + "\n")
            exemplos_gerados += 1
            
    print(f"Sucesso! {exemplos_gerados} exemplos gerados em '{caminho_saida}'.")

if __name__ == "__main__":
    gerar_dataset_jsonl()