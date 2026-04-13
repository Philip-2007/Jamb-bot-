import os
import json
import random
import logging
import time
from datetime import datetime
from flask import Flask, request, Response
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, ConversationHandler, CallbackContext
from telegram.ext import Updater

# ================= CONFIG =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "8224895234:AAGlQmIMHgNv_P0XW2qZ9PMoIcv2dhQqBhI")
ADMIN_ID = 6726456466
PORT = int(os.environ.get("PORT", 8000))

CHOOSING_MODE, SUBJECT, CBT, QUIZ = range(4)

SUBJECTS = {
    "English": "english.json",
    "Mathematics": "math.json",
    "Physics": "physics.json",
    "Chemistry": "chemistry.json",
    "Biology": "biology.json"
}

EMOJIS = {"English": "📖", "Mathematics": "🧮", "Physics": "⚡", "Chemistry": "🧪", "Biology": "🧬"}

# ================= LOAD QUESTIONS =================
def load_questions(s):
    try:
        with open(SUBJECTS[s], "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            all_q = []
            for topic, qs in data.items():
                for q in qs:
                    q["topic"] = topic
                    all_q.append(q)
            return all_q
    except:
        return []

ALL_Q = {s: load_questions(s) for s in SUBJECTS}
for s, qs in ALL_Q.items():
    logger.info(f"📚 Loaded {len(qs)} questions for {s}")

# ================= STORAGE =================
DB = {"users": {}, "attempts": []}
RESULT_FILE = "results.json"

def load_db():
    global DB
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as f:
            DB = json.load(f)

def save_db():
    with open(RESULT_FILE, "w") as f:
        json.dump(DB, f)

load_db()

# ================= SESSIONS =================
sessions = {}

# ================= FLASK APP =================
app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dp = updater.dispatcher

# ================= BOT HANDLERS =================
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🎓 *JAMB 2026 CBT PRO BOT*\n\n"
        "/start_quiz - Begin test\n"
        "/leaderboard - Top students\n"
        "/myresult - Your last score",
        parse_mode="Markdown"
    )

def my_result(update: Update, context: CallbackContext):
    uid = str(update.effective_user.id)
    attempts = [a for a in DB["attempts"] if a.get("user_id") == uid]
    if not attempts:
        update.message.reply_text("No attempts yet!")
        return
    a = attempts[-1]
    update.message.reply_text(f"📊 Score: {a['score']}/{a['total']} ({a['percent']}%)")

def leaderboard(update: Update, context: CallbackContext):
    if not DB["attempts"]:
        update.message.reply_text("No attempts yet!")
        return
    top = sorted(DB["attempts"], key=lambda x: x["percent"], reverse=True)[:10]
    txt = "🏆 *TOP 10*\n\n"
    for i, t in enumerate(top, 1):
        txt += f"{i}. {t['name']} - {t['percent']}%\n"
    update.message.reply_text(txt, parse_mode="Markdown")

def start_quiz(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("📝 EXAM MODE", callback_data="exam")],
        [InlineKeyboardButton("💻 CBT MODE", callback_data="cbt")],
    ]
    update.message.reply_text("Select mode:", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSING_MODE

def mode(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "exam":
        kb = [[InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=s)] for s in SUBJECTS]
        q.edit_message_text("Pick subject:", reply_markup=InlineKeyboardMarkup(kb))
        return SUBJECT
    context.user_data["sub"] = ["English"]
    kb = [[InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=s)] for s in SUBJECTS if s != "English"]
    kb.append([InlineKeyboardButton("✅ Done", callback_data="done")])
    q.edit_message_text("Select 3 more subjects:", reply_markup=InlineKeyboardMarkup(kb))
    return CBT

