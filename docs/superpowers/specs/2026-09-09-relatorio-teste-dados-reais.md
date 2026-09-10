# Relatorio: teste da esteira com documentos reais da Meteorologia

Data: 2026-09-09
Acervo: `C:\Users\x24679188\Documents\METEOROLOGIA` (87 GB, 56.733 arquivos)
Amostra: 6 documentos normativos, 92 chunks
Modelo: Qwen2.5-7B-Instruct, 4-bit NF4, NVIDIA T1000 8GB

## Resumo

A esteira foi confrontada pela primeira vez com documentos reais. Ate entao ela
tinha sido validada apenas contra exemplos sinteticos que eu mesmo escrevi — e que,
por construcao, cabiam no schema. **Sete pressupostos meus cairam.** Nenhum deles
apareceria com dado sintetico.

O resultado numerico final: **21 de 81 regras propostas (26%) sao sustentadas pelo
trecho que citam.** As demais ficam marcadas `suspeito` e vao para conferencia humana.

## Comparacao entre as tres execucoes

| | 1a execucao | 2a (teto 250) | 3a (checagens novas) |
|---|---|---|---|
| regras propostas | 100 | 81 | 81 |
| sustentadas | 11 | 23 | **21** |
| taxa | 11% | 28% | **26%** |
| falhas | 2 | 2 | 2 |
| chunks pulados sem GPU | 64 | 64 | 64 |

A leitura importante nao e o 26%. E que **o 11% inicial era diagnostico contaminado**:
metade das reprovacoes vinha de um parametro meu mal calibrado, nao de falha do modelo.
E a queda de 23 para 21 na terceira execucao e ganho, nao perda — as duas regras que
sairam eram defeituosas de um jeito que nenhuma checagem anterior pegava.

## O que os dados reais quebraram

**1. O contrato nao representava os protocolos.** Eu modelava dois niveis de alerta;
a Instrucao Normativa de MG define cinco, por cor. Modelava valor unico; os documentos
declaram faixas ("entre 6 mm e 30 mm"). Faltavam vento, VIL, refletividade e temperatura
de topo, todos citados nos POPs.

**2. Existem duas classificacoes distintas, nao uma.** Intensidade (`fraca` a `extremo`,
em mm/h) descreve o fenomeno; nivel de alerta (`verde` a `roxo`, em mm acumulados) decide
a resposta. Elas compartilham as mesmas faixas numericas porque a Cedec derivou uma da
outra — e sem separa-las o sistema misturaria descricao com decisao. Campo `escala`
resolveu, com validador impedindo que um nivel de uma escala apareca na outra.

**3. Prompt inflado destroi a extracao.** Uma versao com 3.370 caracteres de instrucao
antes do texto fez o modelo devolver lista vazia em 33s num chunk que declara cinco
niveis. Prompt curto, com o texto ANTES da instrucao: 4 regras corretas. Cada
esclarecimento adicionado compete com o documento pela atencao do modelo.

**4. A defesa acusava inocente.** `normalizar()` trocava marcacao markdown por espaco,
inserindo espaco que a citacao limpa do modelo nao tem (`continuas , com` contra
`continuas, com`). Toda extracao correta era reprovada. Comparacao por sequencia de
tokens resolveu sem reabrir a porta para casamento falso.

**5. A defesa aprovava fabricacao plausivel.** Este foi o mais grave. Auditoria manual
de 27 regras mostrou que apenas 4 tinham seus numeros no trecho citado. O modelo citava
texto REAL mas sem numero — o titulo do documento, prosa sobre severidade — e as duas
checagens existentes aprovavam, porque o texto existia e o valor era plausivel.
Correcao: cada extremo da faixa tem de aparecer como numero no trecho citado.

**6. O `.docx` perdia estrutura em dois niveis.** Virava bloco unico de 21k caracteres
sem secao, o que causava OOM na GPU e deixava a regra sem localizador de origem. E as
**tabelas eram descartadas em silencio** — `document.paragraphs` do python-docx nao
inclui conteudo de tabela. Perdiamos a tabela de intensidade que e a fonte de autoridade
das faixas genuinas.

