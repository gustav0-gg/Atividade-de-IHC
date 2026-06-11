# 💊 **Bot MedInfo**
<p align="center">
       <img width="1024" height="559" alt="medinfo" src="https://github.com/user-attachments/assets/7e4298b4-4cfa-44ab-8979-c8d1968f0c1f" />
<br>
<hr>
<br>
     
# Agente de Consulta de Medicamentos

Agente de IA para consulta de medicamentos em linguagem natural, desenvolvido com **DSPy** e **Phi-3.5-mini (3.8B)** rodando localmente via Ollama. O agente interpreta perguntas em português, gera queries SQL automaticamente e retorna respostas humanizadas — com interface via **CLI** ou **bot do Telegram**.

Projeto desenvolvido para a disciplina de **Interação Humano Computador** — FATEC, ADS 3º Semestre.

---

## Como funciona

O usuário digita uma pergunta em português. O agente passa por um pipeline antes de responder:

```
Pergunta do usuário
       ↓
[1] Classificar — identifica se é consulta, interação, fabricante ou fora do escopo
       ↓
[2] Gerar SQL — converte a pergunta em query para o banco de medicamentos
       ↓
[3] Corrigir SQL (se necessário) — retry automático em caso de erro no SQLite
       ↓
[4] Interpretar — transforma o resultado do banco em resposta humanizada
       ↓
[5] aplicar_regras() — pós-processamento que garante as regras independente do modelo
       ↓
Resposta em português
```

---

## Tecnologias

