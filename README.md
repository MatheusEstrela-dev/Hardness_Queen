# Hardness IA

Assistente tecnico para a Defesa Civil de Minas Gerais. Le laudos e estudos tecnicos
em PDF e Word, extrai os limiares que disparam alerta, e correlaciona hidrologia,
meteorologia e geologia por intersecao geoespacial.

## A decisao que orienta tudo

**O banco decide, o modelo redige.**

Os limiares vivem no PostGIS como dado. A consulta espacial compara o observado
contra o limiar e decide o nivel do alerta. O modelo de linguagem entra depois, so
para transformar a decisao em texto tecnico.

A alternativa — treinar o modelo para decidir o limiar nos proprios pesos — foi
descartada por tres razoes:

1. Um modelo de linguagem nao intersecta poligono. Saber que a Bacia do Rio das
   Velhas corta o poligono de chuva do INMET e uma operacao espacial, nao linguistica.
2. Corrigir um limiar exigiria retreinar o adaptador, contra um `UPDATE`.
3. Alerta de Defesa Civil precisa ser defensavel. Aqui se aponta o documento, a
   pagina, o trecho e o revisor que homologou. Na alternativa, a resposta seria
   apenas "o modelo concluiu".

## Os dois fluxos

```
FLUXO A -- ingestao (o que alimenta o banco)

  docs/*.pdf                03_extrair_texto.py     data/chunks/*.jsonl
  docs/*.docx        --->    PyMuPDF4LLM       --->  (texto + pagina + secao)
                                                              |
                                                              v
  data/regras_propostas.jsonl   <---   04_extrair_regras.py (Qwen 7B local, JSON restrito)
                |
                v
  05_revisar.py (fila web local)  --->  data/regras_aprovadas.jsonl  --->  06_carregar.py  --->  PostGIS
       conferencia humana                                                   (etapa bloqueada)


FLUXO B -- alerta (o que consome o banco)

  chuva observada --> ST_Intersects contra encostas/bacias --> compara com o limiar
                  --> adaptador LoRA redige o texto do alerta
```

## Estado atual, etapa por etapa

| Etapa | O que faz | Estado |
|---|---|---|
| 01 gerar dataset | gera exemplos de treino a partir de regras deterministicas | funcionando (6 exemplos) |
| 02 treinar modelo | QLoRA 4-bit do Qwen2.5-3B na T1000 | funcionando (adaptador salvo) |
| 03 extrair texto | PDF/DOCX para chunks com procedencia | **implementado e testado** |
| 04 extrair regras | chunks para JSON estruturado via LLM local | em implementacao |
| 05 revisar | fila web local de conferencia humana | em implementacao |
| 06 carregar | carga no PostGIS da Cedec | **bloqueado** (ver Pendencias) |

`33 testes passando`, sem warnings.

## Como rodar

Requer o ambiente virtual em `venv/`. Todo comando usa `venv/Scripts/python.exe` —
nunca o Python global.

Com [just](https://github.com/casey/just) instalado, `just` sozinho lista tudo:

```
just gpu             # a T1000 esta visivel? o que ela suporta?
just deps            # versoes do stack (o que costuma quebrar a API)
just test            # suite de testes
just test-gpu        # inclui os testes que exigem GPU e modelo baixado

just dataset         # etapa 01: gera data/dataset_treino.jsonl
just dataset-stats   # quantos exemplos existem hoje
just train           # etapa 02: treina o adaptador LoRA
just adapter         # mostra o adaptador treinado que esta salvo
just vram            # acompanha uso de VRAM durante o treino

just extrair-texto   # etapa 03: docs/*.pdf -> data/chunks/*.jsonl
```

Sem o `just`, cada receita e uma linha so:

```bash
venv/Scripts/python.exe scripts/03_extrair_texto.py
venv/Scripts/python.exe -m pytest -v
```

## O treino, e por que a configuracao e essa

A T1000 e Turing (compute capability 7.5), com tensor cores fp16 nativos e **sem**
bf16 em hardware. A intuicao diz para usar fp16. A medicao diz o contrario:

| caminho | 20 steps | steps/s | VRAM pico |
|---|---|---|---|
| **bf16** (atual) | 152,6 s | 0,131 | 3,50 GB |
| fp16 + adaptadores fp32 | 460,3 s | 0,043 | 3,52 GB |

bf16 e 3x mais rapido aqui, apesar de ser emulado. A razao: o TRL 1.12 forca os
adaptadores para bf16 em qualquer modelo quantizado, seguindo o paper do QLoRA. Usar
fp16 exige desfazer esse cast (voltar os treinaveis para fp32), e e esse arranjo,
somado ao `paged_adamw_8bit`, que consome o tempo. **Nao troque para fp16** sem medir
de novo.

Versoes travadas por necessidade: `transformers 5.16.1`, `trl 1.12.0`. Existe um
teste (`tests/test_infra.py`) que falha se alguem instalar algo que derrube essas
versoes — o treino depende delas.

## Como a esteira evita numero inventado

Decodificacao restrita a schema garante a **forma** da saida do modelo, nunca a
**verdade**. Um JSON perfeitamente valido pode afirmar 800mm onde o laudo escreveu
80mm. Tres defesas, nesta ordem:

1. **Conferencia por substring.** Cada regra extraida carrega o trecho exato que a
   sustenta. Se esse trecho nao aparece no chunk de origem, a extracao e marcada
   `suspeito` — pega a citacao inventada, que e o erro mais perigoso.
2. **Faixa plausivel por dominio.** Valor fora de faixa razoavel para a grandeza vira
   `suspeito`, nunca descartado: a prioridade e recall, e o humano filtra o excesso.
3. **Conferencia humana obrigatoria.** Nenhum limiar entra em producao sem aprovacao,
   com nome do revisor e timestamp gravados.

Ha ainda uma **rede de recall**: um regex varre os chunks e marca os que contem padrao
de limiar mas produziram zero regras. Sem isso, uma omissao passaria invisivel — ninguem
revisa o que nao apareceu na lista.

Coordenadas nunca sao extraidas pelo modelo. A geometria vem sempre da base
cartografica da Cedec, por `JOIN`. Pedir latitude a um LLM convida o numero inventado,
e um par de coordenadas plausivel parece correto na revisao.

## Pendencias e riscos abertos

**Etapa 06 bloqueada pelo schema da Cedec.** O desenho assume que a camada de encostas
traz o tipo de solo classificado e que as bacias sao identificaveis pelo nome usado nos
laudos. Se a camada nao tiver tipo de solo, o `JOIN` nao tem por onde casar e sera
preciso uma tabela de ponte mantida a mao. Verificar antes de escrever a etapa.

**Tesseract nao esta instalado nesta maquina.** Confirmado em execucao: um PDF sem
camada de texto produz estado `sem_camada_texto` com zero chunks. O comportamento e o
projetado — o documento fica retido, nao sumido — mas **laudo digitalizado nao sera
lido enquanto o Tesseract nao existir**. Num acervo de Defesa Civil, boa parte dos
laudos antigos e imagem.

**Cabimento do Qwen 7B em 4-bit nos 8 GB da T1000** ainda nao foi medido. Estimativa de
~4,5 GB de pesos mais ativacoes indica folga, mas e estimativa. Se nao couber, a
alternativa e o 3B-Instruct.

## Documentacao

- Design: `docs/superpowers/specs/2026-09-08-esteira-ingestao-geoespacial-design.md`
- Plano de implementacao: `docs/superpowers/plans/2026-09-08-esteira-ingestao.md`
