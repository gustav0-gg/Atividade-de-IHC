# agente.py
import os
import re
import dspy
import sqlite3
import requests

# ── Configuração ──────────────────────────────────────────────
def setup():
    try:
        requests.get("http://localhost:11434/api/tags", timeout=3)
        # print("✅ Ollama está rodando")
    except Exception:
        print("❌ Ollama não está rodando.")
        print("   Abra outro terminal e rode: ollama serve")
        exit(1)

    dspy.settings.configure(
        lm=dspy.LM(
            model="ollama/phi3.5",
            api_base="http://localhost:11434",
            max_tokens=300,
            temperature=0.3,
        )
    )

# ── Banco de dados ────────────────────────────────────────────
def create_database():
    conn = sqlite3.connect("medicamentos.db")
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
        (1,"EMS","Brasil"),(2,"Medley","Brasil"),(3,"Bayer","Alemanha"),
        (4,"Pfizer","EUA"),(5,"Eurofarma","Brasil"),
    ])
    c.executemany("INSERT OR IGNORE INTO medicamentos VALUES (?,?,?,?,?,?,?,?,?)", [
        (1,"Dipirona Sódica","dipirona","analgésico","500mg","comprimido",0,1,8.50),
        (2,"Paracetamol","paracetamol","analgésico","750mg","comprimido",0,2,12.00),
        (3,"Aspirina","ácido acetilsalicílico","anti-inflamatório","500mg","comprimido",0,3,15.00),
        (4,"Ibuprofeno","ibuprofeno","anti-inflamatório","600mg","comprimido",0,5,18.00),
        (5,"Amoxicilina","amoxicilina","antibiótico","500mg","cápsula",1,1,22.00),
        (6,"Azitromicina","azitromicina","antibiótico","500mg","comprimido",1,2,35.00),
        (7,"Omeprazol","omeprazol","protetor gástrico","20mg","cápsula",0,4,28.00),
        (8,"Loratadina","loratadina","antialérgico","10mg","comprimido",0,5,14.00),
        (9,"Metformina","metformina","antidiabético","850mg","comprimido",1,1,19.00),
        (10,"Enalapril","enalapril","anti-hipertensivo","10mg","comprimido",1,3,24.00),
        (11,"Atorvastatina","atorvastatina","colesterol","20mg","comprimido",1,4,45.00),
        (12,"Dexametasona","dexametasona","corticosteroide","4mg","comprimido",1,2,16.00),
    ])
    c.executemany("INSERT OR IGNORE INTO interacoes VALUES (?,?,?,?,?)", [
        (1,3,9,"moderada","Aspirina pode mascarar hipoglicemia causada por Metformina"),
        (2,5,6,"grave","Uso simultâneo de dois antibióticos aumenta risco de resistência"),
        (3,3,4,"grave","Combinação de Aspirina e Ibuprofeno aumenta risco de sangramento"),
        (4,10,4,"moderada","Ibuprofeno pode reduzir efeito anti-hipertensivo do Enalapril"),
        (5,11,12,"leve","Dexametasona pode aumentar risco de miopatia com estatinas"),
    ])
    conn.commit()
    conn.close()

# ── Signatures ────────────────────────────────────────────────
class GerarSQL(dspy.Signature):
    """
    Você é um especialista em SQL para base de dados farmacêutica.
    Converta a pergunta em linguagem natural para uma query SQL válida.

    Esquema:
    - medicamentos: id, nome_comercial, principio_ativo, categoria, dosagem,
                    forma, necessita_receita (1=sim/0=nao), fabricante_id, preco_medio
    - interacoes: id, medicamento_id1, medicamento_id2, severidade, descricao
    - fabricantes: id, nome, pais

    Regras:
    - Use apenas SELECT
    - Para nomes de medicamentos, SEMPRE use LIKE com % nos dois lados:
      WHERE nome_comercial LIKE '%dipirona%'  ← CORRETO
      WHERE nome_comercial = 'dipirona'       ← ERRADO
    - Retorne apenas a query SQL, sem explicações
    """
    pergunta  = dspy.InputField(desc="Pergunta sobre medicamentos em português")
    sql_query = dspy.OutputField(desc="Query SQL válida para SQLite")

class InterpretarResultado(dspy.Signature):
    """
    Você é um farmacêutico virtual amigável.
    Transforme o resultado SQL em uma resposta clara em português.
    Se houver interações graves, destaque com aviso de segurança.
    Nunca invente informações que não estão nos dados.

    Regras de resposta:
    - Todos os valores de preço estão em reais (R$)
    - Quando for dar uma resposta de valor deixa claro que é um valor aproximado
    - Nunca invente informações
    """
    pergunta     = dspy.InputField(desc="Pergunta original do usuário")
    sql_query    = dspy.InputField(desc="Query SQL executada")
    resultado_db = dspy.InputField(desc="Resultado do banco de dados")
    resposta     = dspy.OutputField(desc="Resposta clara em português. "
            "Preços SEMPRE em R$ (ex: R$ 8,50). "
            "Para preços, diga que é um valor aproximado. "
            "Nunca invente informações.")

class ClassificarPergunta(dspy.Signature):
    """
    Classifique a pergunta em uma categoria.
    Retorne apenas uma palavra: consulta, interacao, fabricante ou outro
    """
    pergunta  = dspy.InputField(desc="Pergunta do usuário")
    categoria = dspy.OutputField(desc="Uma palavra: consulta, interacao, fabricante ou outro")

