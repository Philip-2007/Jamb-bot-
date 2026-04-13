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

def parse_options(options_data):
    if isinstance(options_data, list):
        cleaned = []
        for opt in options_data:
            if isinstance(opt, str):
                if ". " in opt:
                    opt = opt.split(". ", 1)[1]
                elif ") " in opt:
                    opt = opt.split(") ", 1)[1]
                cleaned.append(opt)
            else:
                cleaned.append(str(opt))
        return cleaned
    elif isinstance(options_data, dict):
        result = []
        for key in sorted(options_data.keys()):
            result.append(str(options_data[key]))
        return result
    else:
        return ["A", "B", "C", "D"]

def get_correct_index(question_data):
    answer = question_data.get("answer") or question_data.get("correct") or question_data.get("ans")
    if answer is None:
        return 0
    if isinstance(answer, int):
        return min(answer, 3)
    elif isinstance(answer, str):
        answer = answer.strip().upper()
        if answer in "ABCD":
            return ord(answer) - ord('A')
        try:
            return min(int(answer), 3)
        except:
            return 0
    return 0

def load_questions(s):
    try:
        with open(SUBJECTS[s], "r", encoding="utf-8") as f:
            data = json.load(f)
            all_q = []
            
            if isinstance(data, list):
                if len(data) == 1 and isinstance(data[0], dict):
                    inner = data[0]
                    if any(k.isdigit() for k in inner.keys()):
                        for key, value in inner.items():
                            if isinstance(value, dict):
                                all_q.append(value)
                    else:
                        all_q = data
                else:
                    all_q = data
            elif isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        all_q.extend(value)
                    elif isinstance(value, dict):
                        all_q.append(value)
            
            standardized = []
            for q in all_q:
                if isinstance(q, dict) and "question" in q:
                    options = parse_options(q.get("options", {}))
                    correct = get_correct_index(q)
                    standardized.append({
                        "question": q["question"],
                        "options": options,
                        "correct": correct
                    })
            
            logger.info(f"✅ Loaded {len(standardized)} questions for {s}")
            return standardized
    except Exception as e:
        logger.error(f"❌ Error loading {s}: {e}")
        return []

ALL_Q = {s: load_questions(s) for s in SUBJECTS}
for s, qs in ALL_Q.items():
    print(f"📚 {s}: {len(qs)} questions")

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
        "🎓 JAMB 2026 CBT PRO BOT\n\n"
        "/start_quiz - Begin test\n"
        "/leaderboard - Top students\n"
        "/myresult - Your last score\n"
        "/admin_stats - Admin dashboard\n"
        "/export - Download all results (Admin)"
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
    txt = "🏆 TOP 10\n\n"
    for i, t in enumerate(top, 1):
        txt += f"{i}. {t['name']} - {t['percent']}%\n"
    update.message.reply_text(txt)

def admin_stats(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only!")
        return
    
    if not DB["attempts"]:
        update.message.reply_text("No attempts yet!")
        return
    
    participants = len(DB["users"])
    attempts = len(DB["attempts"])
    avg = sum(a["percent"] for a in DB["attempts"]) / attempts
    
    # Mode breakdown
    exam_attempts = [a for a in DB["attempts"] if a.get("mode") == "exam"]
    cbt_attempts = [a for a in DB["attempts"] if a.get("mode") == "cbt"]
    
    # Subject popularity
    subject_counts = {}
    for a in DB["attempts"]:
        for s in a.get("subjects", "").split(", "):
            subject_counts[s] = subject_counts.get(s, 0) + 1
    
    top = sorted(DB["attempts"], key=lambda x: x["percent"], reverse=True)[:10]
    
    txt = "📊 ADMIN DASHBOARD\n\n"
    txt += f"👥 Participants: {participants}\n"
    txt += f"📝 Total Attempts: {attempts}\n"
    txt += f"   └ Exam Mode: {len(exam_attempts)}\n"
    txt += f"   └ CBT Mode: {len(cbt_attempts)}\n"
    txt += f"📈 Average Score: {avg:.1f}%\n\n"
    
    txt += "📚 SUBJECT POPULARITY:\n"
    for s, count in sorted(subject_counts.items(), key=lambda x: x[1], reverse=True):
        txt += f"   {s}: {count} attempts\n"
    
    txt += "\n🏆 TOP PERFORMERS:\n"
    for i, t in enumerate(top, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        txt += f"{medal} {t['name']} - {t['percent']}% ({t['mode']})\n"
    
    update.message.reply_text(txt)

def export(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only!")
        return
    
    if not DB["attempts"]:
        update.message.reply_text("No data to export!")
        return
    
    csv = "Name,Username,Mode,Subjects,Score,Total,Percent,Time,Date\n"
    for a in DB["attempts"]:
        time_str = a.get("timestamp", "N/A")
        csv += f"{a.get('name','')},{a.get('username','')},{a.get('mode','')},{a.get('subjects','')},{a['score']},{a['total']},{a['percent']}%,{time_str}\n"
    
    filename = f"jamb_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, "w") as f:
        f.write(csv)
    
    with open(filename, "rb") as f:
        update.message.reply_document(document=f, filename=filename, caption=f"📊 {len(DB['attempts'])} attempts")
    
    os.remove(filename)

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
        kb = [[InlineKeyboardButton(f"{EMOJIS[s]} {s} ({len(ALL_Q[s])} Qs)", callback_data=s)] for s in SUBJECTS if ALL_Q[s]]
        if not kb:
            q.edit_message_text("No subjects available!")
            return ConversationHandler.END
        q.edit_message_text("Pick subject:", reply_markup=InlineKeyboardMarkup(kb))
        return SUBJECT
    context.user_data["sub"] = ["English"]
    available = [s for s in SUBJECTS if s != "English" and ALL_Q[s]]
    kb = [[InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=s)] for s in available]
    kb.append([InlineKeyboardButton("✅ Done", callback_data="done")])
    q.edit_message_text(f"Select 3 more subjects:", reply_markup=InlineKeyboardMarkup(kb))
    return CBT

def cbt(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "done":
        subs = context.user_data["sub"]
        if len(subs) != 4:
            q.answer(f"Select exactly 3 more! (Now: {len(subs)-1})", show_alert=True)
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
    
    if not qs:
        q.edit_message_text("❌ No questions available!")
        return ConversationHandler.END
    
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
    opts = question.get("options", ["A", "B", "C", "D"])
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
    
    txt = f"Q{i+1}/{len(s['q'])}\n📖 {question.get('subject', '')}\n\n{question['question']}"
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
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
    
    user_obj = q.from_user
    DB["users"][str(user)] = {"name": user_obj.first_name, "username": user_obj.username}
    DB["attempts"].append({
        "user_id": str(user),
        "name": user_obj.first_name,
        "username": user_obj.username,
        "mode": s["mode"],
        "subjects": ", ".join(s["subjects"]),
        "score": score,
        "total": total,
        "percent": percent,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db()
    
    if percent >= 80:
        fb = "🌟 Outstanding!"
    elif percent >= 70:
        fb = "👍 Excellent!"
    elif percent >= 60:
        fb = "📚 Good effort!"
    elif percent >= 50:
        fb = "📖 Fair performance!"
    else:
        fb = "🌱 Keep practicing!"
    
    txt = f"🏁 FINISHED!\n\nScore: {score}/{total}\nPercent: {percent}%\n\n{fb}"
    q.edit_message_text(txt)
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
dp.add_handler(CommandHandler("admin_stats", admin_stats))
dp.add_handler(CommandHandler("export", export))
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
