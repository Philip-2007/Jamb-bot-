import os
import json
import random
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, ContextTypes

# ========== ENABLE LOGGING ==========
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_USER_ID = 6726456466
PORT = int(os.environ.get("PORT", 8000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")

# Conversation states
(CHOOSING_MODE, CHOOSING_EXAM_SUBJECT, CHOOSING_CBT_SUBJECTS, 
 CONFIRM_CBT, TAKING_QUIZ, REVIEW_MODE) = range(6)

# Available subjects (JSON files must be in same directory)
SUBJECTS = {
    "English": "english.json",
    "Mathematics": "math.json", 
    "Physics": "physics.json",
    "Chemistry": "chemistry.json",
    "Biology": "biology.json"
}

SUBJECT_EMOJIS = {
    "English": "📖",
    "Mathematics": "🧮",
    "Physics": "⚡",
    "Chemistry": "🧪",
    "Biology": "🧬"
}

# ========== LOAD QUESTIONS FROM JSON FILES ==========
def load_subject_questions(subject_key):
    filename = SUBJECTS.get(subject_key)
    if not filename:
        return []
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                all_questions = []
                for topic, questions in data.items():
                    if isinstance(questions, list):
                        for q in questions:
                            q["topic"] = topic
                            all_questions.append(q)
                return all_questions
    except Exception as e:
        logger.error(f"Error loading {filename}: {e}")
        return []

def get_all_questions():
    all_qs = {}
    for subject in SUBJECTS.keys():
        questions = load_subject_questions(subject)
        all_qs[subject] = questions
        logger.info(f"📚 Loaded {len(questions)} questions for {subject}")
    return all_qs

ALL_QUESTIONS = get_all_questions()

# ========== DATABASE (In-Memory) ==========
results_db = {"users": {}, "attempts": []}

def save_attempt(user_id, username, first_name, mode, subjects_taken, score, total, time_taken=None):
    results_db["users"][str(user_id)] = {
        "username": username,
        "first_name": first_name,
        "last_attempt": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    attempt_data = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "mode": mode,
        "subjects": subjects_taken,
        "score": score,
        "total": total,
        "percentage": round(score/total*100, 1) if total > 0 else 0,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    if time_taken:
        attempt_data["time_taken"] = time_taken
    results_db["attempts"].append(attempt_data)
    return attempt_data

# ========== SESSIONS ==========
user_sessions = {}

def is_admin(user_id):
    return user_id == ADMIN_USER_ID

def format_time(seconds):
    if seconds is None:
        return "N/A"
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"

# ========== BOT COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = f"""
📚 JAMB 2026 CBT MOCK EXAM BOT 📚

Welcome, {user.first_name}! 🎓

TEST MODES:

📝 EXAM MODE
• Full subject test (100 questions)

💻 CBT MODE
• English (Compulsory) + 3 subjects
• 40 questions per subject
• Total: 160 questions

🔹 Commands:
/start_quiz - Begin a new test
/myresult - View your last score
/progress - See your improvement
/help - Get assistance

📞 Admin: 08145090371
"""
    await update.message.reply_text(welcome_text)

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 EXAM MODE (Full Subject)", callback_data="mode_exam")],
        [InlineKeyboardButton("💻 CBT MODE (English + 3)", callback_data="mode_cbt")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎯 *SELECT TEST MODE*\n\n👇 Select an option below:", reply_markup=reply_markup, parse_mode="Markdown")
    return CHOOSING_MODE

async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.replace("mode_", "")
    
    if mode == "exam":
        keyboard = []
        for subject in SUBJECTS.keys():
            q_count = len(ALL_QUESTIONS.get(subject, []))
            if q_count > 0:
                emoji = SUBJECT_EMOJIS.get(subject, "📚")
                keyboard.append([InlineKeyboardButton(f"{emoji} {subject} ({q_count} questions)", callback_data=f"exam_{subject}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_mode")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")])
        await query.edit_message_text("*📝 EXAM MODE*\n\nSelect the subject you want to practice:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return CHOOSING_EXAM_SUBJECT
    else:
        context.user_data["cbt_subjects"] = ["English"]
        available = [s for s in SUBJECTS.keys() if s != "English" and len(ALL_QUESTIONS.get(s, [])) > 0]
        keyboard = []
        for subject in available:
            emoji = SUBJECT_EMOJIS.get(subject, "📚")
            keyboard.append([InlineKeyboardButton(f"{emoji} {subject}", callback_data=f"cbt_add_{subject}")])
        keyboard.append([InlineKeyboardButton("✅ Done Selecting", callback_data="cbt_done")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_mode")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")])
        await query.edit_message_text("*💻 CBT MODE*\n\n📖 *English* (Compulsory)\n\nSelect *3 additional subjects*:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return CHOOSING_CBT_SUBJECTS

async def handle_cbt_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "cbt_done":
        subjects = context.user_data.get("cbt_subjects", ["English"])
        if len(subjects) != 4:
            await query.answer(f"Select exactly 3 more subjects! (Now: {len(subjects)-1})", show_alert=True)
            return CHOOSING_CBT_SUBJECTS
        return await confirm_cbt_session(update, context)
    
    if data.startswith("cbt_add_"):
        subject = data.replace("cbt_add_", "")
        subjects = context.user_data.get("cbt_subjects", ["English"])
        if subject in subjects:
            subjects.remove(subject)
            await query.answer(f"Removed {subject}")
        else:
            if len(subjects) >= 4:
                await query.answer("You can only select 3 additional subjects!", show_alert=True)
                return CHOOSING_CBT_SUBJECTS
            subjects.append(subject)
            await query.answer(f"Added {subject}")
        context.user_data["cbt_subjects"] = subjects
        
        available = [s for s in SUBJECTS.keys() if s != "English" and len(ALL_QUESTIONS.get(s, [])) > 0]
        keyboard = []
        for subj in available:
            status = "✅ " if subj in subjects else ""
            emoji = SUBJECT_EMOJIS.get(subj, "📚")
            keyboard.append([InlineKeyboardButton(f"{status}{emoji} {subj}", callback_data=f"cbt_add_{subj}")])
        keyboard.append([InlineKeyboardButton("✅ Done Selecting", callback_data="cbt_done")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_mode")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")])
        
        subjects_display = ", ".join([s for s in subjects if s != "English"]) or "None yet"
        await query.edit_message_text(f"*💻 CBT MODE*\n\n📖 *English* (Compulsory) ✅\nSelected: *{subjects_display}* ({len(subjects)-1}/3)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return CHOOSING_CBT_SUBJECTS

async def confirm_cbt_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    subjects = context.user_data.get("cbt_subjects", ["English"])
    total_questions = sum(min(40, len(ALL_QUESTIONS.get(s, []))) for s in subjects)
    keyboard = [
        [InlineKeyboardButton("🚀 START CBT", callback_data="cbt_start")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_cbt_select")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")]
    ]
    await query.edit_message_text(f"*📋 CBT SESSION CONFIRMATION*\n\nSubjects: {', '.join(subjects)}\nTotal Questions: {total_questions}\n\nReady to begin?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CONFIRM_CBT

async def start_cbt_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    subjects = context.user_data.get("cbt_subjects", ["English"])
    
    all_selected_questions = []
    for subject in subjects:
        available = ALL_QUESTIONS.get(subject, [])
        if available:
            num_to_take = min(40, len(available))
            selected = random.sample(available, num_to_take)
            for q in selected:
                q["subject"] = subject
            all_selected_questions.extend(selected)
    
    random.shuffle(all_selected_questions)
    user_sessions[user_id] = {"mode": "cbt", "subjects": subjects, "questions": all_selected_questions, "current_q": 0, "score": 0, "answers": [], "start_time": datetime.now()}
    
    await query.edit_message_text(f"🎯 *CBT SESSION STARTING!*\n\nSubjects: {', '.join(subjects)}\nTotal Questions: {len(all_selected_questions)}\n\n*Good luck!* 🍀", parse_mode="Markdown")
    await send_question(query, context, user_id)
    return TAKING_QUIZ

async def handle_exam_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subject = query.data.replace("exam_", "")
    available = ALL_QUESTIONS.get(subject, [])
    keyboard = [
        [InlineKeyboardButton("🚀 START EXAM", callback_data=f"exam_start_{subject}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_mode")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")]
    ]
    await query.edit_message_text(f"*📝 EXAM MODE - {subject}*\n\n• Total Questions: {len(available)}\n\nReady to begin?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHOOSING_EXAM_SUBJECT

async def start_exam_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    subject = query.data.replace("exam_start_", "")
    available = ALL_QUESTIONS.get(subject, [])
    selected_questions = available.copy()
    random.shuffle(selected_questions)
    for q in selected_questions:
        q["subject"] = subject
    user_sessions[user_id] = {"mode": "exam", "subjects": [subject], "questions": selected_questions, "current_q": 0, "score": 0, "answers": [], "start_time": datetime.now()}
    await query.edit_message_text(f"🎯 *EXAM STARTING - {subject}*\n\nTotal Questions: {len(selected_questions)}\n\n*Good luck!* 🍀", parse_mode="Markdown")
    await send_question(query, context, user_id)
    return TAKING_QUIZ

async def send_question(update_or_query, context: ContextTypes.DEFAULT_TYPE, user_id):
    session = user_sessions.get(user_id)
    if not session:
        return
    q_index = session["current_q"]
    questions = session["questions"]
    if q_index >= len(questions):
        await finish_quiz(update_or_query, context, user_id)
        return
    
    question = questions[q_index]
    options = question["options"].copy()
    correct_idx = question.get("correct", 0)
    option_pairs = list(enumerate(options))
    random.shuffle(option_pairs)
    shuffled_options = []
    new_correct_idx = 0
    for i, (old_idx, text) in enumerate(option_pairs):
        shuffled_options.append(text)
        if old_idx == correct_idx:
            new_correct_idx = i
    session["_current_correct"] = new_correct_idx
    
    keyboard = []
    for i, option in enumerate(shuffled_options):
        display_text = option[:50] + "..." if len(option) > 50 else option
        keyboard.append([InlineKeyboardButton(f"{chr(65+i)}. {display_text}", callback_data=f"ans_{i}")])
    keyboard.append([InlineKeyboardButton("⏸️ Pause / Quit", callback_data="quit_quiz")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    progress = (q_index + 1) / len(questions)
    bar_length = 20
    filled = int(bar_length * progress)
    bar = "█" * filled + "░" * (bar_length - filled)
    subject = question.get("subject", "General")
    text = f"*Question {q_index + 1} of {len(questions)}*\n{bar} {int(progress * 100)}%\n\n📖 *Subject:* {subject}\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n{question['question']}"
    
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update_or_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("Session expired. Use /start_quiz again.")
        return ConversationHandler.END
    
    if query.data == "quit_quiz":
        return await confirm_quit(update, context)
    
    selected_idx = int(query.data.split("_")[1])
    q_index = session["current_q"]
    question = session["questions"][q_index]
    correct_idx = session.get("_current_correct", question.get("correct", 0))
    
    is_correct = (selected_idx == correct_idx)
    if is_correct:
        session["score"] += 1
    
    correct_answer = question["options"][question.get("correct", 0)]
    if is_correct:
        feedback_text = f"✅ *Correct!*\n\nAnswer: {correct_answer}"
    else:
        selected_answer = question["options"][selected_idx] if selected_idx < len(question["options"]) else ""
        feedback_text = f"❌ *Incorrect*\n\nYour answer: {selected_answer}\nCorrect answer: {correct_answer}"
    
    if "explanation" in question:
        feedback_text += f"\n\n📝 *Explanation:* {question['explanation']}"
    
    is_last = (q_index + 1 >= len(session["questions"]))
    next_text = "🏁 Finish" if is_last else "➡️ Next Question"
    keyboard = [[InlineKeyboardButton(next_text, callback_data="next_question")], [InlineKeyboardButton("⏸️ Quit", callback_data="quit_quiz")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(feedback_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    session["answers"].append({"question": question["question"], "selected": question["options"][selected_idx] if selected_idx < len(question["options"]) else "", "correct": correct_answer, "is_correct": is_correct, "subject": question.get("subject", "General")})
    return TAKING_QUIZ

async def next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("Session expired.")
        return ConversationHandler.END
    session["current_q"] += 1
    if session["current_q"] >= len(session["questions"]):
        await finish_quiz(query, context, user_id)
        return ConversationHandler.END
    await send_question(query, context, user_id)
    return TAKING_QUIZ

async def confirm_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✅ Yes, End Quiz", callback_data="force_quit")],
        [InlineKeyboardButton("❌ No, Continue", callback_data="resume_quiz")],
    ]
    await query.edit_message_text("*⚠️ Are you sure you want to quit?*\n\nYour progress will be lost.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return REVIEW_MODE

async def resume_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await send_question(query, context, user_id)
    return TAKING_QUIZ

async def force_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await query.edit_message_text("❌ *Quiz Cancelled*\n\nUse /start_quiz to try again!", parse_mode="Markdown")
    return ConversationHandler.END

async def finish_quiz(update_or_query, context: ContextTypes.DEFAULT_TYPE, user_id):
    session = user_sessions.pop(user_id, {})
    if not session:
        return ConversationHandler.END
    
    score = session.get("score", 0)
    total = len(session.get("questions", []))
    percentage = round(score/total*100, 1) if total > 0 else 0
    mode = session.get("mode", "unknown")
    subjects = session.get("subjects", [])
    
    start_time = session.get("start_time")
    time_taken = int((datetime.now() - start_time).total_seconds()) if start_time else None
    time_str = f"\n⏱️ *Time Taken:* {format_time(time_taken)}" if time_taken else ""
    
    user = update_or_query.from_user if hasattr(update_or_query, 'from_user') else update_or_query.message.from_user
    save_attempt(user_id, user.username or "No username", user.first_name, mode, ", ".join(subjects), score, total, time_taken)
    
    if percentage >= 80:
        feedback, emoji = "🌟 *Outstanding!* You're fully prepared!", "🏆"
    elif percentage >= 70:
        feedback, emoji = "👍 *Excellent!* Keep up the great work!", "🎯"
    elif percentage >= 60:
        feedback, emoji = "📚 *Good effort!* A little more practice and you'll ace it.", "💪"
    elif percentage >= 50:
        feedback, emoji = "📖 *Fair performance.* Review and try again.", "📝"
    else:
        feedback, emoji = "🌱 *Don't give up!* Study more and retake the quiz.", "🌱"
    
    result_text = f"{emoji} *QUIZ COMPLETED!* {emoji}\n\n📊 *Mode:* {mode.upper()}\n📚 *Subjects:* {', '.join(subjects)}\n\n🎯 *Overall Score:* {score}/{total}\n📈 *Percentage:* {percentage}%{time_str}\n\n{feedback}\n\nUse /start_quiz to try another test!\nUse /myresult to see this again."
    
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(result_text, parse_mode="Markdown")
    else:
        await update_or_query.message.reply_text(result_text, parse_mode="Markdown")
    return ConversationHandler.END

async def my_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_attempts = [a for a in results_db["attempts"] if a["user_id"] == user_id]
    if not user_attempts:
        await update.message.reply_text("❌ You haven't taken any quiz yet. Use /start_quiz")
        return
    last = user_attempts[-1]
    time_str = f"\n⏱️ Time Taken: {format_time(last.get('time_taken'))}" if last.get('time_taken') else ""
    result_text = f"📊 *YOUR LAST RESULT* 📊\n\nMode: {last.get('mode', 'N/A').upper()}\nSubjects: {last.get('subjects', 'N/A')}\nScore: {last['score']}/{last['total']}\nPercentage: {last['percentage']}%\nDate: {last['timestamp']}{time_str}\n\nUse /start_quiz to practice more!"
    await update.message.reply_text(result_text, parse_mode="Markdown")

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_attempts = [a for a in results_db["attempts"] if a["user_id"] == user_id]
    if len(user_attempts) < 2:
        await update.message.reply_text("Take at least 2 quizzes to see your progress!")
        return
    recent = user_attempts[-5:]
    text = "*📈 YOUR PROGRESS*\n\n"
    for i, a in enumerate(recent, 1):
        arrow = "•" if i == 1 else ("↗️" if a["percentage"] > recent[i-2]["percentage"] else "↘️")
        text += f"{arrow} {a['timestamp'][:10]}: *{a['percentage']}%* ({a['mode']})\n"
    change = recent[-1]["percentage"] - recent[0]["percentage"]
    trend = f"📈 *Improving!* (+{change:.1f}%)" if change > 0 else (f"📉 *Declining* ({change:.1f}%)" if change < 0 else "📊 *Stable.* Push harder!")
    text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n{trend}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    attempts = results_db["attempts"]
    if not attempts:
        await update.message.reply_text("No attempts recorded yet.")
        return
    total_participants = len(results_db["users"])
    total_attempts = len(attempts)
    avg_percentage = sum(a["percentage"] for a in attempts) / total_attempts
    sorted_attempts = sorted(attempts, key=lambda x: x["percentage"], reverse=True)[:10]
    stats_text = f"📈 *ADMIN DASHBOARD* 📈\n\n👥 *Participants:* {total_participants}\n📝 *Total Attempts:* {total_attempts}\n📊 *Average Score:* {avg_percentage:.1f}%\n\n━━━━━━━━━━━━━━━━━━━━━━\n🏆 *TOP 10 PERFORMERS:*"
    for i, a in enumerate(sorted_attempts, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        stats_text += f"\n{medal} {a['first_name']} - {a['percentage']}%"
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📌 *JAMB CBT BOT HELP*\n\n/start - Welcome\n/start_quiz - Begin test\n/myresult - Last score\n/progress - Track improvement\n\n📞 Admin: 08145090371", parse_mode="Markdown")

async def back_to_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📝 EXAM MODE", callback_data="mode_exam")],
        [InlineKeyboardButton("💻 CBT MODE", callback_data="mode_cbt")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")]
    ]
    await query.edit_message_text("🎯 *SELECT TEST MODE*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHOOSING_MODE

async def back_to_cbt_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["cbt_subjects"] = ["English"]
    available = [s for s in SUBJECTS.keys() if s != "English" and len(ALL_QUESTIONS.get(s, [])) > 0]
    keyboard = []
    for subject in available:
        emoji = SUBJECT_EMOJIS.get(subject, "📚")
        keyboard.append([InlineKeyboardButton(f"{emoji} {subject}", callback_data=f"cbt_add_{subject}")])
    keyboard.append([InlineKeyboardButton("✅ Done Selecting", callback_data="cbt_done")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_mode")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_quiz")])
    await query.edit_message_text("*💻 CBT MODE*\n\n📖 *English* (Compulsory)\n\nSelect *3 additional subjects*:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
  return CHOOSING_CBT_SUBJECTS

async def cancel_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await query.edit_message_text("❌ Quiz cancelled.\n\nUse /start_quiz when you're ready!")
    return ConversationHandler.END

# ========== MAIN APPLICATION ==========
def main():
    print("╔════════════════════════════════════════╗")
    print("║     🤖 JAMB 2026 CBT BOT STARTING      ║")
    print("╚════════════════════════════════════════╝")
    
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")
    
    print(f"\n📊 Total Questions Loaded:")
    for subject, qs in ALL_QUESTIONS.items():
        print(f"   {SUBJECT_EMOJIS.get(subject, '📚')} {subject}: {len(qs)}")
    print(f"\n👑 Admin ID: {ADMIN_USER_ID}")
    
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start_quiz", start_quiz)],
        states={
            CHOOSING_MODE: [CallbackQueryHandler(choose_mode, pattern="^mode_"), CallbackQueryHandler(cancel_quiz, pattern="^cancel_quiz$")],
            CHOOSING_EXAM_SUBJECT: [CallbackQueryHandler(handle_exam_selection, pattern="^exam_(?!start)"), CallbackQueryHandler(start_exam_quiz, pattern="^exam_start_"), CallbackQueryHandler(back_to_mode, pattern="^back_mode$"), CallbackQueryHandler(cancel_quiz, pattern="^cancel_quiz$")],
            CHOOSING_CBT_SUBJECTS: [CallbackQueryHandler(handle_cbt_selection, pattern="^cbt_"), CallbackQueryHandler(back_to_mode, pattern="^back_mode$"), CallbackQueryHandler(cancel_quiz, pattern="^cancel_quiz$")],
            CONFIRM_CBT: [CallbackQueryHandler(start_cbt_quiz, pattern="^cbt_start$"), CallbackQueryHandler(back_to_cbt_select, pattern="^back_cbt_select$"), CallbackQueryHandler(cancel_quiz, pattern="^cancel_quiz$")],
            TAKING_QUIZ: [CallbackQueryHandler(handle_answer, pattern="^ans_"), CallbackQueryHandler(next_question, pattern="^next_question$"), CallbackQueryHandler(confirm_quit, pattern="^quit_quiz$")],
            REVIEW_MODE: [CallbackQueryHandler(force_quit, pattern="^force_quit$"), CallbackQueryHandler(resume_quiz, pattern="^resume_quiz$")],
        },
        fallbacks=[CommandHandler("start_quiz", start_quiz)],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myresult", my_result))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin_stats", admin_stats))
    
    print("\n🔄 Starting bot with webhook...")
    webhook_url = f"{RENDER_URL}/telegram"
    app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=webhook_url)
    print(f"✅ Bot is LIVE at {RENDER_URL}")

if __name__ == "__main__":
    main()
