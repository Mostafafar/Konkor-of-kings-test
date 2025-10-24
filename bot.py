import os
import logging
import psycopg2
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
    KeyboardButton,
    ChatAction
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

# ==============================
# تنظیمات اولیه
# ==============================

DB_CONFIG = {
    'dbname': 'quiz_bot_db',
    'user': 'postgres',
    'password': 'f13821382',
    'host': 'localhost',
    'port': '5432'
}

BOT_TOKEN = "7502637474:AAGQmU_4c4p5TS6PJrP_e5dOPvu2v8K95L0"
ADMIN_ID = 6680287530
PHOTOS_DIR = "photos"
MAX_USERS_DISPLAY = 20
MAX_RESULTS_DISPLAY = 15

# ایجاد پوشه عکس‌ها
os.makedirs(PHOTOS_DIR, exist_ok=True)

# تنظیم لاگ پیشرفته
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# اتصال سراسری دیتابیس
db_connection = None


# ==============================
# توابع کمکی عمومی
# ==============================

def safe_execute(query: str, params: tuple = None, fetch: bool = False, return_id: bool = False):
    """اجرای ایمن کوئری با مدیریت خطا"""
    try:
        with db_connection.cursor() as cursor:
            cursor.execute(query, params or ())
            if fetch:
                result = cursor.fetchall()
                db_connection.commit()
                return result
            elif return_id and cursor.rowcount > 0:
                result = cursor.fetchone()
                db_connection.commit()
                return result[0] if result else None
            else:
                db_connection.commit()
                return cursor.rowcount
    except Exception as e:
        logger.error(f"Database error: {e}\n{traceback.format_exc()}")
        db_connection.rollback()
        return None


def format_time(seconds: int) -> str:
    """تبدیل ثانیه به دقیقه:ثانیه"""
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins}:{secs:02d}"


def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    """ارسال اعلان به ادمین"""
    try:
        asyncio.create_task(context.bot.send_message(ADMIN_ID, message))
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")


# ==============================
# توابع دیتابیس
# ==============================

def init_database() -> bool:
    """راه‌اندازی دیتابیس"""
    global db_connection
    try:
        db_connection = psycopg2.connect(**DB_CONFIG)
        logger.info("Connected to PostgreSQL")

        tables = [
            '''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                phone_number TEXT,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS quizzes (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                time_limit INTEGER DEFAULT 60,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                question_image TEXT NOT NULL,
                correct_answer INTEGER NOT NULL CHECK (correct_answer BETWEEN 1 AND 4),
                points INTEGER DEFAULT 1,
                question_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS user_answers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
                selected_answer INTEGER CHECK (selected_answer BETWEEN 1 AND 4),
                answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, quiz_id, question_id)
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS results (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                score REAL DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                wrong_answers INTEGER DEFAULT 0,
                unanswered_questions INTEGER DEFAULT 0,
                total_time INTEGER DEFAULT 0,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, quiz_id)
            )
            '''
        ]

        for table_sql in tables:
            safe_execute(table_sql)

        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.critical(f"Database connection failed: {e}")
        return False


# ==============================
# عملیات کاربران
# ==============================

def get_user(user_id: int) -> Optional[Tuple]:
    return safe_execute("SELECT * FROM users WHERE user_id = %s", (user_id,), fetch=True)


def register_user(user_id: int, phone: str = "", username: str = "", full_name: str = "") -> bool:
    """ثبت یا بروزرسانی کاربر"""
    return safe_execute('''
        INSERT INTO users (user_id, phone_number, username, full_name) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET 
            phone_number = EXCLUDED.phone_number,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name
    ''', (user_id, phone, username, full_name)) is not None


def get_active_quizzes() -> List[Tuple]:
    return safe_execute(
        "SELECT id, title, description, time_limit FROM quizzes WHERE is_active = TRUE ORDER BY created_at DESC",
        fetch=True
    ) or []


def get_quiz_info(quiz_id: int) -> Optional[Tuple]:
    result = safe_execute("SELECT title, description, time_limit, is_active FROM quizzes WHERE id = %s", (quiz_id,), fetch=True)
    return result[0] if result else None


def get_quiz_questions(quiz_id: int) -> List[Tuple]:
    return safe_execute(
        "SELECT id, question_image, correct_answer FROM questions WHERE quiz_id = %s ORDER BY question_order, id",
        (quiz_id,), fetch=True
    ) or []


