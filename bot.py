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
    logger.info(f"Loaded {len(qs)} questions for {s}")

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

sessions = {}
app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dp = updater.dispatcher

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
    percent = round(score / total * 100, 1) if total > 0 else 0
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

conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", start_quiz)],
    states={
        CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt)$")],
        SUBJECT: [CallbackQueryHandler(subject, pattern=f"^({'|'.join(SUBJECTS.keys())})$")],
        CBT: [CallbackQueryHandler(cbt, pattern=f"^({'|'.join(SUBJECTS.keys())}|done)$")],
        QUIZ: [CallbackQueryHandler(answer, pattern="^[0-9]$")],
    },
    fallbacks=[],
)

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("myresult", my_result))
dp.add_handler(CommandHandler("leaderboard", leaderboard))
dp.add_handler(conv)

@app.route("/", methods=["GET"])
def home():
    return "🤖 JAMB Bot is running!"

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return Response("ok", status=200)

if __name__ == "__main__":
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        bot.set_webhook(f"{render_url}/telegram")
        logger.info(f"Webhook set to {render_url}/telegram")
    app.run(host="0.0.0.0", port=PORT)