def cbt(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "done":
        subs = context.user_data["sub"]
        if len(subs) != 4:
            q.answer("Select exactly 3 more!", show_alert=True)
            return CBT
        return start_session(q, context, subs, "cbt")
    
    subs = context.user_data["sub"]
    if q.data in subs:
        subs.remove(q.data)
    elif len(subs) < 4:
        subs.append(q.data)
    
    selected = ", ".join([s for s in subs if s != "English"]) or "None"
    q.edit_message_text(f"Selected: {selected} ({len(subs)-1}/3)")
    return CBT

def subject(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    return start_session(q, context, [q.data], "exam")

def start_session(q, context, subjects, mode):
    user = q.from_user.id
    qs = []
    for s in subjects:
        available = ALL_Q.get(s, [])
        if available:
            num = min(40, len(available)) if mode == "cbt" else len(available)
            for item in random.sample(available, num):
                item["subject"] = s
                qs.append(item)
    
    random.shuffle(qs)
    sessions[user] = {"mode": mode, "subjects": subjects, "q": qs, "i": 0, "score": 0, "start": time.time()}
    
    q.edit_message_text(f"Starting! {len(qs)} questions. Good luck!")
    return send_q(q, context, user)

def send_q(q, context, user):
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    i = s["i"]
    if i >= len(s["q"]):
        return finish(q, context, user)
    
    question = s["q"][i]
    opts = question["options"].copy()
    correct = question.get("correct", 0)
    
    pairs = list(enumerate(opts))
    random.shuffle(pairs)
    shuffled = []
    new_correct = 0
    for idx, (old, text) in enumerate(pairs):
        shuffled.append(text)
        if old == correct:
            new_correct = idx
    s["_correct"] = new_correct
    
    kb = [[InlineKeyboardButton(f"{chr(65+idx)}. {opt[:40]}", callback_data=str(idx))] for idx, opt in enumerate(shuffled)]
    
    txt = f"*Q{i+1}/{len(s['q'])}*\n{question.get('subject', '')}\n\n{question['question']}"
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return QUIZ

def answer(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    if int(q.data) == s["_correct"]:
        s["score"] += 1
    
    s["i"] += 1
    return send_q(q, context, user)

def finish(q, context, user):
    s = sessions.pop(user, {})
    if not s:
        return ConversationHandler.END
    
    total = len(s["q"])
    score = s["score"]
    percent = round(score / total * 100, 1)
    
    DB["users"][str(user)] = q.from_user.first_name
    DB["attempts"].append({
        "user_id": str(user),
        "name": q.from_user.first_name,
        "mode": s["mode"],
        "score": score,
        "total": total,
        "percent": percent,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db()
    
    txt = f"🏁 *FINISHED!*\n\nScore: {score}/{total}\nPercent: {percent}%"
    q.edit_message_text(txt, parse_mode="Markdown")
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ================= SETUP HANDLERS =================
conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", start_quiz)],
    states={
        CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt)$")],
        SUBJECT: [CallbackQueryHandler(subject, pattern=f"^({'|'.join(SUBJECTS.keys())})$")],
        CBT: [CallbackQueryHandler(cbt, pattern=f"^({'|'.join(SUBJECTS.keys())}|done)$")],
        QUIZ: [CallbackQueryHandler(answer, pattern="^[0-9]$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("myresult", my_result))
dp.add_handler(CommandHandler("leaderboard", leaderboard))
dp.add_handler(conv)

# ================= FLASK ROUTES =================
@app.route("/", methods=["GET"])
def home():
    return "🤖 JAMB Bot is running!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

# ================= MAIN =================
if __name__ == "__main__":
    # Set webhook
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        bot.set_webhook(f"{render_url}/telegram")
        logger.info(f"✅ Webhook set to {render_url}/telegram")
    
    # Start Flask
    app.run(host="0.0.0.0", port=PORT)    
    total = len(s["q"])
    score = s["score"]
    percent = round(score / total * 100, 1)
    
    DB["users"][str(user)] = q.from_user.first_name
    DB["attempts"].append({
        "user_id": str(user),
        "name": q.from_user.first_name,
        "mode": s["mode"],
        "score": score,
        "total": total,
        "percent": percent,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db()
    
    txt = f"🏁 *FINISHED!*\n\nScore: {score}/{total}\nPercent: {percent}%"
    q.edit_message_text(txt, parse_mode="Markdown")
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ================= SETUP HANDLERS =================
conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", start_quiz)],
    states={
        CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt)$")],
        SUBJECT: [CallbackQueryHandler(subject, pattern=f"^({'|'.join(SUBJECTS.keys())})$")],
        CBT: [CallbackQueryHandler(cbt, pattern=f"^({'|'.join(SUBJECTS.keys())}|done)$")],
        QUIZ: [CallbackQueryHandler(answer, pattern="^[0-9]$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("myresult", my_result))
dp.add_handler(CommandHandler("leaderboard", leaderboard))
dp.add_handler(conv)

# ================= FLASK ROUTES =================
@app.route("/", methods=["GET"])
def home():
    return "🤖 JAMB Bot is running!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

# ================= MAIN =================
if __name__ == "__main__":
    # Set webhook
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        bot.set_webhook(f"{render_url}/telegram")
        logger.info(f"✅ Webhook set to {render_url}/telegram")
    
    # Start Flask
    app.run(host="0.0.0.0", port=PORT)async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not DB["attempts"]:
        await update.message.reply_text("No attempts yet!")
        return
    top = sorted(DB["attempts"], key=lambda x: x["percent"], reverse=True)[:10]
    txt = "🏆 *TOP 10 LEADERBOARD*\n\n"
    for i, t in enumerate(top, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        txt += f"{medal} {t['name']} - {t['percent']}%\n"
    await update.message.reply_text(txt, parse_mode="Markdown")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only")
        return
    if not DB["attempts"]:
        await update.message.reply_text("No data")
        return
    participants = len(DB["users"])
    attempts = len(DB["attempts"])
    avg = sum(a["percent"] for a in DB["attempts"]) / attempts
    txt = f"📈 *ADMIN DASHBOARD*\n\n👥 Participants: {participants}\n📝 Attempts: {attempts}\n📊 Avg: {avg:.1f}%"
    await update.message.reply_text(txt, parse_mode="Markdown")

# ================= QUIZ FLOW =================
async def start_quiz(update: Update, context):
    kb = [
        [InlineKeyboardButton("📝 EXAM MODE (Full Subject)", callback_data="exam")],
        [InlineKeyboardButton("💻 CBT MODE (English + 3)", callback_data="cbt")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    await update.message.reply_text("🎯 *SELECT TEST MODE*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CHOOSING_MODE

async def mode(update: Update, context):
    q = update.callback_query
    await q.answer()
    
    if q.data == "cancel":
        await q.edit_message_text("❌ Cancelled")
        return ConversationHandler.END
    
    if q.data == "exam":
        kb = []
        for s in SUBJECTS:
            em = EMOJIS.get(s, "📚")
            kb.append([InlineKeyboardButton(f"{em} {s} ({len(ALL_Q[s])} Qs)", callback_data=s)])
        kb.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        await q.edit_message_text("📝 *Select subject:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return SUBJECT
    
    context.user_data["sub"] = ["English"]
    kb = []
    for s in SUBJECTS:
        if s != "English":
            em = EMOJIS.get(s, "📚")
            kb.append([InlineKeyboardButton(f"{em} {s}", callback_data=s)])
    kb.append([InlineKeyboardButton("✅ Done", callback_data="done")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await q.edit_message_text("💻 *CBT MODE*\n📖 English (Compulsory)\nSelect 3 more:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CBT

async def cbt(update: Update, context):
    q = update.callback_query
    await q.answer()
    
    if q.data == "cancel":
        await q.edit_message_text("❌ Cancelled")
        return ConversationHandler.END
    
    if q.data == "done":
        subs = context.user_data["sub"]
        if len(subs) != 4:
            await q.answer(f"Select exactly 3 more! (Now: {len(subs)-1})", show_alert=True)
            return CBT
        return await start_session(q, context, subs, "cbt")
    
    subs = context.user_data["sub"]
    if q.data in subs:
        subs.remove(q.data)
        await q.answer(f"❌ Removed {q.data}")
    else:
        if len(subs) >= 4:
            await q.answer("Max 3 additional subjects!", show_alert=True)
            return CBT
        subs.append(q.data)
        await q.answer(f"✅ Added {q.data}")
    
    selected = ", ".join([s for s in subs if s != "English"]) or "None"
    await q.edit_message_text(f"💻 *CBT MODE*\n📖 English ✅\nSelected: *{selected}* ({len(subs)-1}/3)", parse_mode="Markdown")
    return CBT

async def subject(update: Update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ Cancelled")
        return ConversationHandler.END
    return await start_session(q, context, [q.data], "exam")

async def start_session(q, context, subjects, mode):
    user = q.from_user.id
    qs = []
    for s in subjects:
        available = ALL_Q.get(s, [])
        if available:
            num = min(40, len(available)) if mode == "cbt" else len(available)
            for item in random.sample(available, num):
                item["subject"] = s
                qs.append(item)
    
    if not qs:
        await q.edit_message_text("❌ No questions available!")
        return ConversationHandler.END
    
    random.shuffle(qs)
    sessions[user] = {
        "mode": mode,
        "subjects": subjects,
        "q": qs,
        "i": 0,
        "score": 0,
        "start": datetime.now(),
        "timer_task": None
    }
    
    total = len(qs)
    await q.edit_message_text(f"🎯 *SESSION STARTING!*\n\nSubjects: {', '.join(subjects)}\nQuestions: {total}\n\n*Good luck!* 🍀", parse_mode="Markdown")
    await asyncio.sleep(2)
    await send_q(q, context, user)
    return QUIZ

async def send_q(q, context, user):
    s = sessions.get(user)
    if not s:
        return
    
    # Cancel previous timer
    if s.get("timer_task"):
        s["timer_task"].cancel()
    
    i = s["i"]
    qs = s["q"]
    
    if i >= len(qs):
        return await finish(q, context, user)
    
    question = qs[i]
    opts = question["options"].copy()
    correct = question.get("correct", 0)
    
    # Shuffle options
    pairs = list(enumerate(opts))
    random.shuffle(pairs)
    shuffled = []
    new_correct = 0
    for idx, (old, text) in enumerate(pairs):
        shuffled.append(text)
        if old == correct:
            new_correct = idx
    s["_correct"] = new_correct
    
    kb = []
    for idx, opt in enumerate(shuffled):
        display = opt[:50] + "..." if len(opt) > 50 else opt
        kb.append([InlineKeyboardButton(f"{chr(65+idx)}. {display}", callback_data=str(idx))])
    kb.append([InlineKeyboardButton("⏸️ Quit", callback_data="quit")])
    
    bar_len = 20
    filled = int((i+1) / len(qs) * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    
    txt = f"*Q{i+1}/{len(qs)}* {bar} {int((i+1)/len(qs)*100)}%\n📖 {question.get('subject', '')}\n\n{question['question']}"
    
    msg = await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    s["timer_task"] = asyncio.create_task(timer(context, user, msg))

async def timer(context, user, msg):
    await asyncio.sleep(20)  # 20 seconds per question
    if user in sessions and sessions[user]["i"] < len(sessions[user]["q"]):
        sessions[user]["i"] += 1
        await send_q(msg, context, user)

async def answer(update: Update, context):
    q = update.callback_query
    await q.answer()
    user = q.from_user.id
    s = sessions.get(user)
    
    if not s:
        await q.edit_message_text("Session expired.")
        return ConversationHandler.END
    
    if q.data == "quit":
        return await confirm_quit(q, context)
    
    idx = int(q.data)
    if idx == s["_correct"]:
        s["score"] += 1
        await q.answer("✅ Correct!")
    else:
        await q.answer("❌ Incorrect!")
    
    s["i"] += 1
    await send_q(q, context, user)
    return QUIZ

async def confirm_quit(q, context):
    kb = [
        [InlineKeyboardButton("✅ Yes", callback_data="force_quit")],
        [InlineKeyboardButton("❌ No", callback_data="resume")]
    ]
    await q.edit_message_text("*⚠️ Quit quiz?* Progress will be lost.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return QUIZ

async def resume(update: Update, context):
    q = update.callback_query
    await q.answer()
    await send_q(q, context, q.from_user.id)
    return QUIZ

async def force_quit(update: Update, context):
    q = update.callback_query
    await q.answer()
    user = q.from_user.id
    if user in sessions:
        del sessions[user]
    await q.edit_message_text("❌ *Quiz Cancelled*\n\nUse /start_quiz to try again!", parse_mode="Markdown")
    return ConversationHandler.END

async def finish(q, context, user):
    s = sessions.pop(user, {})
    if not s:
        return ConversationHandler.END
    
    if s.get("timer_task"):
        s["timer_task"].cancel()
    
    total = len(s["q"])
    score = s["score"]
    percent = round(score / total * 100, 1)
    time_taken = int((datetime.now() - s["start"]).total_seconds())
    
    save_attempt(q.from_user, s["mode"], s["subjects"], score, total, time_taken)
    
    if percent >= 80:
        fb, em = "🌟 Outstanding!", "🏆"
    elif percent >= 70:
        fb, em = "👍 Excellent!", "🎯"
    elif percent >= 60:
        fb, em = "📚 Good effort!", "💪"
    elif percent >= 50:
        fb, em = "📖 Fair performance.", "📝"
    else:
        fb, em = "🌱 Keep practicing!", "🌱"
    
    txt = f"{em} *QUIZ COMPLETED!* {em}\n\n📊 Mode: {s['mode'].upper()}\n📚 Subjects: {', '.join(s['subjects'])}\n🎯 Score: {score}/{total}\n📈 {percent}%\n⏱️ Time: {fmt(time_taken)}\n\n{fb}"
    await q.edit_message_text(txt, parse_mode="Markdown")
    return ConversationHandler.END

# ================= MAIN =================
def main():
    logger.info("🤖 Starting JAMB CBT Bot...")
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start_quiz", start_quiz)],
        states={
            CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt|cancel)$")],
            SUBJECT: [CallbackQueryHandler(subject, pattern="^(English|Mathematics|Physics|Chemistry|Biology|cancel)$")],
            CBT: [CallbackQueryHandler(cbt, pattern="^(English|Mathematics|Physics|Chemistry|Biology|done|cancel)$")],
            QUIZ: [
                CallbackQueryHandler(answer, pattern="^[0-9]$"),
                CallbackQueryHandler(confirm_quit, pattern="^quit$"),
                CallbackQueryHandler(force_quit, pattern="^force_quit$"),
                CallbackQueryHandler(resume, pattern="^resume$"),
            ],
        },
        fallbacks=[CommandHandler("start_quiz", start_quiz)],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myresult", my_result))
    app.add_handler(CommandHandler("progress", progress))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("admin_stats", admin_stats))
    app.add_handler(conv)
    
    webhook_url = f"{RENDER_URL}/telegram"
    logger.info(f"🚀 Starting webhook at {webhook_url}")
    app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=webhook_url)

if __name__ == "__main__":
    main()import os
import json
import random
import logging
import time
from datetime import datetime
from flask import Flask, request, Response
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, ConversationHandler, CallbackContext
from telegram.ext import Updater

# ================= CONFIG =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "8224895234:AAGlQmIMHgNv_P0XW2qZ9PMoIcv2dhQqBhI")
ADMIN_ID = 6726456466
PORT = int(os.environ.get("PORT", 8000))

CHOOSING_MODE, SUBJECT, CBT, QUIZ = range(4)

SUBJECTS = {
    "English": "english.json",
    "Mathematics": "math.json",
    "Physics": "physics.json",
    "Chemistry": "chemistry.json",
    "Biology": "biology.json"
}

EMOJIS = {"English": "📖", "Mathematics": "🧮", "Physics": "⚡", "Chemistry": "🧪", "Biology": "🧬"}

# ================= LOAD QUESTIONS =================
def load_questions(s):
    try:
        with open(SUBJECTS[s], "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            all_q = []
            for topic, qs in data.items():
                for q in qs:
                    q["topic"] = topic
                    all_q.append(q)
            return all_q
    except:
        return []

ALL_Q = {s: load_questions(s) for s in SUBJECTS}
for s, qs in ALL_Q.items():
    logger.info(f"📚 Loaded {len(qs)} questions for {s}")

# ================= STORAGE =================
DB = {"users": {}, "attempts": []}
RESULT_FILE = "results.json"

def load_db():
    global DB
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as f:
            DB = json.load(f)

def save_db():
    with open(RESULT_FILE, "w") as f:
        json.dump(DB, f)

load_db()

# ================= SESSIONS =================
sessions = {}

# ================= FLASK APP =================
app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dp = updater.dispatcher

# ================= BOT HANDLERS =================
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🎓 *JAMB 2026 CBT PRO BOT*\n\n"
        "/start_quiz - Begin test\n"
        "/leaderboard - Top students\n"
        "/myresult - Your last score",
        parse_mode="Markdown"
    )

def my_result(update: Update, context: CallbackContext):
    uid = str(update.effective_user.id)
    attempts = [a for a in DB["attempts"] if a.get("user_id") == uid]
    if not attempts:
        update.message.reply_text("No attempts yet!")
        return
    a = attempts[-1]
    update.message.reply_text(f"📊 Score: {a['score']}/{a['total']} ({a['percent']}%)")

def leaderboard(update: Update, context: CallbackContext):
    if not DB["attempts"]:
        update.message.reply_text("No attempts yet!")
        return
    top = sorted(DB["attempts"], key=lambda x: x["percent"], reverse=True)[:10]
    txt = "🏆 *TOP 10*\n\n"
    for i, t in enumerate(top, 1):
        txt += f"{i}. {t['name']} - {t['percent']}%\n"
    update.message.reply_text(txt, parse_mode="Markdown")

def start_quiz(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("📝 EXAM MODE", callback_data="exam")],
        [InlineKeyboardButton("💻 CBT MODE", callback_data="cbt")],
    ]
    update.message.reply_text("Select mode:", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSING_MODE

def mode(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "exam":
        kb = [[InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=s)] for s in SUBJECTS]
        q.edit_message_text("Pick subject:", reply_markup=InlineKeyboardMarkup(kb))
        return SUBJECT
    context.user_data["sub"] = ["English"]
    kb = [[InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=s)] for s in SUBJECTS if s != "English"]
    kb.append([InlineKeyboardButton("✅ Done", callback_data="done")])
    q.edit_message_text("Select 3 more subjects:", reply_markup=InlineKeyboardMarkup(kb))
    return CBT

def cbt(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "done":
        subs = context.user_data["sub"]
        if len(subs) != 4:
            q.answer("Select exactly 3 more!", show_alert=True)
            return CBT
        return start_session(q, context, subs, "cbt")
    
    subs = context.user_data["sub"]
    if q.data in subs:
        subs.remove(q.data)
    elif len(subs) < 4:
        subs.append(q.data)
    
    selected = ", ".join([s for s in subs if s != "English"]) or "None"
    q.edit_message_text(f"Selected: {selected} ({len(subs)-1}/3)")
    return CBT

def subject(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    return start_session(q, context, [q.data], "exam")

def start_session(q, context, subjects, mode):
    user = q.from_user.id
    qs = []
    for s in subjects:
        available = ALL_Q.get(s, [])
        if available:
            num = min(40, len(available)) if mode == "cbt" else len(available)
            for item in random.sample(available, num):
                item["subject"] = s
                qs.append(item)
    
    random.shuffle(qs)
    sessions[user] = {"mode": mode, "subjects": subjects, "q": qs, "i": 0, "score": 0, "start": time.time()}
    
    q.edit_message_text(f"Starting! {len(qs)} questions. Good luck!")
    return send_q(q, context, user)

def send_q(q, context, user):
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    i = s["i"]
    if i >= len(s["q"]):
        return finish(q, context, user)
    
    question = s["q"][i]
    opts = question["options"].copy()
    correct = question.get("correct", 0)
    
    pairs = list(enumerate(opts))
    random.shuffle(pairs)
    shuffled = []
    new_correct = 0
    for idx, (old, text) in enumerate(pairs):
        shuffled.append(text)
        if old == correct:
            new_correct = idx
    s["_correct"] = new_correct
    
    kb = [[InlineKeyboardButton(f"{chr(65+idx)}. {opt[:40]}", callback_data=str(idx))] for idx, opt in enumerate(shuffled)]
    
    txt = f"*Q{i+1}/{len(s['q'])}*\n{question.get('subject', '')}\n\n{question['question']}"
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return QUIZ

def answer(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    if int(q.data) == s["_correct"]:
        s["score"] += 1
    
    s["i"] += 1
    return send_q(q, context, user)

def finish(q, context, user):
    s = sessions.pop(user, {})
    if not s:
        return ConversationHandler.END
    
    total = len(s["q"])
    score = s["score"]
    percent = round(score / total * 100, 1)
    
    DB["users"][str(user)] = q.from_user.first_name
    DB["attempts"].append({
        "user_id": str(user),
        "name": q.from_user.first_name,
        "mode": s["mode"],
        "score": score,
        "total": total,
        "percent": percent,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db()
    
    txt = f"🏁 *FINISHED!*\n\nScore: {score}/{total}\nPercent: {percent}%"
    q.edit_message_text(txt, parse_mode="Markdown")
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ================= SETUP HANDLERS =================
conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", start_quiz)],
    states={
        CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt)$")],
        SUBJECT: [CallbackQueryHandler(subject, pattern=f"^({'|'.join(SUBJECTS.keys())})$")],
        CBT: [CallbackQueryHandler(cbt, pattern=f"^({'|'.join(SUBJECTS.keys())}|done)$")],
        QUIZ: [CallbackQueryHandler(answer, pattern="^[0-9]$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("myresult", my_result))
dp.add_handler(CommandHandler("leaderboard", leaderboard))
dp.add_handler(conv)

# ================= FLASK ROUTES =================
@app.route("/", methods=["GET"])
def home():
    return "🤖 JAMB Bot is running!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

# ================= MAIN =================
if __name__ == "__main__":
    # Set webhook
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        bot.set_webhook(f"{render_url}/telegram")
        logger.info(f"✅ Webhook set to {render_url}/telegram")
    
    # Start Flask
    app.run(host="0.0.0.0", port=PORT)
