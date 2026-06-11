"""
Bot do Telegram para o Agente de Medicamentos
══════════════════════════════════════════════
Requer: pip install python-telegram-bot>=20.0

Como obter um token:
  1. No Telegram, fale com @BotFather
  2. Envie /newbot e siga as instruções
  3. Copie o token gerado

Como rodar:
  Terminal → export TELEGRAM_TOKEN="SEU_TOKEN" && python telegram_bot.py
  Colab    → os.environ["TELEGRAM_TOKEN"] = "SEU_TOKEN"
             exec(open("telegram_bot.py").read())
"""

import os
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from collections import defaultdict

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError

# Importa o agente
from agente import setup, create_database, build_agent, aplicar_regras, e_pergunta_preco

# ─────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  CONFIGURAÇÕES DO BOT
# ─────────────────────────────────────────────────────────────
RATE_LIMIT_MSGS   = 5          # max mensagens por janela
RATE_LIMIT_WINDOW = 60         # janela em segundos
MAX_WORKERS       = 2          # LLM calls simultâneas (evita sobrecarga)

_DOSE_KW = frozenset({
    "tomar", "usar", "dose", "posologia",
    "quantidade", "administrar", "como usar", "como tomar",
})

# ─────────────────────────────────────────────────────────────
#  ESTADO GLOBAL
# ─────────────────────────────────────────────────────────────
agente_global: object = None
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Rate limiting por usuário: user_id → list[datetime]
_rate_log: dict = defaultdict(list)


# ─────────────────────────────────────────────────────────────
#  RATE LIMITER
# ─────────────────────────────────────────────────────────────
def _checar_rate_limit(user_id: int) -> bool:
    """Retorna True se o usuário puder enviar mais uma mensagem."""
    agora = datetime.now()
    janela = timedelta(seconds=RATE_LIMIT_WINDOW)
    _rate_log[user_id] = [t for t in _rate_log[user_id] if agora - t < janela]
    if len(_rate_log[user_id]) >= RATE_LIMIT_MSGS:
        return False
    _rate_log[user_id].append(agora)
    return True


# ─────────────────────────────────────────────────────────────
#  ENVIO SEGURO (Markdown com fallback para texto simples)
# ─────────────────────────────────────────────────────────────
async def _enviar(update: Update, texto: str) -> None:
    """Tenta Markdown; se falhar, envia como texto simples."""
    try:
        await update.message.reply_text(texto, parse_mode="Markdown")
    except BadRequest:
        await update.message.reply_text(texto)


