"""
PhysicsG Doubt Solver Bot
--------------------------
এই bot টা Telegram এ student দের physics doubt receive করে
Google Gemini AI দিয়ে answer generate করে automatically reply করে।

প্রশ্ন যে ভাষায় হবে (বাংলা/English), উত্তরও সেই ভাষায় দেবে।

Teacher (তুমি) এই bot দিয়ে আরও ৩টা কাজ করতে পারবে:
1. Text/PDF/link broadcast করে সব student কে একসাথে পাঠানো
2. Quiz পাঠানো (Telegram এর built-in quiz-poll ব্যবহার করে)
3. Student রা ছবি পাঠালেও bot সেখান থেকে question পড়ে solve করবে
"""

import os
import io
import json
import uuid
import tempfile
import logging
import threading
import asyncio
import concurrent.futures
import matplotlib
matplotlib.use("Agg")  # কোনো screen/display ছাড়াই ছবি বানানোর জন্য
import matplotlib.pyplot as plt
import numpy as np
from flask import Flask
import google.generativeai as genai
from PIL import Image
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# ============================================
# KEY গুলো Render.com এ "Environment Variables" হিসেবে বসাতে হবে:
# TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, TEACHER_CHAT_ID
# ============================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TEACHER_CHAT_ID = os.environ.get("TEACHER_CHAT_ID")  # তোমার নিজের Telegram ID (text হিসেবে)

# Gemini AI setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")

SYSTEM_PROMPT = (
    "You are PhysicsG Doubt Solver, a helpful physics tutor bot for students. "
    "A student will send you a physics doubt or question, sometimes as a photo "
    "of a question paper or textbook page. "
    "IMPORTANT: Reply in the SAME language the student used. "
    "If they wrote in Bangla, reply fully in Bangla. "
    "If they wrote in English, reply fully in English. "
    "Explain clearly and simply, step by step, as a good teacher would. "
    "Keep answers focused and not overly long unless the question needs detail.\n\n"
    "FORMATTING RULES (very important — this is a Telegram chat, not a document):\n"
    "- Do NOT use LaTeX. Never use $ or $$ symbols for equations.\n"
    "- Do NOT use markdown headers like ###.\n"
    "- Do NOT use ** for bold. Write plain text only.\n"
    "- Write equations in plain readable text, e.g., E = kQ / r^2, "
    "use ^ for powers, sqrt(x) for square roots, and normal words like "
    "'times' or 'x' for multiplication if needed.\n"
    "- Use simple numbered steps or dashes (-) for structure instead of headers.\n"
    "- Keep it clean and easy to read on a phone screen."
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# Student দের chat_id গুলো একটা ছোট্ট JSON ফাইলে save রাখা হচ্ছে,
# যাতে broadcast/quiz পাঠানোর সময় জানা যায় কাকে কাকে পাঠাতে হবে।
# (নোট: Render এ নতুন deploy হলে এই ফাইল রিসেট হয়ে যায়,
# কিন্তু bot ঘুমিয়ে-জেগে ওঠার সময় এটা থেকেই যায়।)
# ============================================
SUBSCRIBERS_FILE = "subscribers.json"


def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subs, f)


def add_subscriber(chat_id, name):
    subs = load_subscribers()
    if str(chat_id) not in subs:
        subs[str(chat_id)] = name
        save_subscribers(subs)
        logger.info(f"New subscriber added: {name} ({chat_id})")