# ── Módulo (Agente) ───────────────────────────────────────────
class AgenteConsultaMedicamentos(dspy.Module):
    def __init__(self, db_path="medicamentos.db"):  
        super().__init__()
        self.db_path       = db_path                
        self.classificador = dspy.Predict(ClassificarPergunta)
        self.gerador_sql   = dspy.ChainOfThought(GerarSQL)
        self.interpretador = dspy.ChainOfThought(InterpretarResultado)
        self.refinador     = dspy.ChainOfThought(
            "pergunta, sql_query, erro -> sql_corrigida"
        )

    def forward(self, pergunta):                    
        conn = sqlite3.connect(self.db_path)        

        classificacao = self.classificador(pergunta=pergunta)

        if "outro" in classificacao.categoria.lower():
            conn.close()
            return dspy.Prediction(
                categoria="outro", sql_query=None, resultado_db=None,
                resposta="Só consigo responder perguntas sobre medicamentos cadastrados.",
                erro=None
            )

        saida_sql = self.gerador_sql(pergunta=pergunta)
        sql = saida_sql.sql_query.strip().strip("`").replace("sql\n", "", 1).strip()

        try:
            cursor    = conn.execute(sql)
            resultado = cursor.fetchall()
        except Exception as e:
            try:
                refinamento = self.refinador(pergunta=pergunta, sql_query=sql, erro=str(e))
                sql         = refinamento.sql_corrigida.strip().strip("`").replace("sql\n","",1).strip()
                cursor      = conn.execute(sql)
                resultado   = cursor.fetchall()
            except Exception as e2:
                conn.close()
                return dspy.Prediction(
                    categoria=classificacao.categoria, sql_query=sql,
                    resultado_db=None,
                    resposta=f"Erro ao processar: {str(e2)}",
                    erro=str(e2)
                )

        resultado_fmt = str(resultado[:10]) if resultado else "Nenhum resultado."
        interpretacao = self.interpretador(
            pergunta=pergunta, sql_query=sql, resultado_db=resultado_fmt
        )
        conn.close()
        return dspy.Prediction(
            categoria=classificacao.categoria, sql_query=sql,
            resultado_db=resultado, resposta=interpretacao.resposta, erro=None
        )

# ── Otimizador ────────────────────────────────────────────────
def build_agent():
    from dspy.teleprompt import BootstrapFewShot

    if os.path.exists("agente_otimizado.json"):
        print("⚡ Carregando agente já otimizado...")
        agente = AgenteConsultaMedicamentos(db_path="medicamentos.db")
        agente.load("agente_otimizado.json")
        return agente

    print("Otimizando agente (Otimização só ocorre quando roda pela primeira vez)...")
    exemplos = [
        dspy.Example(pergunta="Quais medicamentos são antibióticos?",
            sql_query="SELECT nome_comercial, principio_ativo FROM medicamentos WHERE categoria = 'antibiótico'"
        ).with_inputs("pergunta"),
        dspy.Example(pergunta="Quais remédios não precisam de receita?",
            sql_query="SELECT nome_comercial, categoria FROM medicamentos WHERE necessita_receita = 0"
        ).with_inputs("pergunta"),
        dspy.Example(pergunta="Existe interação grave entre medicamentos?",
            sql_query="SELECT m1.nome_comercial, m2.nome_comercial, i.descricao FROM interacoes i JOIN medicamentos m1 ON i.medicamento_id1 = m1.id JOIN medicamentos m2 ON i.medicamento_id2 = m2.id WHERE i.severidade = 'grave'"
        ).with_inputs("pergunta"),
        dspy.Example(pergunta="Quais medicamentos são fabricados no Brasil?",
            sql_query="SELECT m.nome_comercial, f.nome FROM medicamentos m JOIN fabricantes f ON m.fabricante_id = f.id WHERE f.pais = 'Brasil'"
        ).with_inputs("pergunta"),
    ]

    def metrica(exemplo, pred, trace=None):
        esperado = exemplo.sql_query.lower()
        gerado   = pred.sql_query.lower() if pred.sql_query else ""
        palavras = [w for w in esperado.split() if len(w) > 4 and w not in ("select","where","from","order","group","limit")]
        acertos  = sum(1 for p in palavras if p in gerado)
        return (acertos / len(palavras) if palavras else 0) >= 0.5

    otimizador = BootstrapFewShot(metric=metrica, max_bootstrapped_demos=3, max_labeled_demos=3)
    agente = otimizador.compile(
        AgenteConsultaMedicamentos(db_path="medicamentos.db"),
        trainset=exemplos
    )

    agente.save("agente_otimizado.json")
    return agente

def formatar_resposta(texto: str) -> str:
    def converter_preco(match):
        valor = float(match.group(1))
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    texto = re.sub(r'(\d+\.?\d*)\s*(unidades monetárias|unidades|reais|BRL)', converter_preco, texto)
        
    return texto

# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    setup()
    create_database()
    agente = build_agent()

    print("\n" + "="*55)
    print("💊 AGENTE DE CONSULTA DE MEDICAMENTOS")
    print("   Digite 'sair' para encerrar")
    print("="*55)

    while True:
        try:
            pergunta = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando...")
            break
        if not pergunta:
            continue
        if pergunta.lower() in ("sair", "exit", "quit"):
            print("Até mais!")
            break

        resultado = agente(pergunta=pergunta)
        resposta  = formatar_resposta(resultado.resposta)          
        print(f"\n🤖 Agente: {resposta}")
        # if resultado.sql_query:
        #     print(f"   [SQL: {resultado.sql_query}]")