# ─────────────────────────────────────────────────────────────
#  COMANDOS
# ─────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nome = (update.effective_user.first_name or "Usuário").split()[0]
    await _enviar(
        update,
        f"💊 Olá, *{nome}*\\! Sou o *Agente Farmacêutico Virtual* 🤖\n\n"
        "Posso responder perguntas sobre:\n"
        "• Medicamentos e princípios ativos\n"
        "• Interações medicamentosas ⚠️\n"
        "• Necessidade de receita médica 📋\n"
        "• Dosagens e formas farmacêuticas\n"
        "• Fabricantes\n\n"
        "📌 Use /help para ver exemplos de perguntas\\.\n\n"
        "⚠️ _Sou apenas informativo\\. Consulte sempre um profissional de saúde\\._",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _enviar(
        update,
        "🔍 *Exemplos de perguntas:*\n\n"
        "• Quais antibióticos estão disponíveis?\n"
        "• A Dipirona precisa de receita?\n"
        "• Existe interação entre Aspirina e Ibuprofeno?\n"
        "• Quais remédios são para pressão alta?\n"
        "• Qual o princípio ativo do Omeprazol?\n"
        "• Quem fabrica a Metformina?\n"
        "• Quais medicamentos são antialérgicos?\n"
        "• O Ibuprofeno tem alguma interação grave?\n\n"
        "💡 Pergunte naturalmente, como faria a um farmacêutico\\.\n\n"
        "⚠️ _Sou apenas informativo\\. Consulte sempre um profissional de saúde\\._",
    )


async def cmd_sobre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _enviar(
        update,
        "ℹ️ *Sobre este bot*\n\n"
        "Motor: DSPy \\+ Ollama \\(phi3\\.5 / 4B\\)\n"
        "Banco: SQLite com 12 medicamentos\n"
        "Interações cadastradas: 5\n"
        "Fabricantes: 5\n\n"
        "_Projeto educacional — não substitui orientação médica\\._",
    )


# ─────────────────────────────────────────────────────────────
#  HANDLER DE MENSAGENS
# ─────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global agente_global

    pergunta = update.message.text.strip()
    if not pergunta:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # ── Rate limiting ─────────────────────────────────────────
    if not _checar_rate_limit(user_id):
        await update.message.reply_text(
            f"⏳ Muitas perguntas em pouco tempo. "
            f"Aguarde {RATE_LIMIT_WINDOW} segundos e tente novamente."
        )
        return

    # ── Indicador "digitando..." ──────────────────────────────
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # ── Chamar o agente (síncrono → thread pool) ──────────────
    loop = asyncio.get_event_loop()
    try:
        resultado = await loop.run_in_executor(
            executor,
            lambda: agente_global(pergunta=pergunta),
        )
        resposta = aplicar_regras(resultado.resposta, pergunta)

        if not resposta or len(resposta.strip()) < 5:
            resposta = (
                "Não encontrei informações sobre isso na minha base. "
                "Tente reformular a pergunta. 💊"
            )

        # Aviso de saúde quando pergunta envolve posologia
        if any(kw in pergunta.lower() for kw in _DOSE_KW):
            resposta += "\n\n⚠️ _Consulte sempre um médico ou farmacêutico antes de usar qualquer medicamento._"

        logger.info(f"[{user_id}] '{pergunta[:60]}' → cat={resultado.categoria}")

    except Exception as exc:
        logger.error(f"Erro ao processar '{pergunta}': {exc}", exc_info=True)
        resposta = (
            "❌ Ocorreu um erro ao processar sua pergunta. "
            "Tente novamente ou reformule de outra forma."
        )

    await _enviar(update, resposta)


# ─────────────────────────────────────────────────────────────
#  HANDLER DE ERROS
# ─────────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, TelegramError):
        logger.warning(f"TelegramError: {context.error}")
    else:
        logger.error(f"Erro inesperado: {context.error}", exc_info=context.error)


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────
def main() -> None:
    global agente_global

    # ── Inicializar agente ────────────────────────────────────
    print("🔧  Inicializando agente de medicamentos...")
    setup()
    create_database()
    agente_global = build_agent()
    print("✅  Agente pronto!\n")

    # ── Token do Telegram ─────────────────────────────────────
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("═" * 55)
        print("❌  TELEGRAM_TOKEN não encontrado!")
        print()
        print("  Como obter um token:")
        print("  1. Abra o Telegram e fale com @BotFather")
        print("  2. Envie /newbot e siga as instruções")
        print("  3. Copie o token fornecido")
        print()
        print("  Como definir o token:")
        print("  Linux/Mac → export TELEGRAM_TOKEN='seu_token'")
        print("  Windows   → set TELEGRAM_TOKEN=seu_token")
        print("  Python    → import os; os.environ['TELEGRAM_TOKEN'] = 'token'")
        print("  Colab     → %env TELEGRAM_TOKEN=seu_token")
        print("═" * 55)
        return

    # ── Criar aplicação do bot ────────────────────────────────
    app = (
        Application.builder()
        .token(token)
        .build()
    )

    # Comandos
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("ajuda",  cmd_help))
    app.add_handler(CommandHandler("sobre",  cmd_sobre))

    # Mensagens de texto
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Handler de erros
    app.add_error_handler(on_error)

    # ── Registrar comandos no menu do Telegram ────────────────
    async def _set_commands(app: Application) -> None:
        await app.bot.set_my_commands([
            BotCommand("start", "Iniciar o bot"),
            BotCommand("help",  "Ver exemplos de perguntas"),
            BotCommand("sobre", "Sobre este bot"),
        ])

    app.post_init = _set_commands

    # ── Iniciar polling ───────────────────────────────────────
    print("🤖  Bot Telegram iniciado! Fale com seu bot no app.")
    print("    Ctrl+C para encerrar.\n")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # ignora mensagens recebidas enquanto offline
    )


if __name__ == "__main__":
    main()
