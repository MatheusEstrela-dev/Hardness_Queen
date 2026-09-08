# Esteira de Ingestao Documental com Enriquecimento Geoespacial

Data: 2026-09-08
Projeto: Hardness_IA
Status: design aprovado, pendente plano de implementacao

## 1. Problema

Os limiares tecnicos que disparam alertas da Defesa Civil estao hoje escritos em laudos e estudos em PDF e Word, e replicados a mao no dicionario `REGRAS` no topo de `scripts/01.gerar_dataset.py`. Nao ha rastreabilidade entre o alerta emitido e o documento que fixou o limiar, e qualquer mudanca normativa exige editar codigo.

O objetivo e uma esteira que leia esses documentos, extraia os limiares como dado estruturado, submeta-os a conferencia humana, e os carregue na base geoespacial da Cedec, onde passam a ser correlacionaveis por intersecao fisica entre os tres dominios: hidrologia, meteorologia e geologia.

## 2. Decisao de arquitetura

**O banco decide, o modelo redige.**

O PostGIS guarda geometrias e limiares como dados. A consulta espacial compara o observado contra o limiar e decide o nivel do alerta. O adaptador LoRA treinado em `scripts/02_treinar_modelo.py` recebe a decisao e produz o texto tecnico.

Alternativa descartada: treinar o modelo para decidir o limiar nos proprios pesos. Foi descartada por tres razoes, em ordem de peso:

1. Um modelo de linguagem nao intersecta poligono. A correlacao entre os tres dominios que motiva o projeto e uma operacao espacial (`ST_Intersects`), e nao existe forma de um LLM saber que a bacia corta o poligono de chuva do INMET a menos que alguem ja tenha calculado isso.
2. Corrigir um limiar exigiria retreinar o adaptador, contra um `UPDATE`.
3. Alerta de Defesa Civil precisa ser defensavel. O desenho escolhido permite apontar documento, pagina, trecho e revisor. O descartado responde apenas que "o modelo concluiu".

## 3. Escopo da versao 1

Dentro: extracao de **regras normativas** (limiares) de PDF e Word, conferencia humana, e carga na base da Cedec.

Fora: ocorrencias historicas (eventos passados com data e local), que tem natureza de dado distinta -- regra nao tem data, ocorrencia nao tem limiar -- e entram em tabela propria numa versao posterior sem alterar o que esta aqui.

Pressuposto confirmado: as camadas geograficas (encostas mapeadas, bacias, limites municipais) ja existem em base acessivel da Defesa Civil. A esteira consome essas geometrias, nao as produz.

## 4. Contrato de dados

Objeto unico que toda a esteira serve:

```json
{
  "dominio": "geologia",
  "entidade_tipo": "tipo_solo",
  "entidade_nome": "gnaisse",
  "grandeza": "chuva_acumulada",
  "janela_horas": 72,
  "unidade": "mm",
  "nivel": "critico",
  "valor": 100.0,
  "fonte_doc": "laudo_morro_papagaio.pdf",
  "fonte_pagina": 12,
  "fonte_secao": "4.2 Caracterizacao do solo",
  "fonte_trecho": "a saturacao do solo gnaisse ocorre a partir de 100mm em 72h"
}
```

Decisoes de modelagem:

- **`entidade_tipo` + `entidade_nome` sao a chave de join** com a base da Cedec, e substituem a etapa de geocoding. A regra se prende a uma *classe* de entidade, nao a uma feicao especifica: um laudo sobre solo gnaisse cobre todas as encostas com esse solo. Se a regra se prendesse a geometria, cada encosta precisaria do seu proprio laudo.
- **Nao existe campo de coordenadas.** Pedir latitude e longitude ao modelo convida o numero inventado, e um par de coordenadas plausivel parece correto na revisao. A geometria vem sempre da base da Cedec, via join.
- **`fonte_pagina` e nulavel**, acompanhado de `fonte_secao`. Arquivos `.docx` nao tem paginacao fixa; quem pagina e o renderizador. Sem o campo alternativo, os documentos Word entrariam sem rastreabilidade, anulando o proposito do campo.
- **`fonte_trecho` e obrigatorio.** Serve a revisao humana e a conferencia automatica descrita na secao 6.