def is_teacher(update: Update) -> bool:
    return TEACHER_CHAT_ID is not None and str(update.effective_user.id) == str(TEACHER_CHAT_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """যখন কেউ /start command দেবে"""
    add_subscriber(update.effective_chat.id, update.effective_user.first_name)
    await update.message.reply_text(
        "👋 স্বাগতম PhysicsG Doubt Solver তে!\n\n"
        "তোমার physics doubt (লেখা বা ছবি) এখানে পাঠাও, আমি সাথে সাথে answer দিয়ে দেব।\n\n"
        "👋 Welcome to PhysicsG Doubt Solver!\n"
        "Send me your physics doubt (text or photo) and I'll answer it instantly."
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """নিজের Telegram ID জানার জন্য একটা ছোট command (setup এর সময় লাগবে)"""
    await update.message.reply_text(f"তোমার Telegram user ID: {update.effective_user.id}")


async def handle_doubt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Student এর লেখা doubt পেলে এই function চলে"""
    add_subscriber(update.effective_chat.id, update.effective_user.first_name)

    # Teacher নিজে text পাঠালে সেটা broadcast হিসেবে ধরা হবে (নিচে দেখো), doubt না
    if is_teacher(update):
        return

    student_question = update.message.text
    student_name = update.message.from_user.first_name
    logger.info(f"Question from {student_name}: {student_question}")

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

    # প্রয়োজনে diagram-ও পাঠানো হচ্ছে
    await send_diagram_if_useful(update, context, student_question)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Student ছবি (question এর photo) পাঠালে এই function চলে"""
    add_subscriber(update.effective_chat.id, update.effective_user.first_name)

    student_name = update.message.from_user.first_name
    caption = update.message.caption or ""

    # Teacher যদি ছবি পাঠায় (নোটের ছবি ইত্যাদি), সেটাও broadcast হিসেবে পাঠিয়ে দাও
    if is_teacher(update):
        await broadcast_message(update, context)
        return

    logger.info(f"Photo received from {student_name}, caption: {caption}")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        image = Image.open(io.BytesIO(photo_bytes))

        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "The student sent a photo of one or more physics questions "
            "(possibly a question paper with multiple numbered questions). "
            "Read the question(s) carefully from the image and solve them "
            "step by step. If there are multiple questions, solve each one "
            "clearly with its number.\n\n"
            f"Student's message/caption (may be empty): {caption}"
        )

        response = model.generate_content([prompt, image])
        answer = response.text
    except Exception as e:
        logger.error(f"Error generating answer from photo: {e}")
        answer = (
            "দুঃখিত, ছবিটা থেকে answer generate করতে সমস্যা হচ্ছে। ছবিটা পরিষ্কার কিনা "
            "দেখে আবার পাঠাও, অথবা প্রশ্নটা লিখে পাঠাও।\n"
            "Sorry, I couldn't read the image properly. Please try a clearer photo, "
            "or type the question instead."
        )

    await update.message.reply_text(answer)

    # প্রয়োজনে diagram-ও পাঠানো হচ্ছে
    await send_diagram_if_useful(update, context, caption or "the physics question in the photo")


# ============================================
# DIAGRAM FEATURE: Gemini কে diagram আঁকার জন্য matplotlib
# code লিখতে বলা হয়, তারপর সেটা নিরাপদভাবে চালিয়ে ছবি বানানো হয়।
# ============================================
DIAGRAM_PROMPT = (
    "You are a physics diagram assistant. Given the physics question below, "
    "decide if a simple labeled diagram (like a ray diagram, force diagram, "
    "circuit diagram, field diagram, or geometry figure) would genuinely help "
    "a student understand it.\n\n"
    "If a diagram would NOT help (e.g. a purely numeric or conceptual question "
    "with no geometry), respond with EXACTLY this and nothing else: NO_DIAGRAM\n\n"
    "If a diagram WOULD help, respond with ONLY valid Python code, no markdown "
    "fences, no explanation, nothing else. The code must:\n"
    "- Use only 'plt' (matplotlib.pyplot) and 'np' (numpy), which are already "
    "available — do not import anything.\n"
    "- Draw a clean, clearly labeled diagram using lines, arrows, circles, and "
    "text labels as appropriate.\n"
    "- Use plt.gca().set_aspect('equal') for geometric diagrams where shape "
    "matters.\n"
    "- Turn off unnecessary axis clutter with plt.axis('off') unless axes are "
    "needed.\n"
    "- Save the figure to the path stored in the variable OUTPUT_PATH using "
    "plt.savefig(OUTPUT_PATH, bbox_inches='tight', dpi=150). Do NOT use plt.show().\n\n"
    f"Question: {{question}}"
)

# Diagram code চালানোর সময় শুধু এই safe builtins গুলো ব্যবহার করতে দেওয়া হচ্ছে
_SAFE_BUILTINS = {
    "range": range, "len": len, "str": str, "float": float, "int": int,
    "enumerate": enumerate, "zip": zip, "list": list, "dict": dict, "tuple": tuple,
    "min": min, "max": max, "abs": abs, "round": round, "sum": sum,
    "True": True, "False": False, "None": None, "print": print,
}


def _run_diagram_code(code: str, output_path: str):
    """AI-generated matplotlib code টা একটা সীমিত (restricted) environment এ চালানো হয়"""
    plt.close("all")
    safe_globals = {
        "__builtins__": _SAFE_BUILTINS,
        "plt": plt,
        "np": np,
        "OUTPUT_PATH": output_path,
    }
    exec(code, safe_globals)
    plt.close("all")


def generate_diagram(question_text: str):
    """
    প্রশ্নের জন্য diagram দরকার হলে সেটা বানিয়ে file path রিটার্ন করে,
    দরকার না হলে বা কোনো সমস্যা হলে None রিটার্ন করে।
    """
    try:
        code_response = model.generate_content(
            DIAGRAM_PROMPT.format(question=question_text)
        )
        code_text = code_response.text.strip()

        # Markdown code fence থাকলে সেটা সরিয়ে ফেলা হচ্ছে
        if code_text.startswith("```"):
            code_text = code_text.split("```")[1]
            if code_text.startswith("python"):
                code_text = code_text[len("python"):]
            code_text = code_text.strip()

        if "NO_DIAGRAM" in code_text or "plt.savefig" not in code_text:
            return None

        output_path = os.path.join(tempfile.gettempdir(), f"diagram_{uuid.uuid4().hex}.png")

        # সময়ের সীমা বেঁধে দেওয়া হচ্ছে, যাতে কোনো ভুল code আটকে না থাকে
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_diagram_code, code_text, output_path)
            future.result(timeout=15)

        if os.path.exists(output_path):
            return output_path
        return None
    except Exception as e:
        logger.error(f"Diagram generation failed: {e}")
        return None


