"""
Agente de Consulta de Medicamentos — DSPy + Ollama (phi3.5 / ≤4B)
Compatible with Google Colab.

Variáveis de ambiente (opcionais):
  OLLAMA_MODEL  → modelo a usar (padrão: phi3.5)
  OLLAMA_URL    → endereço do servidor (padrão: http://localhost:11434)

No Colab, instale o Ollama com:
  !curl -fsSL https://ollama.com/install.sh | sh
  !nohup ollama serve > /dev/null 2>&1 &
  !sleep 5 && ollama pull phi3.5
"""

import os
import re
import dspy
import sqlite3
import requests
from typing import Optional

# ─────────────────────────────────────────────────────────────
DB_PATH    = "medicamentos.db"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "phi3.5")
OLLAMA_URL = os.getenv("OLLAMA_URL",  "http://localhost:11434")

_PRICE_KW = frozenset({
    "preço", "preco", "custo", "custa", "caro", "barato",
    "valor", "quanto custa", "quanto fica", "quanto é",
    "quanto vale", "econômico", "economico",
})

# ═════════════════════════════════════════════════════════════
#  CONFIGURAÇÃO
# ═════════════════════════════════════════════════════════════
def setup(check_ollama: bool = True) -> None:
    if check_ollama:
        try:
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        except Exception:
            print(f"❌  Ollama não detectado em {OLLAMA_URL}")
            print("    Execute em outro terminal: ollama serve")
            raise SystemExit(1)

    dspy.settings.configure(
        lm=dspy.LM(
            model=f"ollama/{MODEL_NAME}",
            api_base=OLLAMA_URL,
            max_tokens=400,
            temperature=0.2,   # baixo = respostas mais previsíveis
        )
    )
    print(f"✅  DSPy configurado → modelo: {MODEL_NAME}")