**7. Meu teto de citacao estava calibrado em dois exemplos.** Fixei 100 caracteres
medindo duas frases de 46 e 68. A mediana real das frases com limiar neste acervo e
**124**, e 100 cobria so 35% delas. A gramatica truncava a citacao ANTES dos numeros e
a checagem reprovava extracao correta: **44 das 89 suspeitas eram esse falso positivo.**

## Defeitos que sobreviveram a todas as checagens ate hoje

Encontrados na auditoria final, ja corrigidos:

**Taxa confundida com acumulado.** "60 mm em 24 horas" virou `taxa_precipitacao` de
60 mm/h com janela 24. Sao coisas diferentes por um fator de 24. Codificada assim, a
regra **praticamente nunca dispara** — 60 mm/h e chuva torrencial. Num sistema de alerta,
silencio e o pior modo de falha.

**Faixa degenerada.** "superiores a 90 mm" virou `valor_min=90` E `valor_max=90`, ou
seja "exatamente 90" em vez de "acima de 90". Mesma consequencia: alerta mudo.

As duas passavam pelas tres defesas porque o numero **estava** no trecho e **era**
plausivel. As defesas verificavam que o numero e real, nao que a semantica esta certa.
Agora ha duas checagens novas para isso.

## O que funciona bem

**O parser deterministico de tabelas.** Le a tabela de intensidade completa — cinco
faixas, incluindo `fraca` e `extremo`, que o modelo perdia — com acerto total, sem GPU,
em milissegundos. E ignorou corretamente 27 linhas de tabelas de dados historicos, sem
gerar uma regra falsa.

**O filtro de padrao.** 64 dos 92 chunks nao tem numero com unidade e nao podem conter
limiar. Pula-los economiza ~75% do tempo de GPU sem perder nada que o modelo fosse achar.

**A conferencia de numero no trecho.** E o que separa extracao sustentada de fabricacao
plausivel, e foi ela que tornou esta auditoria possivel.

**A procedencia.** Documento, pagina e secao nunca passam pelo modelo — sao anexados
pelo script a partir do chunk. Toda regra aprovada leva de volta a origem.

## Limites conhecidos

**O modelo nao e confiavel extraindo numero de prosa.** 26% de sustentacao. Ele acerta
quando rotulo e numero estao na mesma frase e fabrica quando estao separados. A
conferencia de numero filtra exatamente nessa linha, mas o custo e que o revisor humano
recebe 60 suspeitas para 21 sustentadas.

**O acervo completo nao e viavel nesta forma.** 150s por chunk. Os 2.348 documentos do
acervo levariam meses.

**Tesseract ausente.** Laudo digitalizado nao e lido; fica retido como `sem_camada_texto`.

**Sete faixas de plausibilidade ainda sao chute meu** — so `taxa_precipitacao` foi
calibrada com fonte (recorde mundial de 401,7 mm/h, OMM). `chuva_acumulada` e `cota` sao
as que mais aparecem e as que eu calibraria primeiro, com dado do INMET e da ANA.

## Proximos passos, em ordem de valor

1. **Levantar o schema das camadas da Cedec.** Destrava a etapa 06 e fecha o ciclo ate o
   alerta. E a unica pendencia que depende de informacao que so a equipe tem.
2. **Revisar uma amostra pequena com quem conhece o dominio.** Dez ou quinze regras, nao
   para aprovar, mas para dizer se o que o modelo propoe faz sentido. Vale mais que
   auditoria automatica.
3. **Corrigir a duplicacao de aprovacao na tela de revisao.** Segurar a tecla `A` dispara
   dois POSTs e pula uma regra. Num portao humano isso e serio.
4. **Calibrar as faixas de plausibilidade restantes** com dado historico.

## Estado do codigo

23 commits em `feat/esteira-ingestao`, **199 testes**, publicado em
`github.com/MatheusEstrela-dev/Hardness_Queen`. Nenhum conteudo dos laudos foi versionado:
documentos, chunks e regras extraidas estao todos no `.gitignore`.
