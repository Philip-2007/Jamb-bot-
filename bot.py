import os
import json
import random
import logging
import time
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

UPDATE_FLAG_FILE = "update_sent.txt"

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
PHONE_FILE = "phone_numbers.json"

def load_db():
    global DB
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as f:
            DB = json.load(f)

def save_db():
    with open(RESULT_FILE, "w") as f:
        json.dump(DB, f)

def load_phones():
    if os.path.exists(PHONE_FILE):
        with open(PHONE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_phones(phones):
    with open(PHONE_FILE, "w") as f:
        json.dump(phones, f)

load_db()
phone_db = load_phones()

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

def send_update_notification():
    if os.path.exists(UPDATE_FLAG_FILE):
        return
    
    users = list(set(list(phone_db.keys()) + list(DB["users"].keys())))
    sent = 0
    for uid in users:
        try:
            bot.send_message(
                chat_id=int(uid),
                text="🔄 *New update available!*\n\nUse /start_quiz to continue your JAMB preparation.\n\nGood luck! 🍀",
                parse_mode="Markdown"
            )
            sent += 1
            time.sleep(0.1)
        except:
            pass
    
    with open(UPDATE_FLAG_FILE, "w") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    logger.info(f"📢 Update notification sent to {sent} users")

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
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if text == "/skip":
        phone_db[user_id] = "Skipped"
        save_phones(phone_db)
        update.message.reply_text("✅ No problem! You can start the quiz now.\n\nUse /start_quiz to begin!")
        return ConversationHandler.END
    
    if text.isdigit() and len(text) >= 10:
        phone_db[user_id] = text
        save_phones(phone_db)
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
        [InlineKeyboardButton("💻 CBT MODE (160 Qs, 80 mins, 400 Marks)", callback_data="cbt")],
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
        "💻 CBT MODE\n\n📖 English (Compulsory) ✅\n\nSelect 3 additional subjects:",
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
        f"💻 CBT MODE\n\n📖 English ✅\n\nSelected: {selected_display}\n({len(subs)-1}/3 selected)",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CBT_SUBJECTS

def start_cbt_session(q, context, subjects):
    user = q.from_user.id
    all_qs = []
    
    for s in subjects:
        available = ALL_Q.get(s, [])
        if available:
            num = min(40, len(available))
            selected = random.sample(available, num)
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
        return check_before_submit(q, context, user)
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

def check_before_submit(q, context, user):
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    unanswered = []
    for i, ans in enumerate(s["answers"]):
        if ans is None:
            unanswered.append(i)
    
    if unanswered:
        txt = f"⚠️ UNANSWERED QUESTIONS\n\nYou have {len(unanswered)} unanswered question(s).\n\n"
        
        by_subject = {}
        for idx in unanswered[:10]:
            subj = s["q"][idx].get('subject', 'General')
            if subj not in by_subject:
                by_subject[subj] = []
            by_subject[subj].append(idx + 1)
        
        for subj, q_nums in by_subject.items():
            txt += f"{EMOJIS.get(subj, '📚')} {subj}: Q{', Q'.join(map(str, q_nums))}\n"
        
        if len(unanswered) > 10:
            txt += f"\n...and {len(unanswered)-10} more"
        
        txt += "\n\nDo you want to submit anyway?"
        
        kb = [
            [InlineKeyboardButton("🔙 GO BACK", callback_data="back")],
            [InlineKeyboardButton("✅ SUBMIT ANYWAY", callback_data="force_submit")],
        ]
        
        q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return REVIEW_MISSED
    else:
        return submit_quiz(q, context, user)

def force_submit(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    return submit_quiz(q, context, user)

def submit_quiz(q, context, user, time_up=False):
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
    
    DB["users"][str(user)] = {"name": user_obj.first_name, "username": user_obj.username}
    DB["attempts"].append({
        "user_id": str(user),
        "name": user_obj.first_name,
        "username": user_obj.username or "N/A",
        "mode": s["mode"],
        "subjects": ", ".join(s["subjects"]),
        "raw_score": raw_score,
        "total_questions": total_questions,
        "total_marks": total_marks,
        "total_marks_earned": earned_marks,
        "percent": percent,
        "time_taken": time_taken,
        "subject_scores": subject_scores,
        "answers_detail": answers_detail,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db()
    
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
    
    kb = [[InlineKeyboardButton("📋 VIEW ANSWERS", callback_data=f"view_answers_{user}")]]
    
    txt += "/start_quiz - Try again\n"
    txt += "/myresult - View again"
    
    del sessions[user]
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

def view_answers(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    
    attempts = [a for a in DB["attempts"] if a.get("user_id") == str(user)]
    if not attempts:
        q.edit_message_text("No attempts found!")
        return
    
    latest = attempts[-1]
    answers_detail = latest.get("answers_detail", [])
    
    if not answers_detail:
        q.edit_message_text("No answer details available!")
        return
    
    txt = f"📋 YOUR ANSWERS - {latest['mode'].upper()}\n\n"
    
    for ans in answers_detail[:15]:
        emoji = "✅" if ans["is_correct"] else "❌"
        txt += f"{emoji} Q{ans['q_num']}: {ans['question'][:40]}...\n"
        txt += f"   Your answer: {ans['user_answer']}\n"
        txt += f"   Correct: {ans['correct_answer']}\n\n"
    
    if len(answers_detail) > 15:
        txt += f"...and {len(answers_detail) - 15} more questions.\n"
    
    kb = [[InlineKeyboardButton("🔄 NEW QUIZ", callback_data="new_quiz")]]
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

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
    txt += f"Marks: {a['total_marks_earned']:.1f}/{a['total_marks']}\n"
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
    
    if not DB["attempts"]:
        update.message.reply_text("No attempts yet!")
        return
    
    participants = len(DB["users"])
    attempts = len(DB["attempts"])
    
    exam_attempts = [a for a in DB["attempts"] if a.get("mode") == "exam"]
    cbt_attempts = [a for a in DB["attempts"] if a.get("mode") == "cbt"]
    
    avg_all = sum(a["percent"] for a in DB["attempts"]) / attempts
    
    txt = f"📊 ADMIN DASHBOARD\n\n"
    txt += f"👥 Total Participants: {participants}\n"
    txt += f"📝 Total Attempts: {attempts}\n"
    txt += f"   └ Exam Mode: {len(exam_attempts)}\n"
    txt += f"   └ CBT Mode: {len(cbt_attempts)}\n"
    txt += f"📈 Average Score: {avg_all:.1f}%\n\n"
    
    user_attempts = {}
    for a in DB["attempts"]:
        uid = a["user_id"]
        if uid not in user_attempts:
            user_attempts[uid] = []
        user_attempts[uid].append(a)
    
    txt += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"📋 ALL PARTICIPANT RESULTS:\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for uid, attempts_list in user_attempts.items():
        latest = attempts_list[-1]
        phone = phone_db.get(uid, "Not provided")
        
        txt += f"👤 {latest['name']}"
        if latest.get('username') and latest['username'] != 'N/A':
            txt += f" (@{latest['username']})"
        txt += f"\n"
        txt += f"   📞 Phone: {phone}\n"
        txt += f"   Mode: {latest['mode'].upper()}\n"
        txt += f"   Date: {latest['timestamp']}\n"
        txt += f"   Overall: {latest['percent']}% ({latest['raw_score']}/{latest['total_questions']})\n"
        txt += f"   Marks: {latest['total_marks_earned']:.1f}/{latest['total_marks']}\n"
        
        if latest.get('subject_scores'):
            txt += f"   📚 Subject Breakdown:\n"
            for subj, data in latest['subject_scores'].items():
                emoji = EMOJIS.get(subj, "📚")
                txt += f"      {emoji} {subj}: {data['correct']}/{data['total']} ({data['percent']}%)\n"
        
        txt += f"\n"
        
        if len(txt) > 3500:
            txt += "...\n(Use /export for full data)"
            break
    
    kb = [
        [InlineKeyboardButton("📥 EXPORT ALL RESULTS (CSV)", callback_data="export_csv")],
        [InlineKeyboardButton("📢 BROADCAST MESSAGE", callback_data="broadcast_prompt")]
    ]
    update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

def broadcast_prompt(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user_id = q.from_user.id
    
    if user_id != ADMIN_ID:
        q.edit_message_text("⛔ Admin only!")
        return
    
    q.edit_message_text(
        "📢 BROADCAST MESSAGE\n\n"
        "Use /broadcast followed by your message to send to all users.\n\n"
        "Example: /broadcast New questions added! Use /start_quiz to try them."
    )

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
    failed = 0
    
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
            failed += 1
    
    update.message.reply_text(f"✅ Broadcast complete!\n\n📤 Sent: {sent}\n❌ Failed: {failed}")

def export_csv(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user_id = q.from_user.id
    
    if user_id != ADMIN_ID:
        q.edit_message_text("⛔ Admin only!")
        return
    
    if not DB["attempts"]:
        q.edit_message_text("No data to export!")
        return
    
    csv = "Name,Username,Phone,Mode,Date,Overall Score,Overall Percent,Total Marks\n"
    
    for a in DB["attempts"]:
        phone = phone_db.get(a["user_id"], "Not provided")
        csv += f"{a.get('name','')},{a.get('username','')},{phone},{a.get('mode','')},"
        csv += f"{a.get('timestamp','')},{a['raw_score']}/{a['total_questions']},"
        csv += f"{a['percent']}%,{a['total_marks_earned']:.1f}/{a['total_marks']}\n"
    
    filename = f"jamb_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(csv)
    
    with open(filename, "rb") as f:
        q.message.reply_document(document=f, filename=filename, caption=f"📊 {len(DB['attempts'])} attempts from {len(DB['users'])} participants")
    
    os.remove(filename)
    q.edit_message_text("✅ Export complete! Check above for the CSV file.")

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
        REVIEW_MISSED: [
            CallbackQueryHandler(resume, pattern="^back$"),
            CallbackQueryHandler(force_submit, pattern="^force_submit$"),
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
dp.add_handler(CallbackQueryHandler(export_csv, pattern="^export_csv$"))
dp.add_handler(CallbackQueryHandler(broadcast_prompt, pattern="^broadcast_prompt$"))
dp.add_handler(CallbackQueryHandler(view_answers, pattern="^view_answers_"))
dp.add_handler(CallbackQueryHandler(lambda u, c: start_quiz_direct(u, c), pattern="^new_quiz$"))

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
    print(f"\n📱 Phone numbers collected: {len(phone_db)}")
    print(f"\n🚀 Bot starting on port {PORT}...")
    
    send_update_notification()
    
    app.run(host="0.0.0.0", port=PORT)