## 5. Etapa 03 -- extracao de texto e chunking

Script: `scripts/03_extrair_texto.py`
Entrada: `docs/*.pdf`, `docs/*.docx`
Saida: `data/chunks/<doc>.jsonl`

Biblioteca: **PyMuPDF4LLM** para PDF, `python-docx` para Word.

```python
chunks = pymupdf4llm.to_markdown(caminho, page_chunks=True)
# chunk: {"metadata": {"page": 12, ...}, "text": "## Titulo...", "tables": [...], "toc_items": [...]}
```

O `page_chunks=True` entrega tres coisas necessarias sem codigo adicional:

- **Numero de pagina nativo** em `metadata.page`, alimentando `fonte_pagina`.
- **Tabelas convertidas em Markdown.** Critico: laudo tecnico coloca limiar em tabela, e extracao de texto crua produz `gnaisse 100 argiloso 80 arenoso 60`, uma sequencia de numeros orfaos onde nenhum extrator consegue associar valor a entidade. Em Markdown as colunas chegam intactas.
- **OCR automatico** em paginas sem camada de texto, necessario porque laudo antigo digitalizado e imagem e produziria zero regras em silencio.

**Estrategia de chunking:** a pagina e a unidade base, e cada chunk carrega o titulo da secao vindo de `toc_items`. O motivo e concreto: o nome da entidade aparece no subtitulo ("4.2 Caracterizacao do solo gnaisse") e o numero aparece paragrafos depois. Sem o cabecalho no chunk, o extrator nao tem como preencher `entidade_nome` e devolve nulo ou chuta. O contexto de 32k do Qwen2.5 acomoda a pagina inteira, logo nao ha necessidade de fatiar mais fino.

**Estado explicito por documento**, gravado no manifesto da etapa: `texto_nativo`, `ocr_aplicado`, `sem_camada_texto`. Isto existe porque zero regras extraidas e indistinguivel de "documento sem regras": um laudo digitalizado que falhou parece identico a um laudo que legitimamente nao fixa limiar. O relatorio final da etapa reporta a contagem por estado.

Idempotencia: hash do arquivo de origem; documento inalterado nao e reprocessado.

## 6. Etapa 04 -- extracao das regras

Script: `scripts/04_extrair_regras.py`
Entrada: `data/chunks/<doc>.jsonl`
Saida: `data/regras_propostas.jsonl`

Modelo: **Qwen2.5-7B-Instruct em 4-bit**, local. Nenhum conteudo de laudo sai da rede corporativa. Roda em lote, sem usuario esperando, logo pode ser lento. Aqui nao ha treino: e inferencia quantizada, nao QLoRA.

O modelo base `Qwen/Qwen2.5-3B` usado no treino do LoRA nao serve para esta etapa: modelo cru, sem fine-tuning, obedece mal a instrucao de formato.

**JSON garantido por decodificacao restrita**, via `outlines` sobre o modelo `transformers` quantizado:

```python
class Regra(BaseModel):
    dominio: Literal["geologia", "hidrologia", "meteorologia"]
    entidade_tipo: Literal["tipo_solo", "bacia", "estacao", "municipio"]
    entidade_nome: str
    grandeza: Literal["chuva_acumulada", "cota", "vazao"]
    janela_horas: int | None
    unidade: Literal["mm", "m", "m3/s"]
    nivel: Literal["atencao", "critico"]
    valor: float
    fonte_trecho: str

class Extracao(BaseModel):
    regras: conlist(Regra, min_length=0)
```

O schema declara deliberadamente menos campos que o contrato da secao 4: o modelo produz apenas os campos analiticos mais o `fonte_trecho`, e o script anexa `fonte_doc`, `fonte_pagina` e `fonte_secao` a partir dos metadados do chunk. Alem de reduzir o que o modelo tem de acertar, isso torna impossivel atribuir a regra ao documento ou a pagina errada, porque essa informacao nunca passa pelo modelo.

