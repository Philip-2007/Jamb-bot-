import os
import json
import random
import logging
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes
)

# ================= CONFIG =================
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not set!")

PORT = int(os.environ.get("PORT", 8000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
ADMIN_ID = 6726456466

RESULT_FILE = "results.json"

CHOOSING_MODE, SUBJECT, CBT, QUIZ = range(4)

SUBJECTS = {
    "English": "english.json",
    "Mathematics": "math.json",
    "Physics": "physics.json",
    "Chemistry": "chemistry.json",
    "Biology": "biology.json"
}

EMOJIS = {
    "English": "📖", "Mathematics": "🧮", "Physics": "⚡",
    "Chemistry": "🧪", "Biology": "🧬"
}

# ================= LOAD QUESTIONS =================
def load_questions(s):
    try:
        with open(SUBJECTS[s], "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                all_q = []
                for topic, qs in data.items():
                    for q in qs:
                        q["topic"] = topic
                        all_q.append(q)
                return all_q
    except Exception as e:
        logger.error(f"Error loading {SUBJECTS[s]}: {e}")
        return []

ALL_Q = {}
for s in SUBJECTS:
    qs = load_questions(s)
    ALL_Q[s] = qs
    logger.info(f"📚 Loaded {len(qs)} questions for {s}")

# ================= STORAGE =================
def load_results():
    if not os.path.exists(RESULT_FILE):
        return {"users": {}, "attempts": []}
    with open(RESULT_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_results(data):
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

DB = load_results()

def save_attempt(user, mode, subjects, score, total, time_taken):
    percent = round(score / total * 100, 1) if total > 0 else 0
    uid = str(user.id)
    DB["users"][uid] = {"name": user.first_name, "username": user.username}
    DB["attempts"].append({
        "user_id": uid,
        "name": user.first_name,
        "username": user.username,
        "mode": mode,
        "subjects": ", ".join(subjects),
        "score": score,
        "total": total,
        "percent": percent,
        "time_taken": time_taken,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_results(DB)

# ================= SESSION =================
sessions = {}

def fmt(sec):
    if sec is None:
        return "N/A"
    return f"{sec//60:02d}:{sec%60:02d}"

def is_admin(uid):
    return uid == ADMIN_ID

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 *JAMB 2026 CBT PRO BOT*\n\n"
        "📝 *Commands:*\n"
        "/start_quiz - Begin test\n"
        "/myresult - Your last score\n"
        "/progress - Track improvement\n"
        "/leaderboard - Top students\n"
        "/help - Get assistance\n\n"
        "📞 *Admin:* 08145090371",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def my_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    attempts = [a for a in DB["attempts"] if a.get("user_id") == uid]
    if not attempts:
        await update.message.reply_text("❌ No attempts yet. Use /start_quiz")
        return
    last = attempts[-1]
    txt = (f"📊 *YOUR LAST RESULT*\n\n"
           f"Mode: {last.get('mode', 'N/A')}\n"
           f"Subjects: {last.get('subjects', 'N/A')}\n"
           f"Score: {last['score']}/{last['total']}\n"
           f"Percent: {last['percent']}%\n"
           f"Time: {fmt(last.get('time_taken'))}\n"
           f"Date: {last['timestamp']}")
    await update.message.reply_text(txt, parse_mode="Markdown")

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    attempts = [a for a in DB["attempts"] if a.get("user_id") == uid]
    if len(attempts) < 2:
        await update.message.reply_text("Take at least 2 quizzes!")
        return
    recent = attempts[-5:]
    txt = "*📈 YOUR PROGRESS*\n\n"
    for i, a in enumerate(recent, 1):
        arrow = "•" if i == 1 else ("↗️" if a["percent"] > recent[i-2]["percent"] else "↘️")
        txt += f"{arrow} {a['timestamp'][:10]}: *{a['percent']}%*\n"
    change = recent[-1]["percent"] - recent[0]["percent"]
    trend = "📈 Improving!" if change > 0 else ("📉 Declining" if change < 0 else "📊 Stable")
    txt += f"\n━━━━━━━━━━\n{trend} ({change:+.1f}%)"
    await update.message.reply_text(txt, parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    main()