async def send_diagram_if_useful(update: Update, context: ContextTypes.DEFAULT_TYPE, question_text: str):
    """Diagram বানানো সম্ভব হলে সেটা student কে পাঠিয়ে দেয়"""
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
        loop = asyncio.get_event_loop()
        diagram_path = await loop.run_in_executor(None, generate_diagram, question_text)

        if diagram_path:
            with open(diagram_path, "rb") as f:
                await update.message.reply_photo(photo=f)
            os.remove(diagram_path)
    except Exception as e:
        logger.error(f"Could not send diagram: {e}")
        # Diagram না গেলেও কোনো সমস্যা নেই, শুধু text answer-ই থেকে যাবে


# ============================================
# TEACHER ONLY FEATURES: broadcast আর quiz
# ============================================

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Teacher এর পাঠানো যেকোনো কিছু (text/PDF/photo/link) সব student কে forward করে দেয়"""
    if not is_teacher(update):
        return

    subs = load_subscribers()
    sent, failed = 0, 0

    for chat_id in subs:
        if str(chat_id) == str(TEACHER_CHAT_ID):
            continue
        try:
            await context.bot.copy_message(
                chat_id=int(chat_id),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast failed for {chat_id}: {e}")
            failed += 1

    await update.message.reply_text(f"✅ পাঠানো হয়েছে {sent} জন student কে। (Failed: {failed})")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/broadcast এর পর লেখা text সব student কে পাঠায়"""
    if not is_teacher(update):
        await update.message.reply_text("দুঃখিত, এই command শুধু teacher ব্যবহার করতে পারবে।")
        return

    text_to_send = update.message.text.replace("/broadcast", "", 1).strip()
    if not text_to_send:
        await update.message.reply_text(
            "Broadcast করার মতো কিছু লেখো, যেমন:\n/broadcast আগামীকাল ক্লাস টেস্ট আছে।\n\n"
            "PDF বা link পাঠাতে চাইলে সরাসরি ফাইল/লিংক bot কে পাঠাও (কোনো command লাগবে না)।"
        )
        return

    subs = load_subscribers()
    sent, failed = 0, 0
    for chat_id in subs:
        if str(chat_id) == str(TEACHER_CHAT_ID):
            continue
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=f"📢 {text_to_send}")
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast failed for {chat_id}: {e}")
            failed += 1

    await update.message.reply_text(f"✅ পাঠানো হয়েছে {sent} জন student কে। (Failed: {failed})")


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Teacher quiz পাঠাতে এভাবে লিখবে:
    /quiz প্রশ্ন লেখো | অপশন ১ | অপশন ২ | অপশন ৩ | অপশন ৪ | সঠিক অপশনের নাম্বার(1-4)

    উদাহরণ:
    /quiz নিউটনের প্রথম সূত্রের অপর নাম কী? | জড়তার সূত্র | মহাকর্ষ সূত্র | গতির সূত্র | শক্তির সূত্র | 1
    """
    if not is_teacher(update):
        await update.message.reply_text("দুঃখিত, এই command শুধু teacher ব্যবহার করতে পারবে।")
        return

    raw = update.message.text.replace("/quiz", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) < 6:
        await update.message.reply_text(
            "সঠিক ফরম্যাটে quiz লেখো:\n\n"
            "/quiz প্রশ্ন | অপশন ১ | অপশন ২ | অপশন ৩ | অপশন ৪ | সঠিক অপশনের নাম্বার\n\n"
            "উদাহরণ:\n"
            "/quiz নিউটনের প্রথম সূত্রের অপর নাম কী? | জড়তার সূত্র | মহাকর্ষ সূত্র | "
            "গতির সূত্র | শক্তির সূত্র | 1"
        )
        return

    question = parts[0]
    options = parts[1:5]
    try:
        correct_index = int(parts[5]) - 1
        if correct_index not in range(4):
            raise ValueError
    except ValueError:
        await update.message.reply_text("সঠিক অপশনের নাম্বার ১ থেকে ৪ এর মধ্যে একটা সংখ্যা হতে হবে।")
        return

    subs = load_subscribers()
    sent, failed = 0, 0
    for chat_id in subs:
        if str(chat_id) == str(TEACHER_CHAT_ID):
            continue
        try:
            await context.bot.send_poll(
                chat_id=int(chat_id),
                question=question,
                options=options,
                type="quiz",
                correct_option_id=correct_index,
                is_anonymous=False,
            )
            sent += 1
        except Exception as e:
            logger.error(f"Quiz send failed for {chat_id}: {e}")
            failed += 1

    await update.message.reply_text(f"✅ Quiz পাঠানো হয়েছে {sent} জন student কে। (Failed: {failed})")


# ============================================
# ছোট্ট একটা "keep-alive" web server।
# Render Free plan এ bot কে ঘুমিয়ে পড়া থেকে আটকাতে
# UptimeRobot (বা এমন কোনো tool) প্রতি কয়েক মিনিটে
# এই web page টা visit/ping করবে।
# ============================================
web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "PhysicsG Bot is alive!"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


async def list_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Teacher দেখতে পারবে এখন পর্যন্ত কারা কারা bot এ join করেছে"""
    if not is_teacher(update):
        await update.message.reply_text("দুঃখিত, এই command শুধু teacher ব্যবহার করতে পারবে।")
        return

    subs = load_subscribers()
    # Teacher নিজেকে লিস্ট থেকে বাদ দিয়ে দেখানো হচ্ছে
    students = {cid: name for cid, name in subs.items() if str(cid) != str(TEACHER_CHAT_ID)}

    if not students:
        await update.message.reply_text("এখনো কোনো student bot এ join করেনি।")
        return

    lines = [f"{i+1}. {name}" for i, name in enumerate(students.values())]
    message = f"👥 মোট {len(students)} জন student join করেছে:\n\n" + "\n".join(lines)
    await update.message.reply_text(message)


def main():
    def run_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("whoami", whoami))
        app.add_handler(CommandHandler("students", list_students))
        app.add_handler(CommandHandler("broadcast", broadcast_command))
        app.add_handler(CommandHandler("quiz", quiz_command))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        # Teacher এর পাঠানো PDF/ডকুমেন্ট সবাইকে broadcast হবে
        app.add_handler(MessageHandler(filters.Document.ALL, broadcast_message))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_doubt))

        print("✅ PhysicsG Bot চালু হয়ে গেছে! Telegram এ গিয়ে test করো।")
        app.run_polling(stop_signals=None)

    threading.Thread(target=run_bot, daemon=True).start()
    run_web_server()


if __name__ == "__main__":
    main()
