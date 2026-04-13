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

CHOOSING_MODE, SUBJECT, CBT, QUIZ, CONFIRM_QUIT, VIEW_SOLUTION = range(6)

SUBJECTS = {
    "English": "english.json",
    "Mathematics": "math.json",
    "Physics": "physics.json",
    "Chemistry": "chemistry.json",
    "Biology": "biology.json"
}

EMOJIS = {"English": "📖", "Mathematics": "🧮", "Physics": "⚡", "Chemistry": "🧪", "Biology": "🧬"}

CBT_TIME = 80 * 60
EXAM_TIME = 30 * 60

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
                        "correct": correct,
                        "explanation": q.get("explanation", "")
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

def format_time(seconds):
    if seconds is None:
        return "N/A"
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"

def generate_explanation(question, correct_answer, options):
    """Generate a simple explanation based on the question"""
    subject = question.get('subject', '').lower()
    q_text = question.get('question', '').lower()
    
    if 'capital' in q_text:
        return f"The capital is {correct_answer}."
    elif 'president' in q_text:
        return f"The current president is {correct_answer}."
    elif 'formula' in q_text or 'equation' in q_text:
        return f"The correct formula is {correct_answer}."
    elif 'synonym' in q_text or 'meaning' in q_text:
        return f"The word meaning is {correct_answer}."
    elif 'force' in q_text or 'energy' in q_text or 'power' in q_text:
        return f"According to physics principles, the answer is {correct_answer}."
    elif 'cell' in q_text or 'organ' in q_text or 'dna' in q_text:
        return f"In biology, the correct answer is {correct_answer}."
    elif 'solve' in q_text or 'calculate' in q_text or 'find' in q_text:
        return f"After calculation, the answer is {correct_answer}."
    else:
        return f"The correct answer is {correct_answer}."

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
    
    time_str = format_time(a.get('time_taken'))
    txt = f"📊 YOUR LAST RESULT\n\n"
    txt += f"Mode: {a.get('mode', 'N/A').upper()}\n"
    txt += f"Subjects: {a.get('subjects', 'N/A')}\n"
    txt += f"Score: {a['score']}/{a['total']}\n"
    txt += f"Percent: {a['percent']}%\n"
    txt += f"Time: {time_str}\n"
    
    if a.get('subject_scores'):
        txt += f"\n📚 SUBJECT BREAKDOWN:\n"
        for subj, data in a['subject_scores'].items():
            txt += f"{EMOJIS.get(subj, '📚')} {subj}: {data['score']}/{data['total']} ({data['percent']}%)\n"
    
    txt += f"\nDate: {a.get('timestamp', 'N/A')}"
    update.message.reply_text(txt)

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
    
    exam_attempts = [a for a in DB["attempts"] if a.get("mode") == "exam"]
    cbt_attempts = [a for a in DB["attempts"] if a.get("mode") == "cbt"]
    
    # Subject performance across all attempts
    subject_performance = {}
    for a in DB["attempts"]:
        if a.get('subject_scores'):
            for subj, data in a['subject_scores'].items():
                if subj not in subject_performance:
                    subject_performance[subj] = {'total_score': 0, 'total_questions': 0, 'attempts': 0}
                subject_performance[subj]['total_score'] += data['score']
                subject_performance[subj]['total_questions'] += data['total']
                subject_performance[subj]['attempts'] += 1
    
    top = sorted(DB["attempts"], key=lambda x: x["percent"], reverse=True)[:10]
    
    txt = "📊 ADMIN DASHBOARD\n\n"
    txt += f"👥 Participants: {participants}\n"
    txt += f"📝 Total Attempts: {attempts}\n"
    txt += f"   └ Exam Mode: {len(exam_attempts)}\n"
    txt += f"   └ CBT Mode: {len(cbt_attempts)}\n"
    txt += f"📈 Average Score: {avg:.1f}%\n\n"
    
    if subject_performance:
        txt += "📚 SUBJECT PERFORMANCE:\n"
        for subj, data in sorted(subject_performance.items()):
            avg_pct = round(data['total_score'] / data['total_questions'] * 100, 1) if data['total_questions'] > 0 else 0
            txt += f"   {EMOJIS.get(subj, '📚')} {subj}: {avg_pct}% ({data['attempts']} attempts)\n"
    
    txt += "\n🏆 TOP PERFORMERS:\n"
    for i, t in enumerate(top, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        txt += f"{medal} {t['name']} - {t['percent']}%\n"
    
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
        time_str = format_time(a.get('time_taken'))
        csv += f"{a.get('name','')},{a.get('username','')},{a.get('mode','')},{a.get('subjects','')},{a['score']},{a['total']},{a['percent']}%,{time_str},{a.get('timestamp','')}\n"
    
    filename = f"jamb_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(csv)
    
    with open(filename, "rb") as f:
        update.message.reply_document(document=f, filename=filename, caption=f"📊 {len(DB['attempts'])} attempts")
    
    os.remove(filename)

def start_quiz(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("📝 EXAM MODE (60 Questions, 30 mins)", callback_data="exam")],
        [InlineKeyboardButton("💻 CBT MODE (English + 3 Subjects, 80 mins)", callback_data="cbt")],
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
                kb.append([InlineKeyboardButton(f"{EMOJIS[s]} {s} ({len(ALL_Q[s])} available)", callback_data=f"subj_{s}")])
        if not kb:
            q.edit_message_text("❌ No subjects available!")
            return ConversationHandler.END
        q.edit_message_text("📝 EXAM MODE\n\nPick a subject (60 questions, 30 mins):", reply_markup=InlineKeyboardMarkup(kb))
        return SUBJECT
    
    # CBT MODE
    context.user_data["cbt_subs"] = ["English"]
    available = [s for s in SUBJECTS if s != "English" and ALL_Q.get(s)]
    
    kb = []
    for s in available:
        kb.append([InlineKeyboardButton(f"{EMOJIS[s]} {s}", callback_data=f"cbt_{s}")])
    kb.append([InlineKeyboardButton("✅ DONE", callback_data="cbt_done")])
    
    q.edit_message_text(
        "💻 CBT MODE\n\n📖 English (Compulsory) ✅\n\nSelect 3 additional subjects:\n(0/3 selected)\n\n⏱️ Time: 1 hour 20 minutes",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CBT

def cbt(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    
    if q.data == "cbt_done":
        subs = context.user_data.get("cbt_subs", ["English"])
        if len(subs) != 4:
            q.answer(f"Select exactly 3 more! (Now: {len(subs)-1})", show_alert=True)
            return CBT
        return start_session(q, context, subs, "cbt")
    
    subj = q.data.replace("cbt_", "")
    subs = context.user_data.get("cbt_subs", ["English"])
    
    if subj in subs:
        subs.remove(subj)
    elif len(subs) < 4:
        subs.append(subj)
    else:
        q.answer("Maximum 3 additional subjects!", show_alert=True)
        return CBT
    
    context.user_data["cbt_subs"] = subs
    
    available = [s for s in SUBJECTS if s != "English" and ALL_Q.get(s)]
    kb = []
    for s in available:
        check = "✅ " if s in subs else ""
        kb.append([InlineKeyboardButton(f"{check}{EMOJIS[s]} {s}", callback_data=f"cbt_{s}")])
    kb.append([InlineKeyboardButton("✅ DONE", callback_data="cbt_done")])
    
    selected_display = ", ".join([s for s in subs if s != "English"]) or "None"
    q.edit_message_text(
        f"💻 CBT MODE\n\n📖 English (Compulsory) ✅\n\nSelected: {selected_display}\n({len(subs)-1}/3 selected)\n\n⏱️ Time: 1 hour 20 minutes\n\nTap subjects to add/remove:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CBT

def subject(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    subj = q.data.replace("subj_", "")
    return start_session(q, context, [subj], "exam")

def start_session(q, context, subjects, mode):
    user = q.from_user.id
    
    all_qs = []
    
    if mode == "cbt":
        for s in subjects:
            available = ALL_Q.get(s, [])
            if available:
                num = min(40, len(available))
                selected = random.sample(available, num)
                for item in selected:
                    item["subject"] = s
                all_qs.extend(selected)
    else:
        s = subjects[0]
        available = ALL_Q.get(s, [])
        if available:
            num = min(60, len(available))
            selected = random.sample(available, num)
            for item in selected:
                item["subject"] = s
            all_qs = selected
    
    if not all_qs:
        q.edit_message_text("❌ No questions available!")
        return ConversationHandler.END
    
    time_limit = CBT_TIME if mode == "cbt" else EXAM_TIME
    
    # Initialize answers array with None
    answers = [None] * len(all_qs)
    
    sessions[user] = {
        "mode": mode,
        "subjects": subjects,
        "q": all_qs,
        "i": 0,
        "answers": answers,
        "start": time.time(),
        "time_limit": time_limit,
        "submitted": False
    }
    
    total_qs = len(all_qs)
    time_str = format_time(time_limit)
    q.edit_message_text(f"🎯 Starting! {total_qs} questions. Time: {time_str}. Good luck! 🍀")
    time.sleep(1)
    return send_q(q, context, user)

def send_q(q, context, user):
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    elapsed = time.time() - s["start"]
    if elapsed > s["time_limit"] and not s.get("submitted"):
        return finish(q, context, user, time_up=True)
    
    i = s["i"]
    if i >= len(s["q"]):
        return finish(q, context, user)
    
    question = s["q"][i]
    opts = question.get("options", ["A", "B", "C", "D"])
    correct = question.get("correct", 0)
    
    # Check if already answered
    current_answer = s["answers"][i]
    
    kb = []
    for idx, opt in enumerate(opts):
        display = opt[:50] + "..." if len(opt) > 50 else opt
        check = "✅ " if current_answer == idx else ""
        kb.append([InlineKeyboardButton(f"{check}{chr(65+idx)}. {display}", callback_data=f"select_{idx}")])
    
    # Navigation buttons
    nav_row = []
    if i > 0:
        nav_row.append(InlineKeyboardButton("◀️ PREV", callback_data="prev"))
    nav_row.append(InlineKeyboardButton("📝 SUBMIT", callback_data="submit"))
    if i < len(s["q"]) - 1:
        nav_row.append(InlineKeyboardButton("NEXT ▶️", callback_data="next"))
    kb.append(nav_row)
    
    kb.append([InlineKeyboardButton("⏸️ QUIT", callback_data="quit")])
    
    progress = int((i+1) / len(s["q"]) * 20)
    bar = "█" * progress + "░" * (20 - progress)
    
    current_subject = question.get('subject', '')
    remaining = s["time_limit"] - elapsed
    time_display = format_time(int(remaining))
    
    answered_count = sum(1 for ans in s["answers"] if ans is not None)
    
    txt = f"{bar}\nQ{i+1}/{len(s['q'])} | ⏱️ {time_display}\n📖 {current_subject}\n📝 Answered: {answered_count}/{len(s['q'])}\n\n{question['question']}"
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    return QUIZ

def handle_quiz(update: Update, context: CallbackContext):
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
        s["i"] -= 1
        return send_q(q, context, user)
    elif data == "next":
        s["i"] += 1
        return send_q(q, context, user)
    elif data == "view_solution":
        return show_solution(q, context, user)
    elif data.startswith("select_"):
        idx = int(data.replace("select_", ""))
        s["answers"][s["i"]] = idx
        q.answer(f"Selected option {chr(65+idx)}")
        return send_q(q, context, user)
    
    return QUIZ

def submit_quiz(q, context, user):
    s = sessions.get(user)
    if not s:
        return ConversationHandler.END
    
    # Calculate score
    score = 0
    subject_scores = {}
    
    for i, ans in enumerate(s["answers"]):
        if ans is not None:
            question = s["q"][i]
            subject = question.get('subject', 'General')
            
            if subject not in subject_scores:
                subject_scores[subject] = {'score': 0, 'total': 0}
            subject_scores[subject]['total'] += 1
            
            if ans == question.get("correct", 0):
                score += 1
                subject_scores[subject]['score'] += 1
    
    # Calculate subject totals
    for question in s["q"]:
        subject = question.get('subject', 'General')
        if subject not in subject_scores:
            subject_scores[subject] = {'score': 0, 'total': 0}
        if subject_scores[subject]['total'] == 0:
            # Count total questions per subject
            subj_total = sum(1 for q_item in s["q"] if q_item.get('subject') == subject)
            subject_scores[subject]['total'] = subj_total
    
    s["score"] = score
    s["subject_scores"] = subject_scores
    s["submitted"] = True
    
    total = len(s["q"])
    percent = round(score / total * 100, 1) if total > 0 else 0
    time_taken = int(time.time() - s["start"])
    
    user_obj = q.from_user
    
    # Format subject scores for display
    subject_breakdown = ""
    for subj, data in subject_scores.items():
        subj_percent = round(data['score'] / data['total'] * 100, 1) if data['total'] > 0 else 0
        emoji = EMOJIS.get(subj, "📚")
        subject_breakdown += f"\n{emoji} {subj}: {data['score']}/{data['total']} ({subj_percent}%)"
    
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
        "time_taken": time_taken,
        "subject_scores": subject_scores,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db()
    
    if percent >= 80:
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
    txt += f"📚 Subjects: {', '.join(s['subjects'])}\n"
    txt += f"🎯 Score: {score}/{total}\n"
    txt += f"📈 Percent: {percent}%\n"
    txt += f"⏱️ Time: {format_time(time_taken)}\n"
    
    if subject_breakdown:
        txt += f"\n📊 SUBJECT BREAKDOWN:{subject_breakdown}\n"
    
    txt += f"\n{fb}\n\n"
    txt += "Would you like to see the solutions?"
    
    kb = [
        [InlineKeyboardButton("✅ YES - Show Solutions", callback_data="view_solution")],
        [InlineKeyboardButton("❌ NO - Finish", callback_data="finish_now")],
    ]
    
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    return VIEW_SOLUTION

def show_solution(q, context, user):
    s = sessions.get(user)
    if not s:
        q.edit_message_text("❌ Session expired.")
        return ConversationHandler.END
    
    # Build solution text
    txt = "📝 SOLUTIONS\n\n"
    
    for i, question in enumerate(s["q"]):
        user_ans = s["answers"][i]
        correct_idx = question.get("correct", 0)
        correct_ans = question["options"][correct_idx] if correct_idx < len(question["options"]) else "N/A"
        
        status = "✅" if user_ans == correct_idx else "❌"
        user_ans_text = question["options"][user_ans] if user_ans is not None and user_ans < len(question["options"]) else "Not answered"
        
        txt += f"{status} Q{i+1}: {question['question'][:50]}...\n"
        txt += f"   Your answer: {user_ans_text}\n"
        txt += f"   Correct: {correct_ans}\n\n"
        
        if len(txt) > 3500:  # Telegram message limit
            txt += "...\n(Use /myresult to see full summary)"
            break
    
    kb = [[InlineKeyboardButton("🏁 FINISH", callback_data="finish_now")]]
    q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    return VIEW_SOLUTION

def finish_now(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    user = q.from_user.id
    if user in sessions:
        del sessions[user]
    q.edit_message_text("✅ Quiz completed!\n\nUse /start_quiz to try again, or /myresult to see your score.")
    return ConversationHandler.END

def confirm_quit(q, context):
    kb = [
        [InlineKeyboardButton("✅ YES, END QUIZ", callback_data="force_quit")],
        [InlineKeyboardButton("❌ NO, CONTINUE", callback_data="resume")],
    ]
    q.edit_message_text(
        "⚠️ ARE YOU SURE?\n\nYour progress will be lost.",
        reply_markup=InlineKeyboardMarkup(kb)
    )
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

def finish(q, context, user, time_up=False):
    if time_up:
        return submit_quiz(q, context, user)
    return submit_quiz(q, context, user)

conv = ConversationHandler(
    entry_points=[CommandHandler("start_quiz", start_quiz)],
    states={
        CHOOSING_MODE: [CallbackQueryHandler(mode, pattern="^(exam|cbt)$")],
        SUBJECT: [CallbackQueryHandler(subject, pattern="^subj_")],
        CBT: [
            CallbackQueryHandler(cbt, pattern="^cbt_"),
            CallbackQueryHandler(cbt, pattern="^cbt_done$")
        ],
        QUIZ: [
            CallbackQueryHandler(handle_quiz, pattern="^(select_|prev|next|submit|quit)$"),
        ],
        CONFIRM_QUIT: [
            CallbackQueryHandler(force_quit, pattern="^force_quit$"),
            CallbackQueryHandler(resume, pattern="^resume$")
        ],
        VIEW_SOLUTION: [
            CallbackQueryHandler(show_solution, pattern="^view_solution$"),
            CallbackQueryHandler(finish_now, pattern="^finish_now$")
        ],
    },
    fallbacks=[],
    allow_reentry=True
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
        logger.info(f"✅ Webhook set to {render_url}/telegram")
    print(f"\n📊 Questions loaded:")
    for s, qs in ALL_Q.items():
        print(f"   {EMOJIS.get(s, '📚')} {s}: {len(qs)}")
    print(f"\n👑 Admin ID: {ADMIN_ID}")
    print(f"\n🚀 Bot starting on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT)
