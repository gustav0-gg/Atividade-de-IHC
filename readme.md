# 💊 Agente de Consulta de Medicamentos

Agente de IA para consulta de medicamentos em linguagem natural, desenvolvido com **DSPy** e **Phi-3.5-mini (3.8B)** rodando localmente via Ollama. O agente interpreta perguntas em português, gera queries SQL automaticamente e retorna respostas humanizadas.

Projeto desenvolvido para a disciplina de **Modelo de Linguagem** — FATEC, 3º Semestre.

---

## Como funciona

O usuário digita uma pergunta em português. O agente passa por um pipeline de 3 etapas antes de responder:

```
Pergunta do usuário
       ↓
[1] Classificar — identifica se é consulta, interação, fabricante ou fora do escopo
       ↓
[2] Gerar SQL — converte a pergunta em query para o banco de medicamentos
       ↓
[3] Interpretar — transforma o resultado do banco em resposta humanizada
       ↓
Resposta em português
```

---

## Tecnologias

| Tecnologia | Função |
|---|---|
| [DSPy](https://dspy.ai) | Framework para construção do agente com Signatures, Modules e Otimizadores |
| [Ollama](https://ollama.com) | Execução local do modelo de linguagem |
| [Phi-3.5-mini (3.8B)](https://ollama.com/library/phi3.5) | Modelo LLM — escolhido por melhor desempenho em raciocínio estruturado e geração de SQL entre modelos open source até 4B |
| SQLite | Banco de dados local de medicamentos |
| Python 3.10+ | Linguagem principal |

---

## Estrutura do projeto

```
├── agente.py               # Código principal do agente
├── medicamentos.db         # Banco de dados SQLite (gerado automaticamente)
├── agente_otimizado.json   # Agente compilado pelo otimizador (gerado na 1ª execução)
└── README.md
```

---

## Pré-requisitos

- Python 3.10+
- [Ollama](https://ollama.com/download) instalado

---

## Instalação e execução

**1. Clone o repositório**
```bash
git clone https://github.com/gustav0-gg/Atividade-de-IHC
cd seu-repositorio
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
pip install dspy-ai requests
```

**4. Baixe o modelo**
```bash
ollama pull phi3.5
```

**5. Execute o agente**
```bash
python agente.py
```

> Na **primeira execução** o otimizador BootstrapFewShot vai rodar (pode levar alguns minutos). Nas execuções seguintes o agente carrega instantaneamente do arquivo `agente_otimizado.json`.

---

## Banco de dados

O banco é criado automaticamente na primeira execução com 3 tabelas:

**`medicamentos`** — 12 medicamentos cadastrados com nome comercial, princípio ativo, categoria, dosagem, forma, necessidade de receita, fabricante e preço médio.

**`interacoes`** — 5 interações medicamentosas classificadas por severidade (leve, moderada, grave) com descrição do risco.

**`fabricantes`** — 5 fabricantes com nome e país de origem (EMS, Medley, Bayer, Pfizer, Eurofarma).

---

## Conceitos DSPy aplicados

### Signatures
Definem o contrato de entrada e saída de cada etapa do pipeline. Foram criadas 3:

- `GerarSQL` — converte pergunta em português para query SQL
- `InterpretarResultado` — transforma resultado do banco em resposta humanizada
- `ClassificarPergunta` — categoriza a pergunta antes de processá-la

### Modules
`AgenteConsultaMedicamentos` orquestra o pipeline completo usando `ChainOfThought` (raciocínio passo a passo) em cada etapa, com fallback automático de correção de SQL em caso de erro.

### Otimizador
`BootstrapFewShot` testa o agente em exemplos de treino, seleciona automaticamente os melhores casos onde o SQL gerado foi correto e os injeta como few-shot nos prompts — sem precisar escolher os exemplos manualmente.

---

## Exemplos de uso

```
💊 AGENTE DE CONSULTA DE MEDICAMENTOS
   Digite 'sair' para encerrar

Você: Quais antibióticos estão cadastrados?
🤖 Agente: Os antibióticos registrados no nosso sistema são Amoxicilina e Azitromicina. Esses fármacos são utilizados para tratar infecções bacterianas, mas é crucial que sejam prescritos por um profissional de saúde devido ao risco de resistência bacteriana e outras possífalidades relacionadas à automedicação.

Você: Qual o preço da aspirina?
🤖 Agente: O preço médio de uma aspirina é R$ 15,00. Este valor pode variar conforme a loja e o fornecedor, portanto, para obter informações mais precisas, consulte os detalhes específicos da farmácia ou distribuidora em questão.

Você: A aspirina pode reagir com outro medicamento?
🤖 Agente: A Aspirina pode interferir na percepção dos baixos níveis de glicose pelo uso concomitante com a Metformina, tornando mais difícil reconhecer os sintomas da hipoglicemia. Além disso, ao tomar simultaneamente Ibuprofeno, o risco de sangramento pode ser maior devido à interação entre esses dois medicamentos.
```