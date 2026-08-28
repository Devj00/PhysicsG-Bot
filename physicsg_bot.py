"""
PhysicsG Doubt Solver Bot
--------------------------
এই bot টা Telegram এ student দের physics doubt receive করে
Google Gemini AI দিয়ে answer generate করে automatically reply করে।

প্রশ্ন যে ভাষায় হবে (বাংলা/English), উত্তরও সেই ভাষায় দেবে।
"""

import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# ============================================
# এখানে তোমার দুইটা KEY বসাও (নিচের দুই লাইনে)
# ============================================
TELEGRAM_BOT_TOKEN = "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE"
GEMINI_API_KEY = "PASTE_YOUR_GEMINI_API_KEY_HERE"
# ============================================

# Gemini AI setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# System instruction — bot কে বলে দিচ্ছি কীভাবে answer দিতে হবে
SYSTEM_PROMPT = (
    "You are PhysicsG Doubt Solver, a helpful physics tutor bot for students. "
    "A student will send you a physics doubt or question. "
    "IMPORTANT: Reply in the SAME language the student used. "
    "If they wrote in Bangla, reply fully in Bangla. "
    "If they wrote in English, reply fully in English. "
    "Explain clearly and simply, step by step, as a good teacher would. "
    "Keep answers focused and not overly long unless the question needs detail."
)

# Logging (terminal এ কী হচ্ছে দেখার জন্য)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """যখন কেউ /start command দেবে"""
    await update.message.reply_text(
        "👋 স্বাগতম PhysicsG Doubt Solver তে!\n\n"
        "তোমার physics doubt এখানে লিখে পাঠাও, আমি সাথে সাথে answer দিয়ে দেব।\n\n"
        "👋 Welcome to PhysicsG Doubt Solver!\n"
        "Send me your physics doubt and I'll answer it instantly."
    )


async def handle_doubt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Student এর message পেলে এই function চলে"""
    student_question = update.message.text
    student_name = update.message.from_user.first_name

    logger.info(f"Question from {student_name}: {student_question}")

    # "typing..." দেখানো যাতে student বোঝে bot কাজ করছে
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        response = model.generate_content(
            f"{SYSTEM_PROMPT}\n\nStudent's question:\n{student_question}"
        )
        answer = response.text
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        answer = (
            "দুঃখিত, এই মুহূর্তে answer generate করতে সমস্যা হচ্ছে। একটু পরে আবার try করো।\n"
            "Sorry, I couldn't generate an answer right now. Please try again shortly."
        )

    await update.message.reply_text(answer)


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_doubt))

    print("✅ PhysicsG Bot চালু হয়ে গেছে! Telegram এ গিয়ে test করো।")
    app.run_polling()


if __name__ == "__main__":
    main()