| Tecnologia | Função |
|---|---|
| [DSPy](https://dspy.ai) | Framework para construção do agente com Signatures, Modules e Otimizadores |
| [Ollama](https://ollama.com) | Execução local do modelo de linguagem |
| [Phi-3.5-mini (3.8B)](https://ollama.com/library/phi3.5) | Modelo LLM — melhor desempenho em raciocínio estruturado e SQL entre modelos open source até 4B |
| [python-telegram-bot](https://python-telegram-bot.org/) | Interface via Telegram (polling assíncrono) |
| SQLite | Banco de dados local de medicamentos |
| Python 3.10+ | Linguagem principal |

---

## Estrutura do projeto

```
├── agente.py               # Núcleo do agente (DSPy + SQLite + pós-processamento)
├── telegram_bot.py         # Bot do Telegram
├── requirements.txt        # Dependências Python
├── medicamentos.db         # Banco de dados SQLite (gerado automaticamente)
├── agente_otimizado.json   # Agente compilado pelo otimizador (gerado na 1ª execução)
└── README.md
```

---

## Pré-requisitos

- Python 3.10+
- [Ollama](https://ollama.com/download) instalado

---

## Instalação e execução (local)

**1. Clone o repositório**
```bash
git clone https://github.com/gustav0-gg/Atividade-de-IHC
cd Atividade-de-IHC
```

**2. Crie e ative o ambiente virtual**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

**3. Instale as dependências**
```bash
pip install -r requirements.txt
```

**4. Baixe o modelo**
```bash
ollama pull phi3.5
```

**5. Execute o agente (CLI)**
```bash
python agente.py
```

**6. Execute o bot do Telegram** *(opcional)*
```bash
export TELEGRAM_TOKEN="SEU_TOKEN_AQUI"   # Mac/Linux
set TELEGRAM_TOKEN=SEU_TOKEN_AQUI        # Windows

python telegram_bot.py
```

> Na **primeira execução** o otimizador BootstrapFewShot vai rodar (pode levar alguns minutos). Nas execuções seguintes o agente carrega instantaneamente do arquivo `agente_otimizado.json`.

---

## Setup no Google Colab

### 1. Instalar dependências
```python
!pip install dspy-ai requests python-telegram-bot -q
```

### 2. Instalar e iniciar o Ollama
```bash
!curl -fsSL https://ollama.com/install.sh | sh
!nohup ollama serve > /dev/null 2>&1 &
!sleep 5
```

### 3. Baixar o modelo
```bash
!ollama pull phi3.5
```

### 4. Rodar a CLI interativa
```python
%run agente.py
```

### 5. Rodar o bot do Telegram
```python
import os
os.environ["TELEGRAM_TOKEN"] = "SEU_TOKEN_AQUI"
%run telegram_bot.py
```

---

## Bot do Telegram

### Como obter um token
1. Abra o Telegram e fale com **@BotFather**
2. Envie `/newbot` e siga as instruções
3. Copie o token fornecido

### Comandos disponíveis

| Comando | Descrição |
|---|---|
| `/start` | Mensagem de boas-vindas |
| `/help` | Exemplos de perguntas |
| `/sobre` | Informações sobre o bot |

### Recursos implementados
- **Typing indicator** — exibe "digitando..." enquanto o modelo processa
- **Rate limiting** — máximo de 5 mensagens por minuto por usuário
- **Thread pool** — o agente síncrono não bloqueia o event loop assíncrono
- **Fallback de formatação** — tenta Markdown; se falhar, envia texto simples

---


## Banco de dados

O banco é criado automaticamente na primeira execução com 3 tabelas:

**`medicamentos`** — 12 medicamentos com nome comercial, princípio ativo, categoria, dosagem, forma, necessidade de receita, fabricante e preço médio.

**`interacoes`** — 5 interações medicamentosas classificadas por severidade (leve, moderada, grave) com descrição do risco.

**`fabricantes`** — 5 fabricantes com nome e país de origem (EMS, Medley, Bayer, Pfizer, Eurofarma).

---

## Conceitos DSPy aplicados

### Signatures
Definem o contrato de entrada e saída de cada etapa do pipeline. Foram criadas 4:

| Signature | Função |
|---|---|
| `ClassificarPergunta` | Categoriza a pergunta antes de processar |
| `GerarSQL` | Converte pergunta em português para query SQL |
| `CorrigirSQL` | Corrige SQL inválido com base na mensagem de erro do SQLite |
| `InterpretarResultado` | Transforma resultado do banco em resposta humanizada |

### Modules
`AgenteConsultaMedicamentos` orquestra o pipeline completo usando `ChainOfThought` (raciocínio passo a passo) em cada etapa, com retry automático via `CorrigirSQL` em caso de erro.

### Otimizador
`BootstrapFewShot` testa o agente em exemplos de treino, seleciona automaticamente os melhores casos onde o SQL gerado foi correto e os injeta como few-shot nos prompts — sem precisar escolher exemplos manualmente.

### `aplicar_regras()` — pós-processamento garantido
Modelos ≤4B frequentemente ignoram parte das instruções nos prompts. A solução foi garantir as regras via código, **depois** da geração:

- **Preço** — removido automaticamente se a pergunta não mencionar preço/custo/valor
- **Linguagem de dosagem** — corrige `"500mg por vez"` → `"500mg"`
- **Termos técnicos** — SQL, banco de dados, query nunca chegam ao usuário
- **Formato BR** — `R$ 28.00` → `R$ 28,00`

---

## Exemplos de uso

```
💊 AGENTE DE CONSULTA DE MEDICAMENTOS
   Digite 'sair' para encerrar

Você: Quais antibióticos estão cadastrados?
🤖 Agente: Os antibióticos disponíveis são Amoxicilina (amoxicilina, 500mg, cápsula)
           e Azitromicina (azitromicina, 500mg, comprimido). Ambos exigem receita médica.

Você: Qual o preço da Aspirina?
🤖 Agente: O preço médio da Aspirina é R$ 15,00 por caixa (valor aproximado).

Você: A Aspirina pode reagir com outro medicamento?
🤖 Agente: ⚠️ Sim. A Aspirina possui duas interações registradas:
           • GRAVE — Com Ibuprofeno: aumenta o risco de sangramento.
           • MODERADA — Com Metformina: pode mascarar sintomas de hipoglicemia.
           Consulte sempre um médico antes de combinar esses medicamentos.

Você: Como está o clima hoje?
🤖 Agente: Sou especializado em consultas sobre medicamentos. Posso ajudar
           com remédios, dosagens, interações e fabricantes. 💊
```

---

> ⚠️ **Aviso**: Este projeto é educacional e não substitui orientação médica ou farmacêutica profissional.
