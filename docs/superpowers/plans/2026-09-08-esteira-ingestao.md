# Esteira de Ingestao Documental — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ler laudos em PDF e Word, extrair os limiares tecnicos como dado estruturado validado, e submete-los a conferencia humana numa fila web local, deixando um `regras_aprovadas.jsonl` pronto para carga no PostGIS.

**Architecture:** Quatro etapas encadeadas por arquivo, cada uma reexecutavel isoladamente. Os scripts `03` a `05` sao CLIs finas; toda a logica vive no pacote `ingestao/`, testavel sem GPU e sem banco. O extrator recebe o gerador de texto por injecao de dependencia, o que permite testar a orquestracao com um gerador falso e reservar o modelo real para a verificacao final.

**Tech Stack:** Python 3, PyMuPDF4LLM (PDF, tabelas em markdown, OCR automatico), python-docx (Word), outlines 1.3.3 + Pydantic 2 (decodificacao restrita a schema), Qwen2.5-7B-Instruct em 4-bit via transformers + bitsandbytes, FastAPI + uvicorn (fila de revisao), pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-esteira-ingestao-geoespacial-design.md`

## Global Constraints

- Etapa 06 (carga PostGIS) esta FORA deste plano: depende do schema real das camadas da Cedec. O plano entrega ate `data/regras_aprovadas.jsonl`.
- `outlines==1.3.3` instala sem tocar em `transformers`. NAO rodar `pip install -U transformers` nem `trl`: o treino em `scripts/02_treinar_modelo.py` depende de `transformers 5.16.1` + `trl 1.12.0` e do dtype bf16. Qualquer downgrade quebra o treino ja validado.
- Python do projeto: `venv/Scripts/python.exe`. Nunca o Python global.
- Sem emojis dentro do codigo (regra de ouro 2). Gitmoji apenas na mensagem de commit.
- Commits seguem gitmoji: `<emoji> tipo(escopo): descricao curta em pt-BR` (regra 11). Sem trailer `Co-Authored-By`.
- Commits atomizados: os arquivos que entregam UMA mudanca vao juntos, nunca um arquivo por commit (regra 12).
- Interpretacao da regra 10 ("nao subir testes para commit"): ela veta scripts de teste descartaveis criados durante depuracao, nao a suite permanente em `tests/`. A suite entra nos commits porque e o que sustenta o TDD deste plano. **Se a intencao for outra, o autor do plano deve corrigir antes da execucao** — isso altera o passo de commit de todas as tasks.
- Determinismo obrigatorio na etapa 04: `temperature=0`, `seed=42`. A revisao humana e caro e nao pode ser invalidada por reexecucao.
- Nada de conteudo de laudo sai da rede: sem chamada a API externa em nenhuma etapa.

---

## File Structure

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `ingestao/__init__.py` | marcador de pacote, vazio |
| `ingestao/contrato.py` | modelos Pydantic: `RegraExtraida`, `Extracao`, `Chunk`, `Regra`, `Decisao` |
| `ingestao/identidade.py` | geracao determinista de `chunk_id` e `regra_id` |
| `ingestao/persistencia.py` | leitura/escrita jsonl, hash de arquivo, manifesto de documentos |
| `ingestao/extracao_texto.py` | PDF/DOCX para `Chunk`, com estado do documento |
| `ingestao/validacao.py` | conferencia de trecho, faixa plausivel, rede de recall |
| `ingestao/extrator_regras.py` | prompt, orquestracao por chunk, fabrica do gerador Qwen |
| `ingestao/revisao/__init__.py` | marcador de pacote, vazio |
| `ingestao/revisao/app.py` | fabrica `criar_app`, endpoints da fila |
| `ingestao/revisao/index.html` | pagina unica da revisao |
| `scripts/03_extrair_texto.py` | CLI da etapa 03 |
| `scripts/04_extrair_regras.py` | CLI da etapa 04 |
| `scripts/05_revisar.py` | CLI que sobe o uvicorn |
| `tests/test_identidade.py` | determinismo dos ids |
| `tests/test_contrato.py` | validacao dos Literal |
| `tests/test_persistencia.py` | jsonl e idempotencia por hash |
| `tests/test_extracao_texto.py` | paginacao, titulo de secao, docx, sem camada de texto |
| `tests/test_validacao.py` | trecho ausente, faixa, omissao |
| `tests/test_extrator_regras.py` | orquestracao com gerador falso |
| `tests/test_revisao_app.py` | fila, decisao, nao reabrir decidido |
| `pytest.ini` | configuracao do pytest e marcador `gpu` |
| `.gitignore` | venv, models, data, pycache |

**Modificar:**

| Arquivo | Mudanca |
|---|---|
| `Justfile` | receitas `test`, `extrair-texto`, `extrair-regras`, `revisar`, `ingestao` |

---

## Task 1: Repositorio, dependencias e infra de teste

**Files:**
- Create: `.gitignore`, `pytest.ini`, `ingestao/__init__.py`, `tests/test_infra.py`
- Modify: `Justfile`

**Interfaces:**
- Consumes: nada
- Produces: pacote `ingestao` importavel; comando `just test` funcionando; repositorio git inicializado

- [ ] **Step 1: Inicializar o repositorio**

A pasta ainda nao e um repo git. Sem isso nenhum passo de commit deste plano funciona.

```bash
cd /c/Users/x24679188/Documents/Github/Hardness_IA
git init
git branch -M main
```

- [ ] **Step 2: Escrever o .gitignore antes do primeiro add**

Ordem importa: `venv/` tem milhares de arquivos e `models/lora_treinado/` tem 25 MB. Se entrarem no indice, sair depois da trabalho.

```gitignore
venv/
__pycache__/
*.pyc
.pytest_cache/
models/
data/chunks/
data/regras_propostas.jsonl
data/regras_aprovadas.jsonl
data/decisoes.jsonl
data/manifesto.jsonl
docs/*.pdf
docs/*.docx
```

`data/dataset_treino.jsonl` fica versionado de proposito: e gerado por regras deterministicas e serve de referencia.

- [ ] **Step 3: Instalar as dependencias**

```bash
./venv/Scripts/python.exe -m pip install pytest httpx pymupdf4llm python-docx "outlines==1.3.3" fastapi uvicorn
```

Conferir que nada mexeu no stack de treino:

```bash
./venv/Scripts/python.exe -c "import transformers, trl; print(transformers.__version__, trl.__version__)"
```

Esperado: `5.16.1 1.12.0`. Se mudou, desfazer a instalacao e reportar antes de continuar — o treino quebra.

- [ ] **Step 4: Criar o pytest.ini**

```ini
[pytest]
testpaths = tests
markers =
    gpu: exige a T1000 e o modelo Qwen 7B baixado (nao roda por padrao)
addopts = -m "not gpu"
```

O marcador `gpu` existe para a Task 8: teste que carrega um 7B nao pode rodar na suite normal.

- [ ] **Step 5: Escrever o teste de infra**

`tests/test_infra.py`:

```python
def test_pacote_ingestao_importavel():
    import ingestao

    assert ingestao is not None


def test_stack_de_treino_intacto():
    import transformers
    import trl

    assert transformers.__version__.startswith("5.")
    assert trl.__version__.startswith("1.")
```

O segundo teste e uma trava: se alguem instalar algo que faca downgrade do transformers, a suite acusa.

- [ ] **Step 6: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_infra.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao'`.

- [ ] **Step 7: Criar o pacote**

```bash
mkdir -p ingestao tests
touch ingestao/__init__.py
```

`ingestao/__init__.py` fica vazio.

- [ ] **Step 8: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_infra.py -v
```

Esperado: 2 passed.

- [ ] **Step 9: Adicionar a receita de teste no Justfile**

Inserir depois da receita `deps`:

```just
# roda a suite de testes
test:
    {{python}} -m pytest -v

# roda tambem os testes que exigem GPU e modelo baixado
test-gpu:
    {{python}} -m pytest -v -m gpu
```

- [ ] **Step 10: Commit**

```bash
git add .gitignore pytest.ini Justfile ingestao/__init__.py tests/test_infra.py
git commit -m "🔧 config(ingestao): repo, dependencias e infra de teste"
```

---

## Task 2: Contrato de dados e identidade

**Files:**
- Create: `ingestao/contrato.py`, `ingestao/identidade.py`, `tests/test_contrato.py`, `tests/test_identidade.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `contrato.RegraExtraida` — o que o modelo produz (campos analiticos + `fonte_trecho`)
  - `contrato.Extracao` — `regras: list[RegraExtraida]`, aceita lista vazia
  - `contrato.Chunk(chunk_id: str, doc: str, pagina: int | None, secao: str | None, texto: str)`
  - `contrato.Regra` — `RegraExtraida` acrescida de `regra_id`, `chunk_id`, `fonte_doc`, `fonte_pagina`, `fonte_secao`, `status`, `motivo_suspeita`
  - `contrato.Decisao(regra_id: str, veredito: str, valor_corrigido: float | None, revisor: str, decidido_em: str)`
  - `identidade.chunk_id(doc: str, pagina: int | None, texto: str) -> str`
  - `identidade.regra_id(chunk_id: str, entidade_tipo: str, entidade_nome: str, grandeza: str, nivel: str, valor: float) -> str`

- [ ] **Step 1: Escrever os testes de identidade**

`tests/test_identidade.py`:

```python
from ingestao.identidade import chunk_id, regra_id


def test_chunk_id_e_determinista():
    a = chunk_id("laudo.pdf", 12, "texto da pagina")
    b = chunk_id("laudo.pdf", 12, "texto da pagina")

    assert a == b


def test_chunk_id_muda_com_o_texto():
    a = chunk_id("laudo.pdf", 12, "texto original")
    b = chunk_id("laudo.pdf", 12, "texto editado")

    assert a != b


def test_chunk_id_aceita_pagina_nula_do_docx():
    assert chunk_id("laudo.docx", None, "texto") != ""


def test_regra_id_e_determinista():
    args = ("abc123", "tipo_solo", "gnaisse", "chuva_acumulada", "critico", 100.0)

    assert regra_id(*args) == regra_id(*args)


def test_regra_id_muda_com_o_valor():
    base = ("abc123", "tipo_solo", "gnaisse", "chuva_acumulada", "critico")

    assert regra_id(*base, 100.0) != regra_id(*base, 90.0)
```

O ultimo teste fixa uma decisao de projeto: o `regra_id` identifica a PROPOSTA, valor incluido. Correcao do revisor nao muda o id — a correcao vive no registro de decisao, referenciando a proposta original.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_identidade.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.identidade'`.

- [ ] **Step 3: Implementar identidade.py**

```python
import hashlib


def _hash(*partes: object) -> str:
    bruto = "|".join("" if parte is None else str(parte) for parte in partes)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]


def chunk_id(doc: str, pagina: int | None, texto: str) -> str:
    return _hash(doc, pagina, texto)


def regra_id(
    chunk_id: str,
    entidade_tipo: str,
    entidade_nome: str,
    grandeza: str,
    nivel: str,
    valor: float,
) -> str:
    return _hash(chunk_id, entidade_tipo, entidade_nome, grandeza, nivel, valor)
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_identidade.py -v
```

Esperado: 5 passed.

- [ ] **Step 5: Escrever os testes do contrato**

`tests/test_contrato.py`:

```python
import pytest
from pydantic import ValidationError

from ingestao.contrato import Chunk, Extracao, Regra, RegraExtraida


def _regra_valida() -> dict:
    return {
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "nivel": "critico",
        "valor": 100.0,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
    }


def test_regra_extraida_aceita_payload_valido():
    regra = RegraExtraida(**_regra_valida())

    assert regra.valor == 100.0


def test_regra_extraida_rejeita_dominio_desconhecido():
    payload = _regra_valida()
    payload["dominio"] = "meteorologia_marinha"

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_regra_extraida_rejeita_unidade_desconhecida():
    payload = _regra_valida()
    payload["unidade"] = "polegadas"

    with pytest.raises(ValidationError):
        RegraExtraida(**payload)


def test_janela_horas_pode_ser_nula():
    payload = _regra_valida()
    payload["janela_horas"] = None

    assert RegraExtraida(**payload).janela_horas is None


def test_extracao_aceita_lista_vazia():
    assert Extracao(regras=[]).regras == []


def test_regra_carrega_procedencia_e_status():
    regra = Regra(
        **_regra_valida(),
        regra_id="r1",
        chunk_id="c1",
        fonte_doc="laudo.pdf",
        fonte_pagina=12,
        fonte_secao="4.2 Caracterizacao do solo",
        status="ok",
    )

    assert regra.fonte_pagina == 12
    assert regra.motivo_suspeita is None


def test_chunk_aceita_pagina_nula():
    chunk = Chunk(chunk_id="c1", doc="laudo.docx", pagina=None, secao="1 Introducao", texto="x")

    assert chunk.pagina is None
```

- [ ] **Step 6: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_contrato.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.contrato'`.

- [ ] **Step 7: Implementar contrato.py**

```python
from typing import Literal

from pydantic import BaseModel

Dominio = Literal["geologia", "hidrologia", "meteorologia"]
EntidadeTipo = Literal["tipo_solo", "bacia", "estacao", "municipio"]
Grandeza = Literal["chuva_acumulada", "cota", "vazao"]
Unidade = Literal["mm", "m", "m3/s"]
Nivel = Literal["atencao", "critico"]
Status = Literal["ok", "suspeito"]
Veredito = Literal["aprovado", "rejeitado", "corrigido"]


class RegraExtraida(BaseModel):
    """Exatamente o que o modelo produz. A procedencia de arquivo nao passa
    pelo modelo: quem anexa e o script, a partir dos metadados do chunk."""

    dominio: Dominio
    entidade_tipo: EntidadeTipo
    entidade_nome: str
    grandeza: Grandeza
    janela_horas: int | None
    unidade: Unidade
    nivel: Nivel
    valor: float
    fonte_trecho: str


class Extracao(BaseModel):
    regras: list[RegraExtraida]


class Chunk(BaseModel):
    chunk_id: str
    doc: str
    pagina: int | None
    secao: str | None
    texto: str


class Regra(RegraExtraida):
    regra_id: str
    chunk_id: str
    fonte_doc: str
    fonte_pagina: int | None
    fonte_secao: str | None
    status: Status
    motivo_suspeita: str | None = None


class Decisao(BaseModel):
    regra_id: str
    veredito: Veredito
    valor_corrigido: float | None = None
    revisor: str
    decidido_em: str
```

- [ ] **Step 8: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_contrato.py tests/test_identidade.py -v
```

Esperado: 12 passed.

- [ ] **Step 9: Commit**

```bash
git add ingestao/contrato.py ingestao/identidade.py tests/test_contrato.py tests/test_identidade.py
git commit -m "✨ feat(ingestao): contrato de dados e identidade determinista"
```

---

## Task 3: Persistencia jsonl e manifesto

**Files:**
- Create: `ingestao/persistencia.py`, `tests/test_persistencia.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `persistencia.hash_arquivo(caminho: Path) -> str`
  - `persistencia.ler_jsonl(caminho: Path) -> list[dict]` — devolve `[]` se o arquivo nao existe
  - `persistencia.anexar_jsonl(caminho: Path, registro: dict) -> None` — cria o diretorio pai se faltar
  - `persistencia.escrever_jsonl(caminho: Path, registros: list[dict]) -> int`
  - `persistencia.ids_ja_vistos(caminho: Path, campo: str) -> set[str]`
  - `persistencia.registrar_documento(manifesto: Path, doc: str, hash_doc: str, estado: str, paginas: int, chunks: int) -> None`
  - `persistencia.documento_inalterado(manifesto: Path, doc: str, hash_doc: str) -> bool`

- [ ] **Step 1: Escrever os testes**

`tests/test_persistencia.py`:

```python
from pathlib import Path

from ingestao.persistencia import (
    anexar_jsonl,
    documento_inalterado,
    escrever_jsonl,
    hash_arquivo,
    ids_ja_vistos,
    ler_jsonl,
    registrar_documento,
)


def test_ler_jsonl_de_arquivo_inexistente_devolve_vazio(tmp_path: Path):
    assert ler_jsonl(tmp_path / "nao_existe.jsonl") == []


def test_anexar_e_ler_preserva_ordem(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"

    anexar_jsonl(caminho, {"i": 1})
    anexar_jsonl(caminho, {"i": 2})

    assert [r["i"] for r in ler_jsonl(caminho)] == [1, 2]


def test_anexar_cria_diretorio_pai(tmp_path: Path):
    caminho = tmp_path / "sub" / "dir" / "saida.jsonl"

    anexar_jsonl(caminho, {"i": 1})

    assert caminho.exists()


def test_acentos_sobrevivem_ao_roundtrip(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"

    anexar_jsonl(caminho, {"texto": "saturacao da encosta em Belo Horizonte, regiao sul"})

    assert "regiao sul" in ler_jsonl(caminho)[0]["texto"]


def test_escrever_jsonl_substitui_conteudo(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"
    escrever_jsonl(caminho, [{"i": 1}, {"i": 2}])

    total = escrever_jsonl(caminho, [{"i": 9}])

    assert total == 1
    assert [r["i"] for r in ler_jsonl(caminho)] == [9]


def test_ids_ja_vistos_coleta_o_campo(tmp_path: Path):
    caminho = tmp_path / "saida.jsonl"
    escrever_jsonl(caminho, [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "a"}])

    assert ids_ja_vistos(caminho, "chunk_id") == {"a", "b"}


def test_hash_arquivo_muda_com_o_conteudo(tmp_path: Path):
    um = tmp_path / "um.txt"
    outro = tmp_path / "outro.txt"
    um.write_text("conteudo original", encoding="utf-8")
    outro.write_text("conteudo alterado", encoding="utf-8")

    assert hash_arquivo(um) != hash_arquivo(outro)


def test_documento_inalterado_reconhece_o_mesmo_hash(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"
    registrar_documento(manifesto, "laudo.pdf", "h1", "texto_nativo", 10, 10)

    assert documento_inalterado(manifesto, "laudo.pdf", "h1") is True
    assert documento_inalterado(manifesto, "laudo.pdf", "h2") is False


def test_documento_nao_registrado_nao_esta_inalterado(tmp_path: Path):
    manifesto = tmp_path / "manifesto.jsonl"

    assert documento_inalterado(manifesto, "novo.pdf", "h1") is False
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_persistencia.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.persistencia'`.

- [ ] **Step 3: Implementar persistencia.py**

```python
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def hash_arquivo(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(65536), b""):
            digestor.update(bloco)
    return digestor.hexdigest()[:16]


def ler_jsonl(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open("r", encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def anexar_jsonl(caminho: Path, registro: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


def escrever_jsonl(caminho: Path, registros: list[dict]) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arquivo:
        for registro in registros:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return len(registros)


def ids_ja_vistos(caminho: Path, campo: str) -> set[str]:
    return {registro[campo] for registro in ler_jsonl(caminho) if campo in registro}


def registrar_documento(
    manifesto: Path,
    doc: str,
    hash_doc: str,
    estado: str,
    paginas: int,
    chunks: int,
) -> None:
    anexar_jsonl(
        manifesto,
        {
            "doc": doc,
            "hash": hash_doc,
            "estado": estado,
            "paginas": paginas,
            "chunks": chunks,
            "processado_em": datetime.now(timezone.utc).isoformat(),
        },
    )


def documento_inalterado(manifesto: Path, doc: str, hash_doc: str) -> bool:
    for registro in ler_jsonl(manifesto):
        if registro.get("doc") == doc and registro.get("hash") == hash_doc:
            return True
    return False
```

`ensure_ascii=False` nao e detalhe: sem ele todo texto de laudo em portugues vira escape unicode e o `fonte_trecho` fica ilegivel na revisao.

- [ ] **Step 4: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_persistencia.py -v
```

Esperado: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add ingestao/persistencia.py tests/test_persistencia.py
git commit -m "✨ feat(ingestao): persistencia jsonl e manifesto de documentos"
```

---

## Task 4: Extracao de texto e chunking (etapa 03)

**Files:**
- Create: `ingestao/extracao_texto.py`, `scripts/03_extrair_texto.py`, `tests/test_extracao_texto.py`
- Modify: `Justfile`

**Interfaces:**
- Consumes: `contrato.Chunk`, `identidade.chunk_id`, `persistencia.*`
- Produces:
  - `extracao_texto.extrair_pdf(caminho: Path) -> tuple[list[Chunk], str]` — devolve chunks e o estado (`texto_nativo`, `ocr_aplicado`, `sem_camada_texto`)
  - `extracao_texto.extrair_docx(caminho: Path) -> tuple[list[Chunk], str]`
  - `extracao_texto.extrair(caminho: Path) -> tuple[list[Chunk], str]` — despacha por extensao
  - `extracao_texto.titulo_da_secao(texto_markdown: str) -> str | None`

- [ ] **Step 1: Escrever os testes**

As fixtures sao geradas em codigo com o proprio PyMuPDF — nao ha PDF binario no repo.

`tests/test_extracao_texto.py`:

```python
from pathlib import Path

import pymupdf
import pytest
from docx import Document

from ingestao.extracao_texto import extrair, extrair_docx, extrair_pdf, titulo_da_secao


def _pdf_com_texto(caminho: Path) -> Path:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 100), "4.2 Caracterizacao do solo gnaisse", fontsize=16)
    pagina.insert_text((72, 140), "A saturacao ocorre a partir de 100mm em 72h.", fontsize=11)
    documento.save(caminho)
    documento.close()
    return caminho


def _pdf_sem_camada_texto(caminho: Path) -> Path:
    documento = pymupdf.open()
    documento.new_page()
    documento.save(caminho)
    documento.close()
    return caminho


def _docx_com_secao(caminho: Path) -> Path:
    documento = Document()
    documento.add_heading("1 Limiares hidrologicos", level=1)
    documento.add_paragraph("A cota de transbordamento do Rio Arrudas e 3.8m.")
    documento.save(caminho)
    return caminho


def test_pdf_produz_chunk_com_numero_de_pagina(tmp_path: Path):
    chunks, estado = extrair_pdf(_pdf_com_texto(tmp_path / "laudo.pdf"))

    assert estado == "texto_nativo"
    assert len(chunks) == 1
    assert chunks[0].pagina == 1


def test_pdf_preserva_o_corpo_da_pagina_no_chunk(tmp_path: Path):
    chunks, _ = extrair_pdf(_pdf_com_texto(tmp_path / "laudo.pdf"))

    assert "gnaisse" in chunks[0].texto
    assert "100mm" in chunks[0].texto


def test_pdf_com_tabela_preserva_as_colunas_em_markdown(tmp_path: Path):
    caminho = tmp_path / "tabela.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    html = """
    <table border="1">
      <tr><th>Solo</th><th>Limiar 72h (mm)</th></tr>
      <tr><td>gnaisse</td><td>100</td></tr>
      <tr><td>argiloso</td><td>80</td></tr>
    </table>
    """
    pagina.insert_htmlbox(pymupdf.Rect(50, 50, 500, 300), html)
    documento.save(caminho)
    documento.close()

    chunks, _ = extrair_pdf(caminho)

    texto = chunks[0].texto
    assert "gnaisse" in texto and "argiloso" in texto
    assert "100" in texto and "80" in texto
    # a associacao solo -> valor precisa sobreviver: gnaisse e 100 na mesma linha
    linha_do_gnaisse = next(l for l in texto.splitlines() if "gnaisse" in l)
    assert "100" in linha_do_gnaisse


def test_pdf_sem_camada_de_texto_nao_produz_zero_em_silencio(tmp_path: Path):
    chunks, estado = extrair_pdf(_pdf_sem_camada_texto(tmp_path / "digitalizado.pdf"))

    assert estado in {"sem_camada_texto", "ocr_aplicado"}
    if estado == "sem_camada_texto":
        assert chunks == []


def test_docx_produz_pagina_nula_e_secao_preenchida(tmp_path: Path):
    chunks, estado = extrair_docx(_docx_com_secao(tmp_path / "laudo.docx"))

    assert estado == "texto_nativo"
    assert chunks[0].pagina is None
    assert chunks[0].secao == "1 Limiares hidrologicos"


def test_chunk_id_e_preenchido(tmp_path: Path):
    chunks, _ = extrair_pdf(_pdf_com_texto(tmp_path / "laudo.pdf"))

    assert len(chunks[0].chunk_id) == 16


def test_extrair_despacha_por_extensao(tmp_path: Path):
    chunks_pdf, _ = extrair(_pdf_com_texto(tmp_path / "a.pdf"))
    chunks_docx, _ = extrair(_docx_com_secao(tmp_path / "a.docx"))

    assert chunks_pdf and chunks_docx


def test_extrair_rejeita_extensao_desconhecida(tmp_path: Path):
    arquivo = tmp_path / "planilha.xlsx"
    arquivo.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        extrair(arquivo)


def test_titulo_da_secao_pega_o_primeiro_cabecalho():
    assert titulo_da_secao("## 4.2 Solo gnaisse\n\ncorpo") == "4.2 Solo gnaisse"


def test_titulo_da_secao_sem_cabecalho_devolve_nulo():
    assert titulo_da_secao("apenas corpo de texto") is None
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_extracao_texto.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.extracao_texto'`.

- [ ] **Step 3: Implementar extracao_texto.py**

```python
import re
from pathlib import Path

import pymupdf
import pymupdf4llm
from docx import Document

from ingestao.contrato import Chunk
from ingestao.identidade import chunk_id

_CABECALHO = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_MINIMO_DE_CARACTERES = 10


def titulo_da_secao(texto_markdown: str) -> str | None:
    encontrado = _CABECALHO.search(texto_markdown)
    return encontrado.group(1).strip() if encontrado else None


def _tem_camada_de_texto(caminho: Path) -> bool:
    with pymupdf.open(caminho) as documento:
        for pagina in documento:
            if len(pagina.get_text().strip()) >= _MINIMO_DE_CARACTERES:
                return True
    return False


def extrair_pdf(caminho: Path) -> tuple[list[Chunk], str]:
    tinha_texto = _tem_camada_de_texto(caminho)
    paginas = pymupdf4llm.to_markdown(str(caminho), page_chunks=True)

    chunks: list[Chunk] = []
    ultima_secao: str | None = None
    for pagina in paginas:
        texto = pagina["text"].strip()
        if not texto:
            continue
        secao = titulo_da_secao(pagina["text"]) or ultima_secao
        ultima_secao = secao
        numero = pagina["metadata"]["page"]
        chunks.append(
            Chunk(
                chunk_id=chunk_id(caminho.name, numero, texto),
                doc=caminho.name,
                pagina=numero,
                secao=secao,
                texto=texto,
            )
        )

    if tinha_texto:
        estado = "texto_nativo"
    elif chunks:
        estado = "ocr_aplicado"
    else:
        estado = "sem_camada_texto"
    return chunks, estado
```

O `ultima_secao` propaga o titulo para as paginas seguintes da mesma secao. Sem isso, so a primeira pagina de uma secao de oito paginas saberia a que entidade os numeros pertencem.

Continuar no mesmo arquivo:

```python
def extrair_docx(caminho: Path) -> tuple[list[Chunk], str]:
    documento = Document(str(caminho))

    chunks: list[Chunk] = []
    secao_atual: str | None = None
    corpo: list[str] = []

    def fechar_bloco() -> None:
        texto = "\n".join(corpo).strip()
        if not texto:
            return
        chunks.append(
            Chunk(
                chunk_id=chunk_id(caminho.name, None, texto),
                doc=caminho.name,
                pagina=None,
                secao=secao_atual,
                texto=texto,
            )
        )

    for paragrafo in documento.paragraphs:
        texto = paragrafo.text.strip()
        if not texto:
            continue
        if paragrafo.style.name.startswith("Heading"):
            fechar_bloco()
            corpo = [texto]
            secao_atual = texto
        else:
            corpo.append(texto)
    fechar_bloco()

    return chunks, "texto_nativo"


def extrair(caminho: Path) -> tuple[list[Chunk], str]:
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        return extrair_pdf(caminho)
    if sufixo == ".docx":
        return extrair_docx(caminho)
    raise ValueError(f"extensao nao suportada: {sufixo}")
```

O `.docx` e quebrado por cabecalho, nao por pagina, porque Word nao tem paginacao fixa. O titulo entra no corpo do chunk para que a entidade viaje junto do numero.

- [ ] **Step 4: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_extracao_texto.py -v
```

Esperado: 10 passed.

- [ ] **Step 5: Escrever a CLI da etapa 03**

`scripts/03_extrair_texto.py`:

```python
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.extracao_texto import extrair
from ingestao.persistencia import (
    documento_inalterado,
    escrever_jsonl,
    hash_arquivo,
    registrar_documento,
)

PASTA_DOCS = Path("docs")
PASTA_CHUNKS = Path("data/chunks")
MANIFESTO = Path("data/manifesto.jsonl")


def main() -> int:
    documentos = sorted(
        caminho
        for caminho in PASTA_DOCS.glob("*")
        if caminho.suffix.lower() in {".pdf", ".docx"}
    )
    if not documentos:
        print(f"Nenhum PDF ou DOCX em '{PASTA_DOCS}/'.")
        return 1

    estados: Counter = Counter()
    for caminho in documentos:
        hash_doc = hash_arquivo(caminho)
        if documento_inalterado(MANIFESTO, caminho.name, hash_doc):
            print(f"[pulado] {caminho.name} inalterado")
            estados["pulado"] += 1
            continue

        chunks, estado = extrair(caminho)
        escrever_jsonl(
            PASTA_CHUNKS / f"{caminho.stem}.jsonl",
            [chunk.model_dump() for chunk in chunks],
        )
        paginas = len({chunk.pagina for chunk in chunks})
        registrar_documento(MANIFESTO, caminho.name, hash_doc, estado, paginas, len(chunks))
        estados[estado] += 1
        print(f"[{estado}] {caminho.name}: {len(chunks)} chunks")

    print("\nResumo por estado:")
    for estado, total in sorted(estados.items()):
        print(f"  {estado}: {total}")
    if estados["sem_camada_texto"]:
        print(
            f"\nATENCAO: {estados['sem_camada_texto']} documento(s) sem camada de texto "
            "nao produziram chunk algum. Verificar se o Tesseract esta instalado."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

O aviso final existe porque zero regras e indistinguivel de "documento sem regras": o operador precisa ver a contagem.

- [ ] **Step 6: Verificar a CLI com um PDF real**

```bash
mkdir -p docs
./venv/Scripts/python.exe -c "import pymupdf; d=pymupdf.open(); p=d.new_page(); p.insert_text((72,100),'4.2 Solo gnaisse',fontsize=16); p.insert_text((72,140),'Saturacao a partir de 100mm em 72h.',fontsize=11); d.save('docs/exemplo.pdf'); d.close()"
./venv/Scripts/python.exe scripts/03_extrair_texto.py
```

Esperado: `[texto_nativo] exemplo.pdf: 1 chunks` e o resumo por estado. Rodar de novo deve imprimir `[pulado] exemplo.pdf inalterado`.

- [ ] **Step 7: Adicionar a receita no Justfile**

```just
# etapa 03: extrai texto e chunks dos documentos em docs/
extrair-texto:
    {{python}} scripts/03_extrair_texto.py
```

- [ ] **Step 8: Commit**

```bash
git add ingestao/extracao_texto.py scripts/03_extrair_texto.py tests/test_extracao_texto.py Justfile
git commit -m "✨ feat(ingestao): etapa 03 de extracao de texto e chunking"
```

---

## Task 5: Validacao e rede de recall

**Files:**
- Create: `ingestao/validacao.py`, `tests/test_validacao.py`

**Interfaces:**
- Consumes: `contrato.RegraExtraida`
- Produces:
  - `validacao.normalizar(texto: str) -> str`
  - `validacao.trecho_confere(trecho: str, texto_chunk: str) -> bool`
  - `validacao.valor_plausivel(grandeza: str, unidade: str, valor: float) -> bool`
  - `validacao.classificar(regra: RegraExtraida, texto_chunk: str) -> tuple[str, str | None]` — devolve `("ok", None)` ou `("suspeito", motivo)`
  - `validacao.suspeito_de_omissao(texto_chunk: str, total_de_regras: int) -> bool`

- [ ] **Step 1: Escrever os testes**

`tests/test_validacao.py`:

```python
from ingestao.contrato import RegraExtraida
from ingestao.validacao import (
    classificar,
    normalizar,
    suspeito_de_omissao,
    trecho_confere,
    valor_plausivel,
)


def _regra(**sobrescritas) -> RegraExtraida:
    payload = {
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "nivel": "critico",
        "valor": 100.0,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
    }
    payload.update(sobrescritas)
    return RegraExtraida(**payload)


def test_normalizar_colapsa_espaco_e_markdown():
    assert normalizar("##  Solo   **gnaisse**  ") == "solo gnaisse"


def test_normalizar_remove_acento():
    assert normalizar("saturacao") == normalizar("saturação")


def test_trecho_confere_ignora_diferenca_de_espaco():
    assert trecho_confere("100mm em 72h", "o limiar e de   100mm  em 72h no gnaisse")


def test_trecho_inventado_nao_confere():
    assert not trecho_confere("800mm em 24h", "o limiar e de 100mm em 72h")


def test_valor_plausivel_aceita_chuva_razoavel():
    assert valor_plausivel("chuva_acumulada", "mm", 100.0)


def test_valor_implausivel_de_chuva_e_recusado():
    assert not valor_plausivel("chuva_acumulada", "mm", 90000.0)


def test_valor_plausivel_aceita_cota_de_rio():
    assert valor_plausivel("cota", "m", 3.8)


def test_combinacao_de_grandeza_e_unidade_desconhecida_e_recusada():
    assert not valor_plausivel("cota", "mm", 3.8)


def test_classificar_regra_boa_devolve_ok():
    chunk = "conforme o estudo, saturacao a partir de 100mm em 72h no solo gnaisse"

    assert classificar(_regra(), chunk) == ("ok", None)


def test_classificar_marca_citacao_inventada():
    status, motivo = classificar(_regra(), "texto que nao contem a citacao")

    assert status == "suspeito"
    assert "trecho" in motivo


def test_classificar_marca_valor_implausivel():
    chunk = "saturacao a partir de 100mm em 72h"
    status, motivo = classificar(_regra(valor=90000.0), chunk)

    assert status == "suspeito"
    assert "valor" in motivo


def test_chunk_com_limiar_e_zero_regras_e_suspeito_de_omissao():
    assert suspeito_de_omissao("o acumulado critico e de 80mm em 24h", 0)


def test_chunk_sem_padrao_de_limiar_nao_e_suspeito():
    assert not suspeito_de_omissao("este capitulo descreve a metodologia adotada", 0)


def test_chunk_que_produziu_regra_nao_e_suspeito_de_omissao():
    assert not suspeito_de_omissao("o acumulado critico e de 80mm em 24h", 1)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_validacao.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.validacao'`.

- [ ] **Step 3: Implementar validacao.py**

```python
import re
import unicodedata

from ingestao.contrato import RegraExtraida

FAIXAS_PLAUSIVEIS: dict[tuple[str, str], tuple[float, float]] = {
    ("chuva_acumulada", "mm"): (1.0, 1000.0),
    ("cota", "m"): (0.1, 50.0),
    ("vazao", "m3/s"): (0.1, 100000.0),
}

_PADRAO_DE_LIMIAR = re.compile(r"\d+(?:[.,]\d+)?\s*(?:mm|m3/s|m\b|h\b)", re.IGNORECASE)
_MARCACAO_MARKDOWN = re.compile(r"[#*_`|>-]+")
_ESPACOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    sem_markdown = _MARCACAO_MARKDOWN.sub(" ", sem_acento)
    return _ESPACOS.sub(" ", sem_markdown).strip().lower()


def trecho_confere(trecho: str, texto_chunk: str) -> bool:
    return normalizar(trecho) in normalizar(texto_chunk)


def valor_plausivel(grandeza: str, unidade: str, valor: float) -> bool:
    faixa = FAIXAS_PLAUSIVEIS.get((grandeza, unidade))
    if faixa is None:
        return False
    minimo, maximo = faixa
    return minimo <= valor <= maximo


def classificar(regra: RegraExtraida, texto_chunk: str) -> tuple[str, str | None]:
    if not trecho_confere(regra.fonte_trecho, texto_chunk):
        return "suspeito", "trecho citado nao encontrado no chunk de origem"
    if not valor_plausivel(regra.grandeza, regra.unidade, regra.valor):
        return "suspeito", f"valor {regra.valor} fora da faixa para {regra.grandeza} em {regra.unidade}"
    return "ok", None


def suspeito_de_omissao(texto_chunk: str, total_de_regras: int) -> bool:
    if total_de_regras > 0:
        return False
    return bool(_PADRAO_DE_LIMIAR.search(texto_chunk))
```

A ordem em `classificar` e deliberada: a citacao e conferida antes do valor, porque trecho inventado torna o valor irrelevante e o motivo mais util para o revisor e o primeiro.

- [ ] **Step 4: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_validacao.py -v
```

Esperado: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add ingestao/validacao.py tests/test_validacao.py
git commit -m "✨ feat(ingestao): validacao de trecho, faixa e rede de recall"
```

---

## Task 6: Extrator de regras (etapa 04)

**Files:**
- Create: `ingestao/extrator_regras.py`, `scripts/04_extrair_regras.py`, `tests/test_extrator_regras.py`
- Modify: `Justfile`

**Interfaces:**
- Consumes: `contrato.Chunk`, `contrato.Extracao`, `contrato.Regra`, `identidade.regra_id`, `validacao.classificar`, `validacao.suspeito_de_omissao`, `persistencia.*`
- Produces:
  - `extrator_regras.montar_prompt(chunk: Chunk) -> str`
  - `extrator_regras.extrair_do_chunk(chunk: Chunk, gerar: Callable[[str], str]) -> list[Regra]`
  - `extrator_regras.criar_gerador_qwen(model_id: str = "Qwen/Qwen2.5-7B-Instruct") -> Callable[[str], str]`
  - `extrator_regras.processar(chunks: list[Chunk], gerar, saida: Path, omissoes: Path) -> dict`

- [ ] **Step 1: Escrever os testes com gerador falso**

O gerador e injetado: a orquestracao e testada sem GPU e sem baixar 7B.

`tests/test_extrator_regras.py`:

```python
import json
from pathlib import Path

from ingestao.contrato import Chunk
from ingestao.extrator_regras import extrair_do_chunk, montar_prompt, processar
from ingestao.persistencia import ler_jsonl

TEXTO = "4.2 Solo gnaisse. A saturacao ocorre a partir de 100mm em 72h."


def _chunk(chunk_id: str = "c1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc="laudo.pdf",
        pagina=12,
        secao="4.2 Caracterizacao do solo",
        texto=TEXTO,
    )


def _gerador(payload: dict):
    def gerar(_prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    return gerar


def _uma_regra(valor: float = 100.0, trecho: str = "saturacao ocorre a partir de 100mm em 72h") -> dict:
    return {
        "regras": [
            {
                "dominio": "geologia",
                "entidade_tipo": "tipo_solo",
                "entidade_nome": "gnaisse",
                "grandeza": "chuva_acumulada",
                "janela_horas": 72,
                "unidade": "mm",
                "nivel": "critico",
                "valor": valor,
                "fonte_trecho": trecho,
            }
        ]
    }


def test_prompt_contem_o_texto_e_a_secao_do_chunk():
    prompt = montar_prompt(_chunk())

    assert TEXTO in prompt
    assert "4.2 Caracterizacao do solo" in prompt


def test_extrair_anexa_procedencia_que_nao_veio_do_modelo():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert len(regras) == 1
    assert regras[0].fonte_doc == "laudo.pdf"
    assert regras[0].fonte_pagina == 12
    assert regras[0].fonte_secao == "4.2 Caracterizacao do solo"
    assert regras[0].chunk_id == "c1"


def test_regra_boa_recebe_status_ok():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert regras[0].status == "ok"


def test_citacao_inventada_recebe_status_suspeito():
    regras = extrair_do_chunk(_chunk(), _gerador(_uma_regra(trecho="800mm em 24h")))

    assert regras[0].status == "suspeito"
    assert "trecho" in regras[0].motivo_suspeita


def test_valor_implausivel_recebe_status_suspeito():
    payload = _uma_regra(valor=90000.0, trecho="saturacao ocorre a partir de 100mm em 72h")
    regras = extrair_do_chunk(_chunk(), _gerador(payload))

    assert regras[0].status == "suspeito"


def test_lista_vazia_e_resultado_legitimo():
    assert extrair_do_chunk(_chunk(), _gerador({"regras": []})) == []


def test_regra_id_e_estavel_entre_execucoes():
    primeira = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))
    segunda = extrair_do_chunk(_chunk(), _gerador(_uma_regra()))

    assert primeira[0].regra_id == segunda[0].regra_id


def test_processar_grava_regras_e_conta(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"

    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes)

    assert resumo["regras"] == 1
    assert resumo["chunks_processados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_processar_retoma_e_pula_chunk_ja_feito(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"
    processar([_chunk()], _gerador(_uma_regra()), saida, omissoes)

    resumo = processar([_chunk()], _gerador(_uma_regra()), saida, omissoes)

    assert resumo["chunks_pulados"] == 1
    assert len(ler_jsonl(saida)) == 1


def test_chunk_com_limiar_e_zero_regras_vai_para_omissoes(tmp_path: Path):
    saida = tmp_path / "propostas.jsonl"
    omissoes = tmp_path / "omissoes.jsonl"

    resumo = processar([_chunk()], _gerador({"regras": []}), saida, omissoes)

    assert resumo["omissoes"] == 1
    assert ler_jsonl(omissoes)[0]["chunk_id"] == "c1"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_extrator_regras.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.extrator_regras'`.

- [ ] **Step 3: Implementar extrator_regras.py**

```python
from pathlib import Path
from typing import Callable

from ingestao.contrato import Chunk, Extracao, Regra
from ingestao.identidade import regra_id
from ingestao.persistencia import anexar_jsonl, ids_ja_vistos
from ingestao.validacao import classificar, suspeito_de_omissao

MODELO_PADRAO = "Qwen/Qwen2.5-7B-Instruct"
SEMENTE = 42
MAX_TOKENS_DE_SAIDA = 1024

INSTRUCAO = """Voce extrai limiares tecnicos de laudos da Defesa Civil.

Extraia do trecho abaixo TODOS os limiares numericos que disparam atencao ou
alerta. Para cada um, copie em fonte_trecho o pedaco EXATO do texto original que
sustenta o numero, sem reescrever nem resumir.

Se o trecho nao fixa limiar algum, devolva a lista vazia. Nao invente limiar que
nao esteja escrito, e nao converta unidade.

Secao: {secao}

Trecho:
{texto}
"""


def montar_prompt(chunk: Chunk) -> str:
    return INSTRUCAO.format(secao=chunk.secao or "nao identificada", texto=chunk.texto)


def extrair_do_chunk(chunk: Chunk, gerar: Callable[[str], str]) -> list[Regra]:
    bruto = gerar(montar_prompt(chunk))
    extracao = Extracao.model_validate_json(bruto)

    regras: list[Regra] = []
    for extraida in extracao.regras:
        status, motivo = classificar(extraida, chunk.texto)
        regras.append(
            Regra(
                **extraida.model_dump(),
                regra_id=regra_id(
                    chunk.chunk_id,
                    extraida.entidade_tipo,
                    extraida.entidade_nome,
                    extraida.grandeza,
                    extraida.nivel,
                    extraida.valor,
                ),
                chunk_id=chunk.chunk_id,
                fonte_doc=chunk.doc,
                fonte_pagina=chunk.pagina,
                fonte_secao=chunk.secao,
                status=status,
                motivo_suspeita=motivo,
            )
        )
    return regras


def processar(
    chunks: list[Chunk],
    gerar: Callable[[str], str],
    saida: Path,
    omissoes: Path,
) -> dict:
    ja_feitos = ids_ja_vistos(saida, "chunk_id") | ids_ja_vistos(omissoes, "chunk_id")

    resumo = {"chunks_processados": 0, "chunks_pulados": 0, "regras": 0, "suspeitas": 0, "omissoes": 0}
    for chunk in chunks:
        if chunk.chunk_id in ja_feitos:
            resumo["chunks_pulados"] += 1
            continue

        regras = extrair_do_chunk(chunk, gerar)
        for regra in regras:
            anexar_jsonl(saida, regra.model_dump())
            resumo["regras"] += 1
            if regra.status == "suspeito":
                resumo["suspeitas"] += 1

        if suspeito_de_omissao(chunk.texto, len(regras)):
            anexar_jsonl(
                omissoes,
                {"chunk_id": chunk.chunk_id, "doc": chunk.doc, "pagina": chunk.pagina, "texto": chunk.texto},
            )
            resumo["omissoes"] += 1

        resumo["chunks_processados"] += 1
    return resumo
```

A retomada considera `saida` e `omissoes`: um chunk que produziu zero regras foi processado, e sem consultar as omissoes ele seria reprocessado a cada execucao.

Continuar no mesmo arquivo, a fabrica do gerador real:

```python
def criar_gerador_qwen(model_id: str = MODELO_PADRAO) -> Callable[[str], str]:
    import outlines
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quantizacao = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    modelo = outlines.from_transformers(
        AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=quantizacao,
            dtype=torch.bfloat16,
            device_map="cuda:0",
        ),
        AutoTokenizer.from_pretrained(model_id),
    )
    gerador = outlines.Generator(modelo, Extracao)

    def gerar(prompt: str) -> str:
        return gerador(
            prompt,
            max_new_tokens=MAX_TOKENS_DE_SAIDA,
            temperature=0,
            seed=SEMENTE,
        )

    return gerar
```

`bfloat16` aqui segue o que foi medido no treino nesta maquina, e `temperature=0` com `seed` fixa atende ao requisito de reprodutibilidade da spec.

- [ ] **Step 4: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_extrator_regras.py -v
```

Esperado: 10 passed.

- [ ] **Step 5: Escrever a CLI da etapa 04**

`scripts/04_extrair_regras.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestao.contrato import Chunk
from ingestao.extrator_regras import criar_gerador_qwen, processar
from ingestao.persistencia import ler_jsonl

PASTA_CHUNKS = Path("data/chunks")
PROPOSTAS = Path("data/regras_propostas.jsonl")
OMISSOES = Path("data/possiveis_omissoes.jsonl")


def main() -> int:
    arquivos = sorted(PASTA_CHUNKS.glob("*.jsonl"))
    if not arquivos:
        print(f"Nenhum chunk em '{PASTA_CHUNKS}/'. Rode a etapa 03 primeiro.")
        return 1

    chunks = [Chunk(**registro) for arquivo in arquivos for registro in ler_jsonl(arquivo)]
    print(f"{len(chunks)} chunks para processar. Carregando o modelo...")

    gerar = criar_gerador_qwen()
    resumo = processar(chunks, gerar, PROPOSTAS, OMISSOES)

    print("\nResumo:")
    for chave, valor in resumo.items():
        print(f"  {chave}: {valor}")
    if resumo["omissoes"]:
        print(f"\n{resumo['omissoes']} chunk(s) com padrao de limiar e zero regras em '{OMISSOES}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Adicionar a receita no Justfile**

```just
# etapa 04: extrai as regras dos chunks com o Qwen 7B local
extrair-regras:
    {{python}} scripts/04_extrair_regras.py
```

- [ ] **Step 7: Commit**

```bash
git add ingestao/extrator_regras.py scripts/04_extrair_regras.py tests/test_extrator_regras.py Justfile
git commit -m "✨ feat(ingestao): etapa 04 de extracao de regras com decodificacao restrita"
```

---

## Task 7: Fila de revisao web (etapa 05)

**Files:**
- Create: `ingestao/revisao/__init__.py`, `ingestao/revisao/app.py`, `ingestao/revisao/index.html`, `scripts/05_revisar.py`, `tests/test_revisao_app.py`
- Modify: `Justfile`

**Interfaces:**
- Consumes: `contrato.Decisao`, `persistencia.*`
- Produces:
  - `revisao.app.criar_app(propostas: Path, decisoes: Path, aprovadas: Path) -> FastAPI`
  - `GET /api/pendentes` — `{"pendentes": [regra, ...], "total": int}`
  - `POST /api/decisao` — corpo `{regra_id, veredito, valor_corrigido, revisor}`; grava decisao e regenera as aprovadas
  - `GET /` — a pagina de revisao

- [ ] **Step 1: Escrever os testes**

`tests/test_revisao_app.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ingestao.persistencia import escrever_jsonl, ler_jsonl
from ingestao.revisao.app import criar_app


def _regra(regra_id: str, valor: float = 100.0) -> dict:
    return {
        "regra_id": regra_id,
        "chunk_id": "c1",
        "dominio": "geologia",
        "entidade_tipo": "tipo_solo",
        "entidade_nome": "gnaisse",
        "grandeza": "chuva_acumulada",
        "janela_horas": 72,
        "unidade": "mm",
        "nivel": "critico",
        "valor": valor,
        "fonte_trecho": "saturacao a partir de 100mm em 72h",
        "fonte_doc": "laudo.pdf",
        "fonte_pagina": 12,
        "fonte_secao": "4.2 Caracterizacao do solo",
        "status": "ok",
        "motivo_suspeita": None,
    }


@pytest.fixture
def ambiente(tmp_path: Path):
    propostas = tmp_path / "propostas.jsonl"
    decisoes = tmp_path / "decisoes.jsonl"
    aprovadas = tmp_path / "aprovadas.jsonl"
    escrever_jsonl(propostas, [_regra("r1"), _regra("r2")])
    cliente = TestClient(criar_app(propostas, decisoes, aprovadas))
    return cliente, decisoes, aprovadas


def test_fila_lista_todas_as_pendentes(ambiente):
    cliente, _, _ = ambiente

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 2


def test_aprovar_grava_decisao_com_revisor(ambiente):
    cliente, decisoes, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"},
    )

    assert resposta.status_code == 200
    registro = ler_jsonl(decisoes)[0]
    assert registro["regra_id"] == "r1"
    assert registro["revisor"] == "matheus"
    assert registro["decidido_em"]


def test_regra_decidida_sai_da_fila(ambiente):
    cliente, _, _ = ambiente
    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})

    corpo = cliente.get("/api/pendentes").json()

    assert corpo["total"] == 1
    assert corpo["pendentes"][0]["regra_id"] == "r2"


def test_aprovada_entra_no_arquivo_de_aprovadas(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "aprovado", "revisor": "matheus"})

    assert [r["regra_id"] for r in ler_jsonl(aprovadas)] == ["r1"]


def test_rejeitada_nao_entra_nas_aprovadas(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post("/api/decisao", json={"regra_id": "r1", "veredito": "rejeitado", "revisor": "matheus"})

    assert ler_jsonl(aprovadas) == []


def test_correcao_do_valor_entra_nas_aprovadas_com_o_valor_novo(ambiente):
    cliente, _, aprovadas = ambiente

    cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "corrigido", "valor_corrigido": 90.0, "revisor": "matheus"},
    )

    aprovada = ler_jsonl(aprovadas)[0]
    assert aprovada["valor"] == 90.0
    assert aprovada["valor_original"] == 100.0


def test_decisao_para_regra_inexistente_devolve_404(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "inexistente", "veredito": "aprovado", "revisor": "matheus"},
    )

    assert resposta.status_code == 404


def test_veredito_invalido_e_recusado_na_validacao(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.post(
        "/api/decisao",
        json={"regra_id": "r1", "veredito": "talvez", "revisor": "matheus"},
    )

    assert resposta.status_code == 422


def test_pagina_de_revisao_responde(ambiente):
    cliente, _, _ = ambiente

    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_revisao_app.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'ingestao.revisao'`.

- [ ] **Step 3: Implementar o app**

```bash
mkdir -p ingestao/revisao
touch ingestao/revisao/__init__.py
```

`ingestao/revisao/app.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ingestao.contrato import Decisao, Veredito
from ingestao.persistencia import anexar_jsonl, escrever_jsonl, ler_jsonl

PAGINA = Path(__file__).parent / "index.html"


class PedidoDeDecisao(BaseModel):
    regra_id: str
    veredito: Veredito
    valor_corrigido: float | None = None
    revisor: str


def criar_app(propostas: Path, decisoes: Path, aprovadas: Path) -> FastAPI:
    app = FastAPI(title="Revisao de limiares")

    def _decididos() -> set[str]:
        return {registro["regra_id"] for registro in ler_jsonl(decisoes)}

    def _regenerar_aprovadas() -> None:
        por_id = {registro["regra_id"]: registro for registro in ler_jsonl(propostas)}
        saida = []
        for decisao in ler_jsonl(decisoes):
            if decisao["veredito"] == "rejeitado":
                continue
            regra = dict(por_id.get(decisao["regra_id"], {}))
            if not regra:
                continue
            if decisao["veredito"] == "corrigido" and decisao.get("valor_corrigido") is not None:
                regra["valor_original"] = regra["valor"]
                regra["valor"] = decisao["valor_corrigido"]
            regra["revisado_por"] = decisao["revisor"]
            regra["revisado_em"] = decisao["decidido_em"]
            saida.append(regra)
        escrever_jsonl(aprovadas, saida)

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return PAGINA.read_text(encoding="utf-8")

    @app.get("/api/pendentes")
    def pendentes() -> dict:
        decididos = _decididos()
        fila = [
            regra
            for regra in ler_jsonl(propostas)
            if regra["regra_id"] not in decididos
        ]
        return {"pendentes": fila, "total": len(fila)}

    @app.post("/api/decisao")
    def decidir(pedido: PedidoDeDecisao) -> dict:
        existe = any(regra["regra_id"] == pedido.regra_id for regra in ler_jsonl(propostas))
        if not existe:
            raise HTTPException(status_code=404, detail="regra_id nao encontrado nas propostas")

        decisao = Decisao(
            regra_id=pedido.regra_id,
            veredito=pedido.veredito,
            valor_corrigido=pedido.valor_corrigido,
            revisor=pedido.revisor,
            decidido_em=datetime.now(timezone.utc).isoformat(),
        )
        anexar_jsonl(decisoes, decisao.model_dump())
        _regenerar_aprovadas()
        return {"ok": True, "regra_id": pedido.regra_id}

    return app
```

`_regenerar_aprovadas` reconstroi o arquivo inteiro a partir do registro acumulativo de decisoes, em vez de anexar. Assim `decisoes.jsonl` e a unica fonte de verdade e uma reexecucao nao duplica linha.

- [ ] **Step 4: Escrever a pagina**

`ingestao/revisao/index.html`. Sem framework e sem CDN: a maquina e corporativa e pode nao ter saida para internet.

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Revisao de limiares</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; }
  .trecho { background: #fffbe6; border-left: 4px solid #e0b400; padding: 1rem; font-size: 1.1rem; }
  .campos { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem 1rem; margin: 1rem 0; }
  .campo strong { display: block; font-size: .75rem; color: #666; text-transform: uppercase; }
  .suspeito { background: #ffe6e6; border-left: 4px solid #cc0000; padding: .5rem 1rem; }
  .acoes { display: flex; gap: .5rem; align-items: center; }
  button { padding: .5rem 1rem; font-size: 1rem; cursor: pointer; }
  #fim { display: none; }
</style>
</head>
<body>
<h1>Revisao de limiares</h1>
<p id="contador"></p>

<div id="cartao">
  <div class="trecho" id="trecho"></div>
  <div class="suspeito" id="motivo" hidden></div>
  <div class="campos" id="campos"></div>
  <div class="acoes">
    <button onclick="decidir('aprovado')">Aprovar (A)</button>
    <button onclick="decidir('rejeitado')">Rejeitar (R)</button>
    <button onclick="corrigir()">Corrigir valor (C)</button>
  </div>
</div>

<p id="fim">Fila vazia. Nada pendente de revisao.</p>

<script>
let fila = [];
let atual = null;
const revisor = prompt("Seu nome, para a trilha de auditoria:") || "nao identificado";

async function carregar() {
  const resposta = await fetch("/api/pendentes");
  const corpo = await resposta.json();
  fila = corpo.pendentes;
  mostrar();
}

function mostrar() {
  atual = fila.shift() || null;
  document.getElementById("contador").textContent =
    atual ? `${fila.length + 1} pendente(s)` : "";
  document.getElementById("cartao").hidden = !atual;
  document.getElementById("fim").style.display = atual ? "none" : "block";
  if (!atual) return;

  document.getElementById("trecho").textContent = atual.fonte_trecho;
  const motivo = document.getElementById("motivo");
  motivo.hidden = atual.status !== "suspeito";
  motivo.textContent = atual.motivo_suspeita || "";

  const ordem = ["valor", "unidade", "entidade_nome", "nivel", "janela_horas",
                 "dominio", "grandeza", "fonte_doc", "fonte_pagina"];
  document.getElementById("campos").innerHTML = ordem
    .map(campo => `<div class="campo"><strong>${campo}</strong>${atual[campo] ?? "-"}</div>`)
    .join("");
}

async function decidir(veredito, valorCorrigido) {
  if (!atual) return;
  await fetch("/api/decisao", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      regra_id: atual.regra_id,
      veredito: veredito,
      valor_corrigido: valorCorrigido ?? null,
      revisor: revisor,
    }),
  });
  mostrar();
}

function corrigir() {
  if (!atual) return;
  const entrada = prompt("Valor correto:", atual.valor);
  if (entrada === null) return;
  const valor = parseFloat(entrada.replace(",", "."));
  if (Number.isNaN(valor)) return;
  decidir("corrigido", valor);
}

document.addEventListener("keydown", evento => {
  if (evento.target.tagName === "INPUT") return;
  const tecla = evento.key.toLowerCase();
  if (tecla === "a") decidir("aprovado");
  if (tecla === "r") decidir("rejeitado");
  if (tecla === "c") corrigir();
});

carregar();
</script>
</body>
</html>
```

O trecho aparece antes dos campos, e `valor` e o primeiro campo da grade: a evidencia vem antes da conclusao da maquina, como exige a spec.

- [ ] **Step 5: Rodar e ver passar**

```bash
./venv/Scripts/python.exe -m pytest tests/test_revisao_app.py -v
```

Esperado: 9 passed.

- [ ] **Step 6: Escrever a CLI da etapa 05**

`scripts/05_revisar.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from ingestao.revisao.app import criar_app

PROPOSTAS = Path("data/regras_propostas.jsonl")
DECISOES = Path("data/decisoes.jsonl")
APROVADAS = Path("data/regras_aprovadas.jsonl")


def main() -> int:
    if not PROPOSTAS.exists():
        print(f"'{PROPOSTAS}' nao existe. Rode a etapa 04 primeiro.")
        return 1

    print("Revisao em http://127.0.0.1:8100 (Ctrl+C para encerrar)")
    uvicorn.run(criar_app(PROPOSTAS, DECISOES, APROVADAS), host="127.0.0.1", port=8100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Preso em `127.0.0.1`: sem autenticacao, a fila nao pode ficar exposta na rede.

- [ ] **Step 7: Verificar a mao com dados falsos**

```bash
./venv/Scripts/python.exe -c "
import json, pathlib
regra = {'regra_id':'r1','chunk_id':'c1','dominio':'geologia','entidade_tipo':'tipo_solo','entidade_nome':'gnaisse','grandeza':'chuva_acumulada','janela_horas':72,'unidade':'mm','nivel':'critico','valor':100.0,'fonte_trecho':'saturacao a partir de 100mm em 72h','fonte_doc':'laudo.pdf','fonte_pagina':12,'fonte_secao':'4.2','status':'ok','motivo_suspeita':None}
pathlib.Path('data').mkdir(exist_ok=True)
pathlib.Path('data/regras_propostas.jsonl').write_text(json.dumps(regra, ensure_ascii=False)+'\n', encoding='utf-8')
"
./venv/Scripts/python.exe scripts/05_revisar.py
```

Abrir `http://127.0.0.1:8100`, informar o nome, aprovar com a tecla `A`, conferir que `data/regras_aprovadas.jsonl` recebeu a linha com `revisado_por`, e que a fila esvaziou. Encerrar com Ctrl+C e apagar o `data/regras_propostas.jsonl` de teste.

- [ ] **Step 8: Adicionar a receita no Justfile**

```just
# etapa 05: sobe a fila de revisao em http://127.0.0.1:8100
revisar:
    {{python}} scripts/05_revisar.py

# esteira completa: extrai texto, extrai regras e abre a revisao
ingestao: extrair-texto extrair-regras revisar
```

- [ ] **Step 9: Commit**

```bash
git add ingestao/revisao scripts/05_revisar.py tests/test_revisao_app.py Justfile
git commit -m "✨ feat(ingestao): etapa 05 com fila de revisao web local"
```

---

## Task 8: Verificacao com o modelo real e medicao

**Files:**
- Create: `tests/test_extracao_real.py`
- Modify: `docs/superpowers/specs/2026-09-08-esteira-ingestao-geoespacial-design.md` (secao 10, riscos medidos)

**Interfaces:**
- Consumes: `extrator_regras.criar_gerador_qwen`, `extrator_regras.extrair_do_chunk`
- Produces: numeros reais de VRAM e tempo por chunk; resposta a dois riscos abertos da spec

- [ ] **Step 1: Escrever o teste marcado como gpu**

`tests/test_extracao_real.py`:

```python
import time

import pytest

from ingestao.contrato import Chunk
from ingestao.extrator_regras import criar_gerador_qwen, extrair_do_chunk

TEXTO = (
    "4.2 Caracterizacao do solo. Para o solo gnaisse, a saturacao critica "
    "ocorre a partir de 100mm de chuva acumulada em 72h. Para o solo argiloso, "
    "o limiar critico e de 80mm em 72h."
)


@pytest.mark.gpu
def test_modelo_real_extrai_os_dois_limiares_do_trecho():
    import torch

    chunk = Chunk(chunk_id="c1", doc="laudo.pdf", pagina=12, secao="4.2 Caracterizacao do solo", texto=TEXTO)

    torch.cuda.reset_peak_memory_stats()
    gerar = criar_gerador_qwen()
    inicio = time.time()
    regras = extrair_do_chunk(chunk, gerar)
    decorrido = time.time() - inicio
    pico_gb = torch.cuda.max_memory_allocated() / 1024**3

    print(f"\ntempo por chunk: {decorrido:.1f}s | VRAM pico: {pico_gb:.2f}GB | regras: {len(regras)}")

    assert len(regras) == 2
    valores = sorted(regra.valor for regra in regras)
    assert valores == [80.0, 100.0]
    assert all(regra.status == "ok" for regra in regras)
    assert pico_gb < 8.0
```

- [ ] **Step 2: Rodar o teste de GPU**

```bash
./venv/Scripts/python.exe -m pytest tests/test_extracao_real.py -v -m gpu -s
```

O `-s` e necessario para ver a linha de medicao. O primeiro download do 7B leva alguns minutos.

Esperado: PASS, com `tempo por chunk` e `VRAM pico` impressos.

- [ ] **Step 3: Se o modelo nao couber ou o teste falhar**

Se `pico_gb` passar de 8 GB ou houver `torch.OutOfMemoryError`, editar `MODELO_PADRAO` em `ingestao/extrator_regras.py`:

```python
MODELO_PADRAO = "Qwen/Qwen2.5-3B-Instruct"
```

E rodar o mesmo teste de novo:

```bash
./venv/Scripts/python.exe -m pytest tests/test_extracao_real.py -v -m gpu -s
```

Registrar a troca na spec no passo 4. **Nao seguir adiante sem medir** — a spec lista esse cabimento como risco aberto, e a resposta e um numero, nao uma estimativa.

Se as duas regras nao forem extraidas, o problema e o prompt, nao a infra: iterar em `INSTRUCAO` com esse teste como criterio, sem afrouxar a assercao.

- [ ] **Step 4: Registrar as medicoes na spec**

Na secao 10 da spec, substituir o paragrafo "Cabimento do 7B em 4-bit nos 8GB da T1000" pelo resultado medido: modelo escolhido, VRAM de pico, tempo por chunk. Substituir tambem o paragrafo do Tesseract pelo que a Task 4 revelou (se o OCR funcionou ou se documento digitalizado ficou retido).

- [ ] **Step 5: Rodar a suite inteira**

```bash
./venv/Scripts/python.exe -m pytest -v
```

Esperado: todos os testes nao marcados como `gpu` passando. Confirmar tambem que o treino segue intacto:

```bash
./venv/Scripts/python.exe -c "import transformers, trl; print(transformers.__version__, trl.__version__)"
```

Esperado: `5.16.1 1.12.0`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_extracao_real.py docs/superpowers/specs/2026-09-08-esteira-ingestao-geoespacial-design.md
git commit -m "✅ test(ingestao): verificacao com modelo real e medicoes na spec"
```

---

## Fora deste plano

**Etapa 06 (carga PostGIS)** — bloqueada pelo schema real das camadas da Cedec. Antes de planejar, e preciso saber: a camada de encostas traz o tipo de solo classificado? As bacias sao identificaveis pelo nome que aparece nos laudos? Se nao, entra uma tabela de ponte mantida a mao, e isso muda o desenho da etapa.

**Leitura do `REGRAS` a partir do banco** em `scripts/01.gerar_dataset.py` — depende da etapa 06 existir.

**Ocorrencias historicas** — fora do escopo da v1 por decisao registrada na spec.