def save_user_answer(user_id: int, quiz_id: int, question_id: int, answer: int) -> bool:
    return safe_execute('''
        INSERT INTO user_answers (user_id, quiz_id, question_id, selected_answer) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, quiz_id, question_id) 
        DO UPDATE SET selected_answer = EXCLUDED.selected_answer, answered_at = CURRENT_TIMESTAMP
    ''', (user_id, quiz_id, question_id, answer)) is not None


def get_user_answers(user_id: int, quiz_id: int) -> Dict[int, int]:
    rows = safe_execute(
        "SELECT question_id, selected_answer FROM user_answers WHERE user_id = %s AND quiz_id = %s",
        (user_id, quiz_id), fetch=True
    ) or []
    return {qid: ans for qid, ans in rows}


def clear_user_answers(user_id: int, quiz_id: int):
    safe_execute("DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s", (user_id, quiz_id))


def save_result(user_id: int, quiz_id: int, score: float, total_time: int,
                correct: int = 0, wrong: int = 0, unanswered: int = 0) -> bool:
    return safe_execute('''
        INSERT INTO results (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, quiz_id) DO UPDATE SET
            score = EXCLUDED.score,
            total_time = EXCLUDED.total_time,
            correct_answers = EXCLUDED.correct_answers,
            wrong_answers = EXCLUDED.wrong_answers,
            unanswered_questions = EXCLUDED.unanswered_questions,
            completed_at = CURRENT_TIMESTAMP
    ''', (user_id, quiz_id, score, total_time, correct, wrong, unanswered)) is not None


def create_quiz(title: str, desc: str, time_limit: int) -> Optional[int]:
    return safe_execute('''
        INSERT INTO quizzes (title, description, time_limit, is_active) 
        VALUES (%s, %s, %s, TRUE) RETURNING id
    ''', (title, desc, time_limit), return_id=True)


def add_question(quiz_id: int, image_path: str, correct_answer: int, order: int) -> bool:
    return safe_execute('''
        INSERT INTO questions (quiz_id, question_image, correct_answer, question_order)
        VALUES (%s, %s, %s, %s)
    ''', (quiz_id, image_path, correct_answer, order)) is not None


def toggle_quiz_status(quiz_id: int) -> bool:
    return safe_execute('UPDATE quizzes SET is_active = NOT is_active WHERE id = %s', (quiz_id,)) is not None


def get_all_users() -> List[Tuple]:
    return safe_execute(
        "SELECT user_id, full_name, username, phone_number, registered_at FROM users ORDER BY registered_at DESC",
        fetch=True
    ) or []


def get_all_results() -> List[Tuple]:
    return safe_execute('''
        SELECT u.full_name, q.title, r.score, r.total_time, r.completed_at 
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        JOIN quizzes q ON r.quiz_id = q.id
        ORDER BY r.completed_at DESC
    ''', fetch=True) or []


# ==============================
# منوهای اصلی (ReplyKeyboardMarkup)
# ==============================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["شرکت در آزمون"],
        ["راهنما"]
    ]
    if update.effective_user.id == ADMIN_ID:
        keyboard.append(["پنل ادمین"])

    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    text = "منوی اصلی:"

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def show_quiz_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quizzes = get_active_quizzes()
    if not quizzes:
        markup = ReplyKeyboardMarkup([["منوی اصلی"]], resize_keyboard=True)
        await update.message.reply_text("هیچ آزمون فعالی وجود ندارد.", reply_markup=markup)
        return

    keyboard = []
    text = "لیست آزمون‌های فعال:\n\n"
    for q in quizzes:
        quiz_id, title, desc, time = q
        btn = f"{time} دقیقه - {title}"
        keyboard.append([btn])
        text += f"• {title}\n{time} دقیقه\n{desc}\n\n"

    keyboard.append(["منوی اصلی"])
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=markup)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "راهنمای استفاده:\n\n"
        "1. از منو آزمون مورد نظر را انتخاب کنید\n"
        "2. زمان محدود است\n"
        "3. گزینه‌ها را انتخاب کنید (قابل تغییر)\n"
        "4. سوالات مشکوک را علامت‌گذاری کنید\n"
        "5. در انتها مرور و ثبت نهایی\n"
        "6. نتایج به ادمین ارسال می‌شود\n\n"
        "موفق باشید!"
    )
    markup = ReplyKeyboardMarkup([["منوی اصلی"]], resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=markup)