A cada token, os que produziriam JSON invalido sao eliminados antes da amostragem. JSON valido deixa de ser um pedido no prompt e passa a ser propriedade estrutural. Os `Literal` eliminam o trabalho de normalizacao posterior: `"Geologia"`, `"geologia "` e `"GEO"` nao sao geraveis. O `min_length=0` permite que um chunk sem regras devolva lista vazia legitimamente.

**O que a restricao nao resolve:** ela garante a forma, nao a verdade. Um JSON valido pode afirmar `valor: 800` onde o laudo escreveu 80. Duas defesas:

1. **Conferencia por substring.** Se o `fonte_trecho` citado nao aparece no chunk de origem (comparacao normalizada para espacos e markdown), a extracao e marcada `suspeito`. Pega justamente a classe de erro mais perigosa, a citacao inventada.
2. **Faixa plausivel por dominio.** Valor fora de faixa razoavel para a grandeza e marcado `suspeito`, nunca descartado -- a prioridade e recall, e o portao humano filtra o excesso.

**Decodificacao greedy, temperatura 0.** Nao por qualidade, mas por reprodutibilidade: a revisao humana e caro, e se reexecutar produzisse conjunto diferente de regras, as aprovacoes anteriores ficariam orfas sem sinal algum.

**Rede de recall.** O risco de um 7B e omitir regra, e o portao humano nao pega omissao, porque ninguem revisa o que nao apareceu na lista. Um regex de padrao de limiar varre os chunks e marca os que contem tal padrao mas produziram zero regras. Esses entram na revisao como possivel omissao.

Retomavel por `chunk_id`: esta e a etapa lenta, e uma reinicializacao nao pode custar horas de GPU. Tempo por chunk sera medido na implementacao, nao estimado aqui.

## 7. Etapa 05 -- conferencia humana

Script: `scripts/05_revisar.py`
Entrada: `data/regras_propostas.jsonl`
Saida: `data/decisoes.jsonl` (acumulativo), `data/regras_aprovadas.jsonl`

Aplicacao web local: FastAPI servindo pagina unica, presa em `127.0.0.1`, sem autenticacao e sem banco. Dois endpoints: `GET /` para a fila de pendentes e `POST /decisao`. Dependencias novas: `fastapi`, `uvicorn`.

A tela apresenta o `fonte_trecho` em destaque com o numero realcado, e os campos extraidos ao lado. **A evidencia vem antes da conclusao da maquina**: na ordem inversa o revisor tende a confirmar o numero que ja esta na tela, e um portao que so confirma nao e portao.

Teclado: `A` aprova, `R` rejeita, `C` abre o campo de correcao do valor. Capturar a correcao, e nao apenas o veredito, tem valor duplo -- entra a regra certa no banco, e acumula-se um registro de onde o extrator erra, insumo para calibrar o prompt da etapa 04.

Sem login, o revisor se identifica ao abrir a sessao; nome e timestamp vao para cada decisao. Essa trilha e o que sustenta a defensabilidade que fundamentou a escolha da arquitetura.

Cada regra tem um `regra_id` estavel (hash de documento, pagina, chunk e campos extraidos). A fila leva somente regra ainda pendente: sem isso, cada nova leva de documentos faz o revisor reavaliar tudo desde o inicio, e ele abandona a ferramenta.

## 8. Etapa 06 -- carga na base da Cedec

Script: `scripts/06_carregar.py`
Entrada: `data/regras_aprovadas.jsonl`
Saida: tabela `regra_limiar` na base PostGIS da Defesa Civil

```sql
regra_limiar(
  id, dominio, entidade_tipo, entidade_nome, grandeza,
  janela_horas, unidade, nivel, valor,
  fonte_doc, fonte_pagina, fonte_secao, fonte_trecho,
  revisado_por, revisado_em,
  vigente_desde, vigente_ate
)
```

A tabela nao tem geometria: a regra pertence a uma classe de entidade, e a geometria vive nas camadas da Cedec.

