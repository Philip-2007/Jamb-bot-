import os
import json
import random
import logging
import time
import requests
from datetime import datetime
from flask import Flask, request, Response
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, ConversationHandler, CallbackContext, MessageHandler, Filters
from telegram.ext import Updater

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "8224895234:AAGlQmIMHgNv_P0XW2qZ9PMoIcv2dhQqBhI")
ADMIN_ID = 6726456466
PORT = int(os.environ.get("PORT", 8000))

# JSONBin Configuration
JSONBIN_BIN_ID = '69e0db67aaba882197069654'
JSONBIN_API_KEY = '$2a$10$Ailo1FCdiaG3coaubaZK3O80dS9MOHCx6zOtBWxpBbiDcNbA8y5w6'
JSONBIN_URL = f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}'

CHOOSING_MODE, EXAM_SUBJECT, EXAM_QUESTIONS, EXAM_TIME, CBT_SUBJECTS, QUIZ, CONFIRM_QUIT, REVIEW_MISSED, GET_PHONE = range(9)

SUBJECTS = {
    "English": "english.json",
    "Mathematics": "math.json",
    "Physics": "physics.json",
    "Chemistry": "chemistry.json",
    "Biology": "biology.json"
}

EMOJIS = {"English": "📖", "Mathematics": "🧮", "Physics": "⚡", "Chemistry": "🧪", "Biology": "🧬"}

CBT_TIME = 80 * 60
CBT_MARKS_PER_QUESTION = 2.5
EXAM_MARKS_PER_QUESTION = 1

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

# Cloud Database Functions
def load_cloud_data():
    """Load data from JSONBin"""
    try:
        response = requests.get(f"{JSONBIN_URL}/latest", 
                               headers={'X-Master-Key': JSONBIN_API_KEY})
        if response.status_code == 200:
            data = response.json()
            return data.get('record', {'results': [], 'users': [], 'phone_numbers': {}})
        return {'results': [], 'users': [], 'phone_numbers': {}}
    except Exception as e:
        logger.error(f"Failed to load from cloud: {e}")
        return {'results': [], 'users': [], 'phone_numbers': {}}

def save_cloud_data(data):
    """Save data to JSONBin"""
    try:
        response = requests.put(JSONBIN_URL,
                               headers={'Content-Type': 'application/json',
                                       'X-Master-Key': JSONBIN_API_KEY},
                               json=data)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Failed to save to cloud: {e}")
        return False

# Load initial data from cloud
cloud_db = load_cloud_data()
DB = {'users': cloud_db.get('users', {}), 'attempts': cloud_db.get('results', [])}
phone_db = cloud_db.get('phone_numbers', {})

def sync_to_cloud():
    """Sync local DB to cloud"""
    cloud_data = {
        'results': DB['attempts'],
        'users': DB['users'],
        'phone_numbers': phone_db
    }
    return save_cloud_data(cloud_data)

sessions = {}
app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dp = updater.dispatcher

def format_time(seconds):
    if seconds is None:
        return "N/A"
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🎓 JAMB 2026 CBT PRO BOT\n\n"
        "Welcome to the most comprehensive JAMB practice bot!\n\n"
        "/start_quiz - Begin test\n"
        "/leaderboard - Top students\n"
        "/myresult - Your last score\n"
        "/admin - Admin dashboard\n\n"
        "📞 *Note:* Your phone number helps us identify top performers for rewards.",
        parse_mode="Markdown"
    )