# ═════════════════════════════════════════════════════════════
#  BANCO DE DADOS
# ═════════════════════════════════════════════════════════════
def create_database(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS medicamentos (
        id INTEGER PRIMARY KEY, nome_comercial TEXT, principio_ativo TEXT,
        categoria TEXT, dosagem TEXT, forma TEXT,
        necessita_receita INTEGER, fabricante_id INTEGER, preco_medio REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS interacoes (
        id INTEGER PRIMARY KEY, medicamento_id1 INTEGER, medicamento_id2 INTEGER,
        severidade TEXT, descricao TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS fabricantes (
        id INTEGER PRIMARY KEY, nome TEXT, pais TEXT
    )""")

    c.executemany("INSERT OR IGNORE INTO fabricantes VALUES (?,?,?)", [
        (1, "EMS",      "Brasil"),
        (2, "Medley",   "Brasil"),
        (3, "Bayer",    "Alemanha"),
        (4, "Pfizer",   "EUA"),
        (5, "Eurofarma","Brasil"),
    ])
    c.executemany("INSERT OR IGNORE INTO medicamentos VALUES (?,?,?,?,?,?,?,?,?)", [
        (1,  "Dipirona Sódica",  "dipirona",               "analgésico",        "500mg", "comprimido", 0, 1,  8.50),
        (2,  "Paracetamol",      "paracetamol",             "analgésico",        "750mg", "comprimido", 0, 2, 12.00),
        (3,  "Aspirina",         "ácido acetilsalicílico",  "anti-inflamatório", "500mg", "comprimido", 0, 3, 15.00),
        (4,  "Ibuprofeno",       "ibuprofeno",              "anti-inflamatório", "600mg", "comprimido", 0, 5, 18.00),
        (5,  "Amoxicilina",      "amoxicilina",             "antibiótico",       "500mg", "cápsula",    1, 1, 22.00),
        (6,  "Azitromicina",     "azitromicina",            "antibiótico",       "500mg", "comprimido", 1, 2, 35.00),
        (7,  "Omeprazol",        "omeprazol",               "protetor gástrico", "20mg",  "cápsula",    0, 4, 28.00),
        (8,  "Loratadina",       "loratadina",              "antialérgico",      "10mg",  "comprimido", 0, 5, 14.00),
        (9,  "Metformina",       "metformina",              "antidiabético",     "850mg", "comprimido", 1, 1, 19.00),
        (10, "Enalapril",        "enalapril",               "anti-hipertensivo", "10mg",  "comprimido", 1, 3, 24.00),
        (11, "Atorvastatina",    "atorvastatina",           "colesterol",        "20mg",  "comprimido", 1, 4, 45.00),
        (12, "Dexametasona",     "dexametasona",            "corticosteroide",   "4mg",   "comprimido", 1, 2, 16.00),
    ])
    c.executemany("INSERT OR IGNORE INTO interacoes VALUES (?,?,?,?,?)", [
        (1, 3,  9, "moderada", "Aspirina pode mascarar hipoglicemia causada por Metformina"),
        (2, 5,  6, "grave",    "Uso simultâneo de dois antibióticos aumenta risco de resistência"),
        (3, 3,  4, "grave",    "Combinação de Aspirina e Ibuprofeno aumenta risco de sangramento"),
        (4, 10, 4, "moderada", "Ibuprofeno pode reduzir efeito anti-hipertensivo do Enalapril"),
        (5, 11, 12,"leve",     "Dexametasona pode aumentar risco de miopatia com estatinas"),
    ])
    conn.commit()
    conn.close()
    print(f"✅  Banco '{db_path}' pronto")


# ═════════════════════════════════════════════════════════════
#  SIGNATURES  (simplificadas para modelos ≤4B)
# ═════════════════════════════════════════════════════════════
class ClassificarPergunta(dspy.Signature):
    """
    Classifique a pergunta sobre medicamentos.
    Retorne APENAS uma palavra da lista abaixo — sem pontuação:
      consulta   → perguntas sobre remédios, dosagem, receita, princípio ativo
      interacao  → perguntas sobre combinar ou interagir medicamentos
      fabricante → perguntas sobre quem fabrica ou distribui
      fora_escopo → qualquer assunto que NÃO seja sobre medicamentos
    """
    pergunta  = dspy.InputField(desc="Pergunta do usuário")
    categoria = dspy.OutputField(
        desc="Uma palavra: consulta | interacao | fabricante | fora_escopo"
    )


class GerarSQL(dspy.Signature):
    """
    Converta a pergunta em SQL SELECT para SQLite.

    Esquema:
      medicamentos(id, nome_comercial, principio_ativo, categoria, dosagem,
                   forma, necessita_receita, fabricante_id, preco_medio)
      interacoes(id, medicamento_id1, medicamento_id2, severidade, descricao)
      fabricantes(id, nome, pais)

    Regras OBRIGATÓRIAS:
    - SEMPRE use LIKE '%termo%' para buscar por nome — NUNCA use '='
    - Retorne SOMENTE o SQL, sem markdown, sem backticks, sem explicações
    - Use apenas SELECT (nunca INSERT, UPDATE, DELETE)
    """
    pergunta  = dspy.InputField(desc="Pergunta em português")
    sql_query = dspy.OutputField(desc="SQL SELECT válido para SQLite")


class CorrigirSQL(dspy.Signature):
    """Corrija o SQL com base no erro do SQLite. Retorne apenas o SQL correto."""
    pergunta      = dspy.InputField(desc="Pergunta original")
    sql_com_erro  = dspy.InputField(desc="SQL que gerou o erro")
    mensagem_erro = dspy.InputField(desc="Mensagem de erro do SQLite")
    sql_corrigida = dspy.OutputField(desc="SQL corrigido e válido para SQLite")


class InterpretarResultado(dspy.Signature):
    """
    Você é um farmacêutico virtual. Responda à pergunta com base nos dados.

    Regras:
    - Responda em português claro e conciso
    - Use APENAS os dados fornecidos; nunca invente informações
    - NÃO mencione banco de dados, SQL, tabela ou query
    - Dosagem = concentração do princípio ativo (ex: '500mg por comprimido')
    - Para interações graves, inclua aviso de segurança em destaque
    """
    pergunta     = dspy.InputField(desc="Pergunta do usuário")
    resultado_db = dspy.InputField(desc="Dados retornados pelo banco de dados")
    resposta     = dspy.OutputField(desc="Resposta em português sobre medicamentos")


# ═════════════════════════════════════════════════════════════
#  FUNÇÕES AUXILIARES
# ═════════════════════════════════════════════════════════════
def extrair_sql(texto: str) -> str:
    """Extrai SQL de forma robusta da saída do modelo (lida com markdown, prose, etc.)."""
    # 1. Bloco ```sql ... ```
    m = re.search(r"```sql\s*([\s\S]+?)\s*```", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(";")

    # 2. Bloco ``` ... ``` genérico contendo SELECT
    m = re.search(r"```\s*(SELECT[\s\S]+?)\s*```", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(";")

    # 3. SELECT até fim de parágrafo / fim de string
    m = re.search(r"(SELECT\s[\s\S]+?)(?:;\s*\n|;\s*$|\n\n|$)", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(";")

    # 4. Primeira linha que começa com SELECT
    for line in texto.splitlines():
        if re.match(r"\s*SELECT\s", line, re.IGNORECASE):
            return line.strip().rstrip(";")

    # 5. Fallback: limpa backticks e prefixo "sql"
    return texto.strip().strip("`").lstrip("sql").strip().rstrip(";")


def e_pergunta_preco(pergunta: str) -> bool:
    """Retorna True se a pergunta for explicitamente sobre preço / custo."""
    p = pergunta.lower()
    return any(kw in p for kw in _PRICE_KW)


def aplicar_regras(resposta: str, pergunta: str) -> str:
    """
    Pós-processamento que GARANTE as regras de resposta independente do modelo.
    Chamado após cada geração para compensar o que o LLM ≤4B ignora.
    """
    # ── Regra 1: Remover preço quando não foi perguntado ─────
    if not e_pergunta_preco(pergunta):
        padroes_preco = [
            r",?\s+(?:com\s+)?preço\s+médio\s+(?:de|é|:)\s*R\$\s*[\d.,]+",
            r",?\s+(?:ao\s+preço|no\s+valor)\s+de\s+R\$\s*[\d.,]+",
            r",?\s+(?:custa|custando|vendido\s+por|por\s+apenas)\s+R\$\s*[\d.,]+",
            r",?\s+R\$\s*[\d.,]+(?:\s*(?:por|a|cada)\s+\w+)?",
            r"\s+com\s+valor\s+(?:médio\s+)?(?:de\s+)?R\$\s*[\d.,]+",
        ]
        for padrao in padroes_preco:
            resposta = re.sub(padrao, "", resposta, flags=re.IGNORECASE)

        # Remove frases/sentenças inteiras que mencionem preço
        sentencas = re.split(r"(?<=[.!?])\s+", resposta)
        sentencas = [
            s for s in sentencas
            if not re.search(
                r"\b(?:preço|custo|custa|valor\s+(?:de|médio)|caro|barato|R\$)\b",
                s, re.IGNORECASE
            )
        ]
        resposta = " ".join(sentencas)

    # ── Regra 2: Formatar preços no padrão brasileiro ────────
    # "R$ 28.00" → "R$ 28,00"
    resposta = re.sub(
        r"(R\$\s*)(\d+)\.(\d{1,2})\b",
        lambda m: f"{m.group(1)}{m.group(2)},{m.group(3).ljust(2, '0')}",
        resposta,
    )

    # ── Regra 3: Corrigir linguagem de dosagem ───────────────
    # Remove "por vez / por dose / por tomada" após valores de concentração
    resposta = re.sub(
        r"(\d+\s*(?:mg|g|ml|mcg|UI|μg))\s+"
        r"(?:por\s+(?:vez|dose|tomada|administração)|a\s+cada\s+\d+\s*h)",
        r"\1",
        resposta,
        flags=re.IGNORECASE,
    )

    # ── Regra 4: Remover termos técnicos de SQL / BD ─────────
    resposta = re.sub(
        r"\b(?:banco\s+de\s+dados|query|sql\b|SELECT\b|FROM\s+\w+|WHERE\b"
        r"|JOIN\b|NULL\b|tabela\s+\w+|resultado\s+do\s+banco)\b",
        "",
        resposta,
        flags=re.IGNORECASE,
    )

    # ── Limpeza final ─────────────────────────────────────────
    resposta = re.sub(r" {2,}", " ", resposta)      # espaços duplos
    resposta = re.sub(r" ([.,;:!?])", r"\1", resposta)  # espaço antes de pontuação
    resposta = resposta.strip(" .,")

    return resposta


# ═════════════════════════════════════════════════════════════
#  MÓDULO DSPy (Agente)
# ═════════════════════════════════════════════════════════════
class AgenteConsultaMedicamentos(dspy.Module):
    def __init__(self, db_path: str = DB_PATH):
        super().__init__()
        self.db_path       = db_path
        self.classificador = dspy.Predict(ClassificarPergunta)
        self.gerador_sql   = dspy.ChainOfThought(GerarSQL)
        self.corrigir_sql  = dspy.Predict(CorrigirSQL)
        self.interpretador = dspy.ChainOfThought(InterpretarResultado)

    def forward(self, pergunta: str) -> dspy.Prediction:

        # ── 1. Classificar a pergunta ─────────────────────────
        categoria_raw = self.classificador(pergunta=pergunta).categoria.lower().strip()
        categoria = next(
            (c for c in ("consulta", "interacao", "fabricante") if c in categoria_raw),
            "fora_escopo",
        )

        if categoria == "fora_escopo":
            return dspy.Prediction(
                categoria="fora_escopo", sql_query=None, resultado_db=None,
                resposta=(
                    "Sou especializado em consultas sobre medicamentos. Posso "
                    "ajudar com remédios, dosagens, interações e fabricantes. 💊"
                ),
                erro=None,
            )

        # ── 2. Gerar SQL ──────────────────────────────────────
        saida_sql = self.gerador_sql(pergunta=pergunta)
        sql       = extrair_sql(saida_sql.sql_query)

        # ── 3. Executar SQL (com retry automático) ────────────
        conn = sqlite3.connect(self.db_path)
        try:
            resultado = conn.execute(sql).fetchall()

        except Exception as err1:
            # Tenta corrigir o SQL automaticamente
            try:
                sql_corrigido = self.corrigir_sql(
                    pergunta=pergunta,
                    sql_com_erro=sql,
                    mensagem_erro=str(err1),
                ).sql_corrigida
                sql      = extrair_sql(sql_corrigido)
                resultado = conn.execute(sql).fetchall()

            except Exception as err2:
                conn.close()
                return dspy.Prediction(
                    categoria=categoria, sql_query=sql, resultado_db=None,
                    resposta="Não consegui recuperar as informações. Tente reformular a pergunta.",
                    erro=str(err2),
                )
        conn.close()

        # ── 4. Interpretar resultado ──────────────────────────
        resultado_fmt = str(resultado[:10]) if resultado else "Nenhum resultado encontrado."
        resposta = self.interpretador(
            pergunta=pergunta,
            resultado_db=resultado_fmt,
        ).resposta

        return dspy.Prediction(
            categoria=categoria, sql_query=sql,
            resultado_db=resultado, resposta=resposta, erro=None,
        )


# ═════════════════════════════════════════════════════════════
#  OTIMIZADOR (BootstrapFewShot)
# ═════════════════════════════════════════════════════════════
_EXEMPLOS_TREINO = [
    dspy.Example(
        pergunta="Quais medicamentos são antibióticos?",
        sql_query=(
            "SELECT nome_comercial, principio_ativo "
            "FROM medicamentos WHERE categoria = 'antibiótico'"
        ),
    ).with_inputs("pergunta"),

    dspy.Example(
        pergunta="Quais remédios não precisam de receita?",
        sql_query=(
            "SELECT nome_comercial, categoria "
            "FROM medicamentos WHERE necessita_receita = 0"
        ),
    ).with_inputs("pergunta"),

    dspy.Example(
        pergunta="Existe interação grave entre medicamentos?",
        sql_query=(
            "SELECT m1.nome_comercial, m2.nome_comercial, i.descricao "
            "FROM interacoes i "
            "JOIN medicamentos m1 ON i.medicamento_id1 = m1.id "
            "JOIN medicamentos m2 ON i.medicamento_id2 = m2.id "
            "WHERE i.severidade = 'grave'"
        ),
    ).with_inputs("pergunta"),

    dspy.Example(
        pergunta="Quais medicamentos são fabricados no Brasil?",
        sql_query=(
            "SELECT m.nome_comercial, f.nome FROM medicamentos m "
            "JOIN fabricantes f ON m.fabricante_id = f.id "
            "WHERE f.pais = 'Brasil'"
        ),
    ).with_inputs("pergunta"),

    dspy.Example(
        pergunta="Quais remédios são para pressão alta?",
        sql_query=(
            "SELECT nome_comercial, principio_ativo, necessita_receita "
            "FROM medicamentos WHERE categoria = 'anti-hipertensivo'"
        ),
    ).with_inputs("pergunta"),

    dspy.Example(
        pergunta="A Dipirona precisa de receita?",
        sql_query=(
            "SELECT nome_comercial, necessita_receita "
            "FROM medicamentos WHERE nome_comercial LIKE '%Dipirona%'"
        ),
    ).with_inputs("pergunta"),
]


def _metrica_sql(exemplo, pred, trace=None) -> bool:
    """Métrica: ≥50% das palavras-chave esperadas presentes no SQL gerado."""
    esperado = exemplo.sql_query.lower()
    gerado   = (pred.sql_query or "").lower()
    stopwords = {"select", "where", "from", "order", "group", "limit", "count", "join", "on"}
    palavras  = [w for w in esperado.split() if len(w) > 4 and w not in stopwords]
    if not palavras:
        return False
    acertos = sum(1 for p in palavras if p in gerado)
    return (acertos / len(palavras)) >= 0.5


def build_agent(
    db_path: str = DB_PATH,
    cache_path: str = "agente_otimizado.json",
) -> AgenteConsultaMedicamentos:
    from dspy.teleprompt import BootstrapFewShot

    agente = AgenteConsultaMedicamentos(db_path=db_path)

    if os.path.exists(cache_path):
        print(f"⚡  Carregando agente de '{cache_path}'...")
        agente.load(cache_path)
        return agente

    print("🔧  Otimizando agente pela primeira vez (pode demorar ~2 min)...")
    otimizador = BootstrapFewShot(
        metric=_metrica_sql,
        max_bootstrapped_demos=3,
        max_labeled_demos=3,
    )
    agente = otimizador.compile(agente, trainset=_EXEMPLOS_TREINO)
    agente.save(cache_path)
    print(f"✅  Agente otimizado salvo em '{cache_path}'")
    return agente


# ═════════════════════════════════════════════════════════════
#  CLI INTERATIVA
# ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    setup()
    create_database()
    agente = build_agent()

    print("\n" + "=" * 55)
    print("💊  AGENTE DE CONSULTA DE MEDICAMENTOS")
    print("    Digite 'sair' para encerrar | 'debug' para ver SQL")
    print("=" * 55)

    debug_mode = False
    while True:
        try:
            pergunta = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando...")
            break

        if not pergunta:
            continue
        if pergunta.lower() in ("sair", "exit", "quit"):
            print("Até mais! 💊")
            break
        if pergunta.lower() == "debug":
            debug_mode = not debug_mode
            print(f"[Debug {'ativado' if debug_mode else 'desativado'}]")
            continue

        resultado = agente(pergunta=pergunta)
        resposta  = aplicar_regras(resultado.resposta, pergunta)
        print(f"\n🤖  Agente: {resposta}")

        if debug_mode and resultado.sql_query:
            print(f"    [SQL] {resultado.sql_query}")
            print(f"    [Cat] {resultado.categoria}")