**A carga nunca faz UPDATE nem DELETE.** Um laudo novo que revisa o limiar do gnaisse de 100 para 90 fecha a vigencia da linha anterior (`vigente_ate`) e insere uma nova. E o que permite responder qual limiar estava valendo na data de um desastre -- pergunta que, num orgao de Defesa Civil, sera feita, e provavelmente com advogado presente.

## 9. Runtime

A decisao do alerta e uma consulta espacial, sem participacao do modelo:

```sql
SELECT e.nome, r.nivel, r.valor, obs.acumulado_72h
FROM chuva_observada obs
JOIN encostas_cedec e ON ST_Intersects(obs.geom, e.geom)
JOIN regra_limiar r ON r.entidade_tipo = 'tipo_solo'
                   AND r.entidade_nome = e.tipo_solo
                   AND r.vigente_ate IS NULL
WHERE obs.acumulado_72h >= r.valor;
```

Cada linha resultante e um alerta a ser redigido, e e nesse ponto -- e apenas nesse -- que o adaptador LoRA atua: recebe os campos e produz o texto tecnico, no mesmo formato dos exemplos que `scripts/01.gerar_dataset.py` gera hoje.

**Consequencia de projeto:** o dicionario `REGRAS` hardcoded em `scripts/01.gerar_dataset.py` passa a ser lido de `regra_limiar`. O gerador de dataset de treino e o motor de alertas passam a beber da mesma fonte, garantindo que o modelo seja sempre treinado com os limiares vigentes em producao.

## 10. Riscos e dependencias abertas

**Schema da base da Cedec (bloqueia a etapa 06).** O desenho assume que a camada de encostas traz o tipo de solo classificado e que as bacias sao identificaveis pelo nome usado nos laudos. Se a camada nao tiver tipo de solo, o join nao tem por onde casar e sera necessaria uma tabela de ponte mantida a mao. Verificar o schema real antes de escrever a etapa 06. As etapas 03 a 05 nao dependem disso e podem ser construidas antes.

**Tesseract para OCR (degrada a etapa 03).** O OCR do PyMuPDF depende do Tesseract instalado, o que numa estacao corporativa pode nao existir nem ser instalavel. Se faltar, o desenho permanece correto: o documento fica retido com estado `sem_camada_texto` em vez de produzir silenciosamente zero regras.

**Cabimento do 7B em 4-bit nos 8GB da T1000.** Estimativa de cerca de 4,5 GB de pesos mais ativacoes de chunk curto indica folga, mas precisa ser medido. Se nao couber, a alternativa e o 3B-Instruct, com perda de precisao absorvida em parte pelo portao humano.

**Vocabulario dos `Literal`.** As listas de `entidade_tipo` e `grandeza` foram derivadas do dicionario `REGRAS` atual e dos exemplos discutidos. Laudos reais podem trazer grandeza fora dessas listas, e nesse caso a decodificacao restrita forcara o modelo ao valor mais proximo em vez de sinalizar o desconhecido. Mitigacao: revisar as listas contra uma amostra real de documentos antes de processar o acervo inteiro.

## 11. Criterios de verificacao

- Um PDF com tabela de limiares produz uma regra por linha da tabela, com `entidade_nome` correto para cada valor.
- Um PDF digitalizado sem Tesseract disponivel resulta em documento com estado `sem_camada_texto` no relatorio, e nao em zero regras silencioso.
- Um `.docx` produz regras com `fonte_pagina` nulo e `fonte_secao` preenchido.
- Uma extracao cujo `fonte_trecho` nao existe no chunk de origem chega a revisao com status `suspeito`.
- Um chunk contendo padrao de limiar que produziu zero regras aparece na revisao como possivel omissao.
- Reexecutar a etapa 04 sobre os mesmos chunks produz `regra_id` identicos, e decisoes ja registradas nao reaparecem na fila de revisao.
- Carregar um limiar revisado para a mesma entidade fecha `vigente_ate` da linha anterior e mantem as duas linhas na tabela.