def ask_phone(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    
    if user_id in phone_db:
        return start_quiz_direct(update, context)
    
    update.message.reply_text(
        "📱 *Quick Registration*\n\n"
        "To help us identify top performers for future rewards, please share your phone number.\n\n"
        "Format: 08123456789\n\n"
        "Type your number or /skip to continue without it.",
        parse_mode="Markdown"
    )
    return GET_PHONE

def save_phone(update: Update, context: CallbackContext):
    global phone_db
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if text == "/skip":
        phone_db[user_id] = "Skipped"
        sync_to_cloud()
        update.message.reply_text("✅ No problem! You can start the quiz now.\n\nUse /start_quiz to begin!")
        return ConversationHandler.END
    
    if text.isdigit() and len(text) >= 10:
        phone_db[user_id] = text
        sync_to_cloud()
        update.message.reply_text("✅ Thank you! Your number has been saved.\n\nUse /start_quiz to begin your test!\n\nGood luck! 🍀")
        return ConversationHandler.END
    else:
        update.message.reply_text("❌ That doesn't look like a valid phone number.\n\nPlease enter a valid number or /skip")
        return GET_PHONE

def start_quiz(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id not in phone_db:
        return ask_phone(update, context)
    return start_quiz_direct(update, context)

def start_quiz_direct(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("📝 EXAM MODE (Custom Questions & Time)", callback_data="exam")],
        [InlineKeyboardButton("💻 CBT MODE (180 Qs, 60+40+40+40)", callback_data="cbt")],
    ]
    update.message.reply_text("🎯 SELECT TEST MODE:", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSING_MODE

def mode(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    
    if q.data == "exam":
        kb = []
        for s in SUBJECTS:
            if ALL_Q.get(s):
                kb.append([InlineKeyboardButton(f"{EMOJIS[s]} {s} ({len(ALL_Q[s])} available)", callback_data=f"examsubj_{s}")])
        q.edit_message_text("📝 EXAM MODE\n\nPick a subject:", reply_markup=InlineKeyboardMarkup(kb))
        return EXAM_SUBJECT
    
    # CBT MODE
    context.user_data["cbt_subs"] = ["English"]
    available = [s for s in SUBJECTS if s != "English" and ALL_Q.get(s)]
    
    kb = []
    for s in available:
        kb.append([InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=f"cbt_{s}")])
    kb.append([InlineKeyboardButton("✅ DONE", callback_data="cbt_done")])
    
    q.edit_message_text(
        "💻 CBT MODE\n\n📖 English (Compulsory - 60 Qs) ✅\n\nSelect 3 additional subjects (40 Qs each):",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CBT_SUBJECTS

def exam_subject(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    subject = q.data.replace("examsubj_", "")
    context.user_data["exam_subject"] = subject
    
    max_q = len(ALL_Q.get(subject, []))
    context.user_data["exam_max_q"] = max_q
    
    q.edit_message_text(
        f"📝 EXAM MODE - {subject}\n\n"
        f"Available questions: {max_q}\n\n"
        f"How many questions do you want? (10-{max_q})\n"
        f"Type a number:"
    )
    return EXAM_QUESTIONS

def exam_questions(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if not text.isdigit():
        update.message.reply_text("❌ Please enter a valid number.")
        return EXAM_QUESTIONS
    
    num = int(text)
    max_q = context.user_data.get("exam_max_q", 100)
    
    if num < 10 or num > max_q:
        update.message.reply_text(f"❌ Please enter a number between 10 and {max_q}.")
        return EXAM_QUESTIONS
    
    context.user_data["exam_num_q"] = num
    update.message.reply_text(
        f"✅ {num} questions selected.\n\n"
        f"How many MINUTES should the exam last? (10-180)\n"
        f"Type a number:"
    )
    return EXAM_TIME

def exam_time(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if not text.isdigit():
        update.message.reply_text("❌ Please enter a valid number.")
        return EXAM_TIME
    
    mins = int(text)
    if mins < 10 or mins > 180:
        update.message.reply_text("❌ Please enter a number between 10 and 180 minutes.")
        return EXAM_TIME
    
    context.user_data["exam_time"] = mins
    subject = context.user_data.get("exam_subject")
    num_q = context.user_data.get("exam_num_q")
    
    update.message.reply_text(
        f"🎯 EXAM READY!\n\n"
        f"Subject: {subject}\n"
        f"Questions: {num_q}\n"
        f"Time: {mins} minutes\n\n"
        f"Starting now... Good luck! 🍀"
    )
    
    return start_exam_session(update, context)

def start_exam_session(update: Update, context: CallbackContext):
    user = update.effective_user.id
    subject = context.user_data.get("exam_subject")
    num_q = context.user_data.get("exam_num_q")
    time_mins = context.user_data.get("exam_time")
    
    available = ALL_Q.get(subject, [])
    selected = random.sample(available, min(num_q, len(available)))
    for item in selected:
        item["subject"] = subject
    
    sessions[user] = {
        "mode": "exam",
        "subjects": [subject],
        "q": selected,
        "i": 0,
        "answers": [None] * len(selected),
        "start": time.time(),
        "time_limit": time_mins * 60
    }
    
    time.sleep(1)
    return send_q(update, context, user)

def cbt(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    
    if q.data == "cbt_done":
        subs = context.user_data.get("cbt_subs", ["English"])
        if len(subs) != 4:
            q.answer(f"Select exactly 3 more! (Now: {len(subs)-1})", show_alert=True)
            return CBT_SUBJECTS
        return start_cbt_session(q, context, subs)
    
    subj = q.data.replace("cbt_", "")
    subs = context.user_data.get("cbt_subs", ["English"])
    
    if subj in subs:
        subs.remove(subj)
    elif len(subs) < 4:
        subs.append(subj)
    
    context.user_data["cbt_subs"] = subs
    
    available = [s for s in SUBJECTS if s != "English" and ALL_Q.get(s)]
    kb = []
    for s in available:
        check = "✅ " if s in subs else ""
        kb.append([InlineKeyboardButton(f"{check}{EMOJIS[s]} {s}", callback_data=f"cbt_{s}")])
    kb.append([InlineKeyboardButton("✅ DONE", callback_data="cbt_done")])
    
    selected_display = ", ".join([s for s in subs if s != "English"]) or "None"
    q.edit_message_text(
        f"💻 CBT MODE\n\n📖 English ✅ (60 Qs)\n\nSelected: {selected_display}\n({len(subs)-1}/3 selected)",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CBT_SUBJECTS

def start_cbt_session(q, context, subjects):
    user = q.from_user.id
    all_qs = []
    
    # ENGLISH FIRST - 60 questions
    english_bank = ALL_Q.get('English', [])
    english_selected = random.sample(english_bank, min(60, len(english_bank)))
    for item in english_selected:
        item["subject"] = "English"
    all_qs.extend(english_selected)
    
    # THEN OTHER SUBJECTS - 40 questions each
    for s in subjects:
        if s != "English":
            available = ALL_Q.get(s, [])
            if available:
                selected = random.sample(available, min(40, len(available)))
                for item in selected:
                    item["subject"] = s
                all_qs.extend(selected)
    
    if not all_qs:
        q.edit_message_text("❌ No questions available!")
        return ConversationHandler.END
    
    sessions[user] = {
        "mode": "cbt",
        "subjects": subjects,
        "q": all_qs,
        "i": 0,
        "answers": [None] * len(all_qs),
        "start": time.time(),
        "time_limit": CBT_TIME
    }
    
    q.edit_message_text(f"🎯 Starting! {len(all_qs)} questions. 80 minutes. Good luck! 🍀")
    time.sleep(1)
    return send_q(q, context, user)

def send_q(q_or_update, context, user):
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    elapsed = time.time() - s["start"]
    if elapsed > s["time_limit"]:
        return submit_quiz(q_or_update, context, user, time_up=True)
    
    i = s["i"]
    if i >= len(s["q"]):
        return submit_quiz(q_or_update, context, user)
    
    question = s["q"][i]
    opts = question.get("options", ["A", "B", "C", "D"])
    current_answer = s["answers"][i]
    
    kb = []
    for idx, opt in enumerate(opts):
        display = opt[:40] + "..." if len(opt) > 40 else opt
        check = "✅ " if current_answer == idx else ""
        kb.append([InlineKeyboardButton(f"{check}{chr(65+idx)}. {display}", callback_data=f"ans_{idx}")])
    
    nav_row = []
    if i > 0:
        nav_row.append(InlineKeyboardButton("◀️ PREV", callback_data="prev"))
    nav_row.append(InlineKeyboardButton("📝 SUBMIT", callback_data="submit"))
    if i < len(s["q"]) - 1:
        nav_row.append(InlineKeyboardButton("NEXT ▶️", callback_data="next"))
    if nav_row:
        kb.append(nav_row)
    
    kb.append([InlineKeyboardButton("⏸️ QUIT", callback_data="quit")])
    
    progress = int((i+1) / len(s["q"]) * 20)
    bar = "█" * progress + "░" * (20 - progress)
    
    current_subject = question.get('subject', '')
    remaining = s["time_limit"] - elapsed
    time_display = format_time(int(remaining))
    
    answered_count = sum(1 for ans in s["answers"] if ans is not None)
    
    txt = f"{bar}\nQ{i+1}/{len(s['q'])} | ⏱️ {time_display}\n📖 {current_subject}\n📝 Answered: {answered_count}/{len(s['q'])}\n\n{question['question']}"
    
    if hasattr(q_or_update, 'edit_message_text'):
        q_or_update.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    else:
        q_or_update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    return QUIZ

def handle_answer(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    s = sessions.get(user)
    
    if not s:
        q.edit_message_text("❌ Session expired. Use /start_quiz")
        return ConversationHandler.END
    
    data = q.data
    
    if data == "quit":
        return confirm_quit(q, context)
    elif data == "submit":
        return submit_quiz(q, context, user)
    elif data == "prev":
        if s["i"] > 0:
            s["i"] -= 1
        return send_q(q, context, user)
    elif data == "next":
        if s["i"] < len(s["q"]) - 1:
            s["i"] += 1
        return send_q(q, context, user)
    elif data.startswith("ans_"):
        idx = int(data.replace("ans_", ""))
        s["answers"][s["i"]] = idx
        q.answer(f"✅ Selected {chr(65+idx)}")
        
        if s["i"] < len(s["q"]) - 1:
            s["i"] += 1
            return send_q(q, context, user)
        else:
            return send_q(q, context, user)
    
    return QUIZ

def submit_quiz(q, context, user, time_up=False):
    global DB
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    raw_score = 0
    marks_per_q = CBT_MARKS_PER_QUESTION if s["mode"] == "cbt" else EXAM_MARKS_PER_QUESTION
    
    subject_scores = {}
    answers_detail = []
    
    for i, ans in enumerate(s["answers"]):
        question = s["q"][i]
        subject = question.get('subject', 'General')
        correct_idx = question.get("correct", 0)
        correct_answer = question["options"][correct_idx] if correct_idx < len(question["options"]) else "N/A"
        user_answer_text = question["options"][ans] if ans is not None and ans < len(question["options"]) else "Not answered"
        
        if subject not in subject_scores:
            subject_scores[subject] = {'correct': 0, 'total': 0}
        subject_scores[subject]['total'] += 1
        
        is_correct = False
        if ans is not None and ans == correct_idx:
            raw_score += 1
            subject_scores[subject]['correct'] += 1
            is_correct = True
        
        answers_detail.append({
            "q_num": i + 1,
            "question": question["question"],
            "subject": subject,
            "user_answer": user_answer_text,
            "correct_answer": correct_answer,
            "is_correct": is_correct
        })
    
    for subj in subject_scores:
        subject_scores[subj]['percent'] = round(
            subject_scores[subj]['correct'] / subject_scores[subj]['total'] * 100, 1
        ) if subject_scores[subj]['total'] > 0 else 0
    
    total_questions = len(s["q"])
    total_marks = total_questions * marks_per_q
    earned_marks = raw_score * marks_per_q
    percent = round(raw_score / total_questions * 100, 1) if total_questions > 0 else 0
    time_taken = int(time.time() - s["start"])
    
    user_obj = q.from_user
    
    # Save to cloud DB
    DB["users"][str(user)] = {"name": user_obj.first_name, "username": user_obj.username}
    
    attempt_data = {
        "user_id": str(user),
        "name": user_obj.first_name,
        "username": user_obj.username or "N/A",
        "phone": phone_db.get(str(user), "Not provided"),
        "mode": s["mode"],
        "subjects": ", ".join(s["subjects"]),
        "raw_score": raw_score,
        "total_questions": total_questions,
        "total_marks": total_marks,
        "earned_marks": earned_marks,
        "percent": percent,
        "time_taken": time_taken,
        "subject_scores": subject_scores,
        "answers_detail": answers_detail,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    
    DB["attempts"].append(attempt_data)
    sync_to_cloud()  # Save to JSONBin immediately!
    
    if time_up:
        fb, emoji = "⏰ TIME'S UP!", "⏰"
    elif percent >= 80:
        fb, emoji = "🌟 Outstanding!", "🏆"
    elif percent >= 70:
        fb, emoji = "👍 Excellent!", "🎯"
    elif percent >= 60:
        fb, emoji = "📚 Good effort!", "💪"
    elif percent >= 50:
        fb, emoji = "📖 Fair performance!", "📝"
    else:
        fb, emoji = "🌱 Keep practicing!", "🌱"
    
    txt = f"{emoji} QUIZ SUBMITTED! {emoji}\n\n"
    txt += f"📊 Mode: {s['mode'].upper()}\n"
    txt += f"🎯 Correct: {raw_score}/{total_questions}\n"
    txt += f"📈 Marks: {earned_marks:.1f}/{total_marks}\n"
    txt += f"📊 Percent: {percent}%\n"
    txt += f"⏱️ Time: {format_time(time_taken)}\n\n"
    
    txt += f"📚 SUBJECT BREAKDOWN:\n"
    for subj, data in subject_scores.items():
        emoji = EMOJIS.get(subj, "📚")
        subj_marks = data['correct'] * marks_per_q
        subj_total = data['total'] * marks_per_q
        txt += f"{emoji} {subj}: {data['correct']}/{data['total']} ({subj_marks:.1f}/{subj_total:.1f} marks) - {data['percent']}%\n"
    
    txt += f"\n{fb}\n\n"
    txt += "/start_quiz - Try again\n"
    txt += "/myresult - View again"
    
    del sessions[user]
    q.edit_message_text(txt)
    return ConversationHandler.END

def confirm_quit(q, context):
    kb = [
        [InlineKeyboardButton("✅ YES, END", callback_data="force_quit")],
        [InlineKeyboardButton("❌ NO, CONTINUE", callback_data="resume")],
    ]
    q.edit_message_text("⚠️ ARE YOU SURE?\n\nProgress will be lost.", reply_markup=InlineKeyboardMarkup(kb))
    return CONFIRM_QUIT

def resume(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    return send_q(q, context, user)

def force_quit(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    if user in sessions:
        del sessions[user]
    q.edit_message_text("❌ Quiz Cancelled\n\nUse /start_quiz to try again!")
    return ConversationHandler.END

def my_result(update: Update, context: CallbackContext):
    uid = str(update.effective_user.id)
    attempts = [a for a in DB["attempts"] if a.get("user_id") == uid]
    if not attempts:
        update.message.reply_text("No attempts yet!")
        return
    a = attempts[-1]
    
    time_str = format_time(a.get('time_taken'))
    txt = f"📊 YOUR LAST RESULT\n\n"
    txt += f"Mode: {a.get('mode', 'N/A').upper()}\n"
    txt += f"Score: {a['raw_score']}/{a['total_questions']} correct\n"
    txt += f"Marks: {a['earned_marks']:.1f}/{a['total_marks']}\n"
    txt += f"Percent: {a['percent']}%\n"
    txt += f"Time: {time_str}"
    
    if a.get('subject_scores'):
        txt += f"\n\n📚 SUBJECT BREAKDOWN:\n"
        for subj, data in a['subject_scores'].items():
            emoji = EMOJIS.get(subj, "📚")
            txt += f"{emoji} {subj}: {data['correct']}/{data['total']} ({data['percent']}%)\n"
    
    update.message.reply_text(txt)

def leaderboard(update: Update, context: CallbackContext):
    if not DB["attempts"]:
        update.message.reply_text("No attempts yet!")
        return
    
    user_best = {}
    for a in DB["attempts"]:
        uid = a["user_id"]
        if uid not in user_best or a["percent"] > user_best[uid]["percent"]:
            user_best[uid] = a
    
    top = sorted(user_best.values(), key=lambda x: x["percent"], reverse=True)[:10]
    
    txt = "🏆 TOP 10 LEADERBOARD\n\n"
    for i, t in enumerate(top, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        txt += f"{medal} {t['name']} - {t['percent']}% ({t['mode'].upper()})\n"
    
    update.message.reply_text(txt)

def admin(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only!")
        return
    
    # Refresh from cloud
    global DB, phone_db
    cloud_data = load_cloud_data()
    DB = {'users': cloud_data.get('users', {}), 'attempts': cloud_data.get('results', [])}
    phone_db = cloud_data.get('phone_numbers', {})
    
    if not DB["attempts"]:
        update.message.reply_text("No attempts yet!")
        return
    
    participants = len(DB["users"])
    attempts = len(DB["attempts"])
    
    avg_all = sum(a["percent"] for a in DB["attempts"]) / attempts
    
    txt = f"📊 ADMIN DASHBOARD (Cloud)\n\n"
    txt += f"👥 Total Participants: {participants}\n"
    txt += f"📝 Total Attempts: {attempts}\n"
    txt += f"📈 Average Score: {avg_all:.1f}%\n\n"
    
    txt += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"📋 ALL PARTICIPANT RESULTS:\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for a in DB["attempts"][-15:]:
        txt += f"👤 {a['name']}"
        if a.get('username') and a['username'] != 'N/A':
            txt += f" (@{a['username']})"
        txt += f"\n"
        txt += f"   📞 Phone: {a.get('phone', 'N/A')}\n"
        txt += f"   Mode: {a['mode'].upper()}\n"
        txt += f"   Score: {a['percent']}% ({a['raw_score']}/{a['total_questions']})\n"
        txt += f"   Marks: {a['earned_marks']:.1f}/{a['total_marks']}\n\n"
    
    update.message.reply_text(txt)

def broadcast(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only!")
        return
    
    if not context.args:
        update.message.reply_text("Usage: /broadcast Your message here")
        return
    
    message = " ".join(context.args)
    users = list(set(list(phone_db.keys()) + list(DB["users"].keys())))
    
    if not users:
        update.message.reply_text("No users to broadcast to.")
        return
    
    update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    sent = 0
    for uid in users:
        try:
            bot.send_message(
                chat_id=int(uid),
                text=f"📢 *Announcement*\n\n{message}",
                parse_mode="Markdown"
            )
            sent += 1
            time.sleep(0.1)
        except:
            pass
    
    update.message.reply_text(f"✅ Broadcast complete!\n\n📤 Sent: {sent}")

# Phone collection conversation
phone_conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", ask_phone)],
    states={
        GET_PHONE: [
            MessageHandler(Filters.text & ~Filters.command, save_phone),
            CommandHandler("skip", save_phone)
        ],
    },
    fallbacks=[],
)

# Quiz conversation
quiz_conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", start_quiz)],
    states={
        CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt)$")],
        EXAM_SUBJECT: [CallbackQueryHandler(exam_subject, pattern="^examsubj_")],
        EXAM_QUESTIONS: [MessageHandler(Filters.text & ~Filters.command, exam_questions)],
        EXAM_TIME: [MessageHandler(Filters.text & ~Filters.command, exam_time)],
        CBT_SUBJECTS: [
            CallbackQueryHandler(cbt, pattern="^cbt_"),
            CallbackQueryHandler(cbt, pattern="^cbt_done$")
        ],
        QUIZ: [
            CallbackQueryHandler(handle_answer, pattern="^(ans_|prev|next|submit|quit)"),
        ],
        CONFIRM_QUIT: [
            CallbackQueryHandler(force_quit, pattern="^force_quit$"),
            CallbackQueryHandler(resume, pattern="^resume$")
        ],
    },
    fallbacks=[],
    allow_reentry=True
)

dp.add_handler(phone_conv)
dp.add_handler(quiz_conv)
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("myresult", my_result))
dp.add_handler(CommandHandler("leaderboard", leaderboard))
dp.add_handler(CommandHandler("admin", admin))
dp.add_handler(CommandHandler("broadcast", broadcast))

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
        logger.info(f"✅ Webhook set to {render_url}/telegram")
    
    print(f"\n📊 Questions loaded:")
    for s, qs in ALL_Q.items():
        print(f"   {EMOJIS.get(s, '📚')} {s}: {len(qs)}")
    print(f"\n👑 Admin ID: {ADMIN_ID}")
    print(f"\n☁️ Cloud Database: Connected to JSONBin")
    print(f"\n🚀 Bot starting on port {PORT}...")
    
    app.run(host="0.0.0.0", port=PORT)