# ==============================
# پنل ادمین (ReplyKeyboardMarkup)
# ==============================

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("دسترسی غیرمجاز!")
        return

    keyboard = [
        ["ایجاد آزمون جدید"],
        ["مدیریت آزمون‌ها"],
        ["مشاهده کاربران"],
        ["مشاهده نتایج"],
        ["منوی اصلی"]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("پنل ادمین:", reply_markup=markup)


async def admin_manage_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    quizzes = safe_execute("SELECT id, title, is_active FROM quizzes ORDER BY created_at DESC", fetch=True) or []
    if not quizzes:
        markup = ReplyKeyboardMarkup([["پنل ادمین"]], resize_keyboard=True)
        await update.message.reply_text("هیچ آزمونی وجود ندارد.", reply_markup=markup)
        return

    text = "مدیریت آزمون‌ها:\n\n"
    keyboard = []
    for qid, title, active in quizzes:
        status = "فعال" if active else "غیرفعال"
        action = "غیرفعال" if active else "فعال"
        keyboard.append([f"{action} کردن '{title}'"])
        text += f"{title} - {status}\n"

    keyboard.append(["پنل ادمین"])
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=markup)


async def admin_view_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    users = get_all_users()
    if not users:
        markup = ReplyKeyboardMarkup([["پنل ادمین"]], resize_keyboard=True)
        await update.message.reply_text("هیچ کاربری ثبت نشده.", reply_markup=markup)
        return

    text = "کاربران ثبت‌شده:\n\n"
    for u in users[:MAX_USERS_DISPLAY]:
        uid, name, uname, phone, reg = u
        text += f"{name}\n{phone or 'ندارد'}\n@{uname or 'ندارد'}\n{uid}\n{reg.strftime('%Y-%m-%d %H:%M')}\n"
        text += "─" * 20 + "\n"

    if len(users) > MAX_USERS_DISPLAY:
        text += f"\nو {len(users) - MAX_USERS_DISPLAY} کاربر دیگر..."

    markup = ReplyKeyboardMarkup([["پنل ادمین"]], resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=markup)


async def admin_view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    results = get_all_results()
    if not results:
        markup = ReplyKeyboardMarkup([["پنل ادمین"]], resize_keyboard=True)
        await update.message.reply_text("هیچ نتیجه‌ای ثبت نشده.", reply_markup=markup)
        return

    text = "نتایج آزمون‌ها:\n\n"
    for r in results[:MAX_RESULTS_DISPLAY]:
        name, title, score, time, date = r
        tstr = format_time(time)
        text += f"{name}\n{title}\n{score:.1f}%\n{tstr}\n{date.strftime('%Y-%m-%d %H:%M')}\n"
        text += "─" * 20 + "\n"

    if len(results) > MAX_RESULTS_DISPLAY:
        text += f"\nو {len(results) - MAX_RESULTS_DISPLAY} نتیجه دیگر..."

    markup = ReplyKeyboardMarkup([["پنل ادمین"]], resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=markup)


# ==============================
# فرآیند آزمون (InlineKeyboardMarkup)
# ==============================

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    user_id = update.effective_user.id
    info = get_quiz_info(quiz_id)
    if not info:
        await update.message.reply_text("آزمون یافت نشد.")
        return

    title, desc, time_limit, active = info
    if not active:
        await update.message.reply_text("این آزمون غیرفعال است.")
        return

    questions = get_quiz_questions(quiz_id)
    if not questions:
        await update.message.reply_text("سوالی برای این آزمون تعریف نشده.")
        return

    clear_user_answers(user_id, quiz_id)

    context.user_data['current_quiz'] = {
        'quiz_id': quiz_id,
        'questions': questions,
        'current_index': 0,
        'start_time': datetime.now(),
        'time_limit': time_limit,
        'title': title
    }

    context.job_queue.run_once(
        quiz_timeout,
        time_limit * 60,
        user_id=user_id,
        data={'quiz_id': quiz_id, 'chat_id': update.effective_chat.id, 'time_limit': time_limit},
        name=f"timeout_{user_id}_{quiz_id}"
    )

    await show_question(update, context)


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quiz = context.user_data.get('current_quiz')
    if not quiz:
        return

    idx = quiz['current_index']
    questions = quiz['questions']
    if idx >= len(questions):
        return

    q = questions[idx]
    qid, img_path, correct = q

    answers = get_user_answers(update.effective_user.id, quiz['quiz_id'])
    selected = answers.get(qid)

    keyboard = []
    for i in range(1, 5):
        prefix = "پاسخ صحیح" if selected == i else ""
        keyboard.append([InlineKeyboardButton(
            f"{prefix}گزینه {i}",
            callback_data=f"ans_{quiz['quiz_id']}_{idx}_{i}"
        )])

    marked = context.user_data.get('marked_questions', set())
    mark_text = "علامت‌گذاری شده" if idx in marked else "علامت‌گذاری"
    keyboard.append([InlineKeyboardButton(mark_text, callback_data=f"mark_{quiz['quiz_id']}_{idx}")])

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("قبلی", callback_data=f"nav_{idx-1}"))
    if idx < len(questions) - 1:
        nav.append(InlineKeyboardButton("بعدی", callback_data=f"nav_{idx+1}"))
    if nav:
        keyboard.append(nav)

    if idx == len(questions) - 1:
        mcount = len(marked)
        if mcount:
            keyboard.append([InlineKeyboardButton(f"مرور ({mcount})", callback_data="review_marked")])
        keyboard.append([InlineKeyboardButton("ثبت نهایی", callback_data=f"submit_{quiz['quiz_id']}")])

    markup = InlineKeyboardMarkup(keyboard)
    caption = f"سوال {idx + 1} از {len(questions)}\n{quiz['title']}"

    try:
        if os.path.exists(img_path):
            with open(img_path, 'rb') as photo:
                if update.callback_query and update.callback_query.message.photo:
                    await update.callback_query.edit_message_media(
                        media=InputMediaPhoto(photo, caption=caption),
                        reply_markup=markup
                    )
                else:
                    await update.message.reply_photo(photo, caption=caption, reply_markup=markup)
        else:
            await update.callback_query.edit_message_text(f"{caption}\n\nتصویر یافت نشد!", reply_markup=markup)
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await update.callback_query.edit_message_text("خطا در نمایش سوال!", reply_markup=markup)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int, qidx: int, answer: int):
    user_id = update.effective_user.id
    quiz = context.user_data.get('current_quiz')
    if not quiz or quiz['quiz_id'] != quiz_id:
        return

    qid = quiz['questions'][qidx][0]
    current = get_user_answers(user_id, quiz_id).get(qid)

    if current == answer:
        safe_execute("DELETE FROM user_answers WHERE user_id=%s AND quiz_id=%s AND question_id=%s", (user_id, quiz_id, qid))
        await update.callback_query.answer("تیک برداشته شد")
    else:
        save_user_answer(user_id, quiz_id, qid, answer)
        await update.callback_query.answer("پاسخ ثبت شد")

    await show_question(update, context)


async def toggle_mark(update: Update, context: ContextTypes.DEFAULT_TYPE, qidx: int):
    marked = context.user_data.get('marked_questions', set())
    if qidx in marked:
        marked.remove(qidx)
        await update.callback_query.answer("علامت برداشته شد")
    else:
        marked.add(qidx)
        await update.callback_query.answer("علامت‌گذاری شد")
    context.user_data['marked_questions'] = marked
    await show_question(update, context)


async def navigate_to_question(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int):
    quiz = context.user_data.get('current_quiz')
    if quiz and 0 <= idx < len(quiz['questions']):
        quiz['current_index'] = idx
        await show_question(update, context)


async def submit_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    user_id = update.effective_user.id
    quiz = context.user_data.get('current_quiz')
    if not quiz or quiz['quiz_id'] != quiz_id:
        return

    total_time = int((datetime.now() - quiz['start_time']).total_seconds())
    answers = get_user_answers(user_id, quiz_id)
    questions = quiz['questions']

    correct = wrong = unanswered = 0
    for i, q in enumerate(questions):
        qid, _, correct_ans = q
        user_ans = answers.get(qid)
        if user_ans is None:
            unanswered += 1
        elif user_ans == correct_ans:
            correct += 1
        else:
            wrong += 1

    penalty = wrong / 3.0
    final_score = max(0, correct - penalty)
    percentage = (final_score / len(questions)) * 100 if questions else 0

    save_result(user_id, quiz_id, percentage, total_time, correct, wrong, unanswered)

    user_msg = (
        f"آزمون ثبت شد!\n\n"
        f"صحیح: {correct}\nغلط: {wrong}\nبی‌پاسخ: {unanswered}\n"
        f"درصد: {percentage:.2f}%\nزمان: {format_time(total_time)}"
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]])
    await update.callback_query.edit_message_text(user_msg, reply_markup=markup)

    # پاکسازی
    for key in ['current_quiz', 'marked_questions', 'review_mode']:
        context.user_data.pop(key, None)


async def quiz_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.user_id
    data = job.data
    quiz_id = data['quiz_id']
    chat_id = data['chat_id']

    questions = get_quiz_questions(quiz_id)
    if not questions:
        return

    answers = get_user_answers(user_id, quiz_id)
    correct = wrong = unanswered = 0

    for q in questions:
        qid, _, correct_ans = q
        user_ans = answers.get(qid)
        if user_ans is None:
            unanswered += 1
        elif user_ans == correct_ans:
            correct += 1
        else:
            wrong += 1

    penalty = wrong / 3.0
    final_score = max(0, correct - penalty)
    percentage = (final_score / len(questions)) * 100

    save_result(user_id, quiz_id, percentage, data['time_limit'] * 60, correct, wrong, unanswered)

    msg = (
        f"زمان به پایان رسید!\n\n"
        f"صحیح: {correct} | غلط: {wrong} | بی‌پاسخ: {unanswered}\n"
        f"درصد نهایی: {percentage:.2f}%"
    )
    await context.bot.send_message(chat_id, msg, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
    ]))


# ==============================
# مدیریت پیام‌ها
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message.text else ""

    if update.message.contact:
        await handle_contact(update, context)
        return

    if text == "شرکت در آزمون":
        await show_quiz_list(update, context)
    elif text == "راهنما":
        await show_help(update, context)
    elif text == "پنل ادمین" and update.effective_user.id == ADMIN_ID:
        await show_admin_panel(update, context)
    elif text == "منوی اصلی":
        await show_main_menu(update, context)
    elif text == "ایجاد آزمون جدید" and update.effective_user.id == ADMIN_ID:
        await admin_create_quiz(update, context)
    elif text == "مدیریت آزمون‌ها" and update.effective_user.id == ADMIN_ID:
        await admin_manage_quizzes(update, context)
    elif text == "مشاهده کاربران" and update.effective_user.id == ADMIN_ID:
        await admin_view_users(update, context)
    elif text == "مشاهده نتایج" and update.effective_user.id == ADMIN_ID:
        await admin_view_results(update, context)
    elif text.startswith(("فعال کردن", "غیرفعال کردن")) and update.effective_user.id == ADMIN_ID:
        try:
            title = text.split("'", 1)[1].rsplit("'", 1)[0]
            q = safe_execute("SELECT id FROM quizzes WHERE title = %s", (title,), fetch=True)
            if q:
                toggle_quiz_status(q[0][0])
                await update.message.reply_text(f"وضعیت '{title}' تغییر کرد.")
                await admin_manage_quizzes(update, context)
        except:
            pass
    elif any(text.endswith(f" دقیقه - {q[1]}") for q in get_active_quizzes()):
        title = text.split(" - ", 1)[1]
        q = safe_execute("SELECT id FROM quizzes WHERE title = %s AND is_active = TRUE", (title,), fetch=True)
        if q:
            await start_quiz(update, context, q[0][0])
    else:
        await handle_admin_text(update, context)


# ==============================
# ادمین: ایجاد آزمون
# ==============================

async def admin_create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data['admin_action'] = 'creating_quiz'
    context.user_data['quiz_data'] = {'step': 'title'}
    await update.message.reply_text("عنوان آزمون را وارد کنید:")


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or 'admin_action' not in context.user_data:
        return

    text = update.message.text.strip()
    action = context.user_data['admin_action']
    data = context.user_data.get('quiz_data', {})

    if action == 'creating_quiz':
        step = data.get('step')
        if step == 'title':
            data['title'] = text
            data['step'] = 'description'
            await update.message.reply_text("توضیحات آزمون را وارد کنید:")
        elif step == 'description':
            data['description'] = text
            data['step'] = 'time_limit'
            await update.message.reply_text("زمان آزمون (دقیقه):")
        elif step == 'time_limit':
            try:
                t = int(text)
                if t <= 0:
                    raise ValueError
                quiz_id = create_quiz(data['title'], data['description'], t)
                if quiz_id:
                    data['quiz_id'] = quiz_id
                    data['step'] = 'add_questions'
                    context.user_data['quiz_data'] = data
                    markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("افزودن سوالات", callback_data="confirm_add_questions")],
                        [InlineKeyboardButton("بازگشت", callback_data="admin_panel")]
                    ])
                    await update.message.reply_text(
                        f"آزمون ایجاد شد:\n\n"
                        f"عنوان: {data['title']}\n"
                        f"زمان: {t} دقیقه\n\n"
                        f"افزودن سوالات؟",
                        reply_markup=markup
                    )
                else:
                    await update.message.reply_text("خطا در ایجاد آزمون!")
            except:
                await update.message.reply_text("عدد صحیح مثبت وارد کنید:")

    elif action == 'adding_questions' and data.get('step') == 'correct_answer':
        try:
            ans = int(text)
            if 1 <= ans <= 4:
                img = data['current_image']
                order = len(data.get('questions', [])) + 1
                if add_question(data['quiz_id'], img, ans, order):
                    data.setdefault('questions', []).append({'img': img, 'ans': ans})
                    markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("سوال بعدی", callback_data="add_another_question")],
                        [InlineKeyboardButton("اتمام", callback_data="admin_panel")]
                    ])
                    await update.message.reply_text(
                        f"سوال {order} ذخیره شد.\nپاسخ صحیح: گزینه {ans}\n\nادامه؟",
                        reply_markup=markup
                    )
                    data.pop('current_image', None)
                    data['step'] = 'waiting'
                else:
                    await update.message.reply_text("خطا در ذخیره سوال!")
            else:
                raise ValueError
        except:
            await update.message.reply_text("عدد 1 تا 4 وارد کنید:")

    context.user_data['quiz_data'] = data


async def handle_admin_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or context.user_data.get('admin_action') != 'adding_questions':
        return

    data = context.user_data.get('quiz_data', {})
    if data.get('step') != 'question_image':
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    filename = f"q_{data['quiz_id']}_{len(data.get('questions', [])) + 1}.jpg"
    path = os.path.join(PHOTOS_DIR, filename)
    await file.download_to_drive(path)

    data['current_image'] = path
    data['step'] = 'correct_answer'
    context.user_data['quiz_data'] = data

    await update.message.reply_text("عکس ذخیره شد.\nگزینه صحیح (1-4):")


async def start_adding_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = context.user_data.get('quiz_data', {})
    if 'quiz_id' not in data:
        return

    context.user_data['admin_action'] = 'adding_questions'
    data['step'] = 'question_image'
    context.user_data['quiz_data'] = data
    await update.callback_query.edit_message_text("عکس سوال را ارسال کنید:")


# ==============================
# هندلرها
# ==============================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not get_user(user.id):
        register_user(user.id, "", user.username, user.full_name)
        notify_admin(context, f"کاربر جدید:\n{user.full_name}\n@{user.username or 'ندارد'}\nID: {user.id}")
    await show_main_menu(update, context)


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if contact.user_id != update.effective_user.id:
        await update.message.reply_text("شماره خودتان را ارسال کنید.")
        return
    register_user(contact.user_id, contact.phone_number, update.effective_user.username, update.effective_user.full_name)
    await update.message.reply_text("ثبت نام موفق!", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("ans_"):
        p = data.split("_")
        await handle_answer(update, context, int(p[1]), int(p[2]), int(p[3]))
    elif data.startswith("mark_"):
        await toggle_mark(update, context, int(data.split("_")[2]))
    elif data.startswith("nav_"):
        await navigate_to_question(update, context, int(data.split("_")[1]))
    elif data.startswith("submit_"):
        await submit_quiz(update, context, int(data.split("_")[1]))
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "confirm_add_questions":
        await start_adding_questions(update, context)
    elif data == "add_another_question":
        await start_adding_questions(update, context)
    elif data == "admin_panel":
        await show_admin_panel(update, context)


# ==============================
# اجرای ربات
# ==============================

def main():
    if not init_database():
        logger.critical("Failed to initialize database. Exiting.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.PHOTO, handle_admin_photos))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("ربات با موفقیت راه‌اندازی شد.")
    print("ربات در حال اجرا...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
