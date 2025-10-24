import os
import logging
import psycopg2
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
    KeyboardButton
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
# تنظیمات دیتابیس و ربات
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

os.makedirs(PHOTOS_DIR, exist_ok=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db_connection = None


# ==============================
# توابع دیتابیس
# ==============================

def init_database():
    """اتصال به دیتابیس و ایجاد جداول"""
    global db_connection
    try:
        db_connection = psycopg2.connect(**DB_CONFIG)
        logger.info("Connected to PostgreSQL database")

        cursor = db_connection.cursor()

        # جدول کاربران
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                phone_number TEXT,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # جدول آزمون‌ها
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quizzes (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                time_limit INTEGER DEFAULT 60,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # جدول سوالات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                question_image TEXT NOT NULL,
                correct_answer INTEGER NOT NULL,
                points INTEGER DEFAULT 1,
                question_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # جدول پاسخ‌های کاربران
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_answers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
                selected_answer INTEGER,
                answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, quiz_id, question_id)
            )
        ''')

        # جدول نتایج
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                score REAL DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                wrong_answers INTEGER DEFAULT 0,
                unanswered_questions INTEGER DEFAULT 0,
                total_time INTEGER DEFAULT 0,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        db_connection.commit()
        logger.info("Database tables created successfully")

    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        if db_connection:
            db_connection.rollback()


def execute_query(query: str, params: tuple = None, return_id: bool = False):
    """اجرای کوئری و بازگشت نتیجه"""
    try:
        cursor = db_connection.cursor()
        cursor.execute(query, params or ())

        if query.strip().upper().startswith('SELECT') or return_id:
            result = cursor.fetchall()
            db_connection.commit()
            return result
        else:
            db_connection.commit()
            return cursor.rowcount

    except Exception as e:
        logger.error(f"Query execution error: {e}")
        if db_connection:
            db_connection.rollback()
        return None


def get_user(user_id: int):
    """دریافت اطلاعات کاربر"""
    return execute_query("SELECT * FROM users WHERE user_id = %s", (user_id,))


def add_user(user_id: int, phone_number: str, username: str, full_name: str):
    """افزودن کاربر جدید"""
    return execute_query('''
        INSERT INTO users (user_id, phone_number, username, full_name) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET 
        phone_number = EXCLUDED.phone_number,
        username = EXCLUDED.username,
        full_name = EXCLUDED.full_name
    ''', (user_id, phone_number, username, full_name))


def get_active_quizzes():
    """دریافت آزمون‌های فعال"""
    return execute_query(
        "SELECT id, title, description, time_limit FROM quizzes WHERE is_active = TRUE ORDER BY id"
    )


def get_quiz_questions(quiz_id: int):
    """دریافت سوالات یک آزمون"""
    return execute_query(
        "SELECT id, question_image, correct_answer FROM questions WHERE quiz_id = %s ORDER BY question_order, id",
        (quiz_id,)
    )


def save_user_answer(user_id: int, quiz_id: int, question_id: int, answer: int):
    """ذخیره یا بروزرسانی پاسخ کاربر"""
    return execute_query('''
        INSERT INTO user_answers (user_id, quiz_id, question_id, selected_answer) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, quiz_id, question_id) 
        DO UPDATE SET selected_answer = EXCLUDED.selected_answer, answered_at = CURRENT_TIMESTAMP
    ''', (user_id, quiz_id, question_id, answer))


def get_user_answers(user_id: int, quiz_id: int):
    """دریافت پاسخ‌های کاربر برای یک آزمون"""
    return execute_query(
        "SELECT question_id, selected_answer FROM user_answers WHERE user_id = %s AND quiz_id = %s",
        (user_id, quiz_id)
    )


def clear_user_answers(user_id: int, quiz_id: int):
    """پاک کردن پاسخ‌های کاربر"""
    return execute_query(
        "DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s",
        (user_id, quiz_id)
    )


def save_result(user_id: int, quiz_id: int, score: float, total_time: int,
                correct_answers: int = 0, wrong_answers: int = 0, unanswered_questions: int = 0):
    """ذخیره نتیجه آزمون"""
    return execute_query('''
        INSERT INTO results (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    ''', (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions))


def create_quiz(title: str, description: str, time_limit: int):
    """ایجاد آزمون جدید"""
    result = execute_query('''
        INSERT INTO quizzes (title, description, time_limit, is_active) 
        VALUES (%s, %s, %s, TRUE) 
        RETURNING id
    ''', (title, description, time_limit), return_id=True)

    if result and len(result) > 0:
        return result[0][0]
    return None


def add_question(quiz_id: int, question_image: str, correct_answer: int, question_order: int):
    """افزودن سوال به آزمون"""
    return execute_query('''
        INSERT INTO questions 
        (quiz_id, question_image, correct_answer, question_order)
        VALUES (%s, %s, %s, %s)
    ''', (quiz_id, question_image, correct_answer, question_order))


def get_question_count(quiz_id: int):
    """دریافت تعداد سوالات یک آزمون"""
    result = execute_query("SELECT COUNT(*) FROM questions WHERE quiz_id = %s", (quiz_id,))
    return result[0][0] if result else 0


def get_quiz_info(quiz_id: int):
    """دریافت اطلاعات آزمون"""
    result = execute_query(
        "SELECT title, description, time_limit, is_active FROM quizzes WHERE id = %s",
        (quiz_id,)
    )
    return result[0] if result else None


def get_all_users():
    """دریافت تمام کاربران"""
    return execute_query(
        "SELECT user_id, full_name, username, phone_number, registered_at FROM users ORDER BY registered_at DESC"
    )


def get_all_results():
    """دریافت تمام نتایج"""
    return execute_query('''
        SELECT u.full_name, q.title, r.score, r.total_time, r.completed_at 
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        JOIN quizzes q ON r.quiz_id = q.id
        ORDER BY r.completed_at DESC
    ''')


def toggle_quiz_status(quiz_id: int):
    """تغییر وضعیت فعال/غیرفعال آزمون"""
    return execute_query('''
        UPDATE quizzes 
        SET is_active = NOT is_active 
        WHERE id = %s
    ''', (quiz_id,))


# ==============================
# توابع اصلی ربات
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ربات"""
    user = update.effective_user
    user_id = user.id

    user_data = get_user(user_id)
    if not user_data:
        add_user(user_id, "", user.username, user.full_name)
        admin_message = (
            "کاربر جدید ثبت نام کرد:\n"
            f"آیدی: {user.id}\n"
            f"نام: {user.full_name}\n"
            f"یوزرنیم: @{user.username if user.username else 'ندارد'}"
        )
        try:
            await context.bot.send_message(ADMIN_ID, admin_message)
        except Exception as e:
            logger.error(f"Error sending message to admin: {e}")

    await show_main_menu(update, context)


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش شماره تلفن"""
    contact = update.message.contact
    user = update.effective_user

    if contact.user_id != user.id:
        await update.message.reply_text("لطفاً شماره تلفن خودتان را ارسال کنید.")
        return

    add_user(user.id, contact.phone_number, user.username, user.full_name)

    admin_message = (
        "کاربر جدید ثبت نام کرد:\n"
        f"آیدی: {user.id}\n"
        f"شماره: {contact.phone_number}\n"
        f"نام: {user.full_name}\n"
        f"یوزرنیم: @{user.username if user.username else 'ندارد'}"
    )

    try:
        await context.bot.send_message(ADMIN_ID, admin_message)
    except Exception as e:
        logger.error(f"Error sending message to admin: {e}")

    await update.message.reply_text(
        "ثبت نام شما با موفقیت انجام شد!",
        reply_markup=ReplyKeyboardRemove()
    )
    await show_main_menu(update, context)


# ==============================
# منوهای اصلی (ReplyKeyboardMarkup)
# ==============================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی"""
    keyboard = [
        ["شرکت در آزمون"],
        ["راهنما"]
    ]

    if update.effective_user.id == ADMIN_ID:
        keyboard.append(["پنل ادمین"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    text = "منوی اصلی:"

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def show_quiz_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست آزمون‌های فعال"""
    quizzes = get_active_quizzes()

    if not quizzes:
        keyboard = [["منوی اصلی"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "در حال حاضر هیچ آزمون فعالی وجود ندارد.",
            reply_markup=reply_markup
        )
        return

    keyboard = []
    text = "لیست آزمون‌های فعال:\n\n"

    for quiz in quizzes:
        quiz_id, title, description, time_limit = quiz
        button_text = f"{time_limit} دقیقه - {title}"
        keyboard.append([button_text])
        text += f"• {title}\n{time_limit} دقیقه\n{description}\n\n"

    keyboard.append(["منوی اصلی"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(text, reply_markup=reply_markup)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش راهنما"""
    help_text = (
        "راهنمای ربات آزمون:\n\n"
        "1. شرکت در آزمون: از بین آزمون‌های فعال یکی را انتخاب کنید\n"
        "2. زمان‌بندی: هر آزمون زمان محدودی دارد\n"
        "3. انتخاب پاسخ: روی گزینه‌ها کلیک کنید\n"
        "4. علامت‌گذاری: سوالات مشکوک را علامت بگذارید\n"
        "5. مرور: در پایان سوالات علامت‌گذاری شده را مرور کنید\n"
        "6. نتایج: برای مدیران ارسال می‌شود\n\n"
        "موفق باشید!"
    )

    keyboard = [["منوی اصلی"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(help_text, reply_markup=reply_markup)


# ==============================
# پنل ادمین (ReplyKeyboardMarkup)
# ==============================

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پنل ادمین"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("دسترسی denied!")
        return

    keyboard = [
        ["ایجاد آزمون جدید"],
        ["مدیریت آزمون‌ها"],
        ["مشاهده کاربران"],
        ["مشاهده نتایج"],
        ["منوی اصلی"]
    ]

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text("پنل مدیریت ادمین:", reply_markup=reply_markup)


async def admin_manage_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت آزمون‌ها"""
    if update.effective_user.id != ADMIN_ID:
        return

    quizzes = execute_query("SELECT id, title, is_active FROM quizzes ORDER BY created_at DESC")

    if not quizzes:
        keyboard = [["پنل ادمین"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("هیچ آزمونی یافت نشد.", reply_markup=reply_markup)
        return

    text = "مدیریت آزمون‌ها:\n\n"
    keyboard = []

    for quiz_id, title, is_active in quizzes:
        status = "فعال" if is_active else "غیرفعال"
        action_text = "غیرفعال" if is_active else "فعال"
        keyboard.append([f"{action_text} کردن '{title}'"])
        text += f"{title} - {status}\n"

    keyboard.append(["پنل ادمین"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(text, reply_markup=reply_markup)


async def admin_view_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده کاربران"""
    if update.effective_user.id != ADMIN_ID:
        return

    users = get_all_users()

    if not users:
        keyboard = [["پنل ادمین"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("هیچ کاربری یافت نشد.", reply_markup=reply_markup)
        return

    text = "لیست کاربران:\n\n"
    for user in users[:20]:
        user_id, full_name, username, phone_number, registered_at = user
        text += f"{full_name}\n"
        text += f"{phone_number}\n"
        text += f"@{username if username else 'ندارد'}\n"
        text += f"{user_id}\n"
        text += f"{registered_at.strftime('%Y-%m-%d %H:%M')}\n"
        text += "─" * 20 + "\n"

    if len(users) > 20:
        text += f"\nو {len(users) - 20} کاربر دیگر..."

    keyboard = [["پنل ادمین"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(text, reply_markup=reply_markup)


async def admin_view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده نتایج"""
    if update.effective_user.id != ADMIN_ID:
        return

    results = get_all_results()

    if not results:
        keyboard = [["پنل ادمین"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("هیچ نتیجه‌ای یافت نشد.", reply_markup=reply_markup)
        return

    text = "نتایج آزمون‌ها:\n\n"
    for result in results[:15]:
        full_name, title, score, total_time, completed_at = result
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        text += f"{full_name}\n"
        text += f"{title}\n"
        text += f"امتیاز: {score}\n"
        text += f"زمان: {time_str}\n"
        text += f"{completed_at.strftime('%Y-%m-%d %H:%M')}\n"
        text += "─" * 20 + "\n"

    if len(results) > 15:
        text += f"\nو {len(results) - 15} نتیجه دیگر..."

    keyboard = [["پنل ادمین"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(text, reply_markup=reply_markup)


# ==============================
# فرآیند آزمون (InlineKeyboardMarkup)
# ==============================

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """شروع آزمون"""
    user_id = update.effective_user.id
    quiz_info = get_quiz_info(quiz_id)

    if not quiz_info:
        await update.message.reply_text("آزمون یافت نشد!")
        return

    title, description, time_limit, is_active = quiz_info

    if not is_active:
        await update.message.reply_text("این آزمون غیرفعال است.")
        return

    questions = get_quiz_questions(quiz_id)
    if not questions:
        await update.message.reply_text("هیچ سوالی برای این آزمون تعریف نشده!")
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
        name=f"quiz_timeout_{user_id}_{quiz_id}"
    )

    await show_question(update, context)


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش سوال جاری (Inline)"""
    quiz_data = context.user_data['current_quiz']
    current_index = quiz_data['current_index']
    questions = quiz_data['questions']

    if current_index >= len(questions):
        return

    question = questions[current_index]
    question_id, question_image, correct_answer = question

    user_answers = get_user_answers(update.effective_user.id, quiz_data['quiz_id'])
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    selected = user_answers_dict.get(question_id)

    keyboard = []
    for i in range(1, 5):
        check = "پاسخ صحیح" if selected == i else ""
        keyboard.append([InlineKeyboardButton(
            f"{check}گزینه {i}",
            callback_data=f"ans_{quiz_data['quiz_id']}_{current_index}_{i}"
        )])

    marked = context.user_data.get('marked_questions', set())
    mark_text = "علامت‌گذاری شده" if current_index in marked else "علامت‌گذاری"
    keyboard.append([InlineKeyboardButton(
        mark_text,
        callback_data=f"mark_{quiz_data['quiz_id']}_{current_index}"
    )])

    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("قبلی", callback_data=f"nav_{current_index-1}"))
    if current_index < len(questions) - 1:
        nav_buttons.append(InlineKeyboardButton("بعدی", callback_data=f"nav_{current_index+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    if current_index == len(questions) - 1:
        marked_count = len(marked)
        if marked_count > 0:
            keyboard.append([InlineKeyboardButton(
                f"مرور علامت‌گذاری شده ({marked_count})",
                callback_data="review_marked"
            )])
        keyboard.append([InlineKeyboardButton(
            "ثبت نهایی",
            callback_data=f"submit_{quiz_data['quiz_id']}"
        )])

    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"سوال {current_index + 1} از {len(questions)}\n{quiz_data.get('title', '')}"

    try:
        if os.path.exists(question_image):
            with open(question_image, 'rb') as photo:
                if update.callback_query and update.callback_query.message.photo:
                    await update.callback_query.edit_message_media(
                        media=InputMediaPhoto(photo, caption=caption),
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_photo(photo, caption=caption, reply_markup=reply_markup)
        else:
            await update.callback_query.edit_message_text(
                f"{caption}\n\nتصویر سوال یافت نشد!",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error showing question: {e}")
        await update.callback_query.edit_message_text("خطا در نمایش سوال!", reply_markup=reply_markup)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int, question_index: int, answer: int):
    """پردازش پاسخ"""
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')

    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        return

    question = quiz_data['questions'][question_index]
    question_id = question[0]

    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    current_answer = user_answers_dict.get(question_id)

    if current_answer == answer:
        execute_query("DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s AND question_id = %s",
                      (user_id, quiz_id, question_id))
        await update.callback_query.answer("تیک برداشته شد")
    else:
        save_user_answer(user_id, quiz_id, question_id, answer)
        await update.callback_query.answer("پاسخ ثبت شد")

    await show_question(update, context)


async def toggle_mark(update: Update, context: ContextTypes.DEFAULT_TYPE, question_index: int):
    """علامت‌گذاری سوال"""
    marked = context.user_data.get('marked_questions', set())
    if question_index in marked:
        marked.remove(question_index)
        await update.callback_query.answer("علامت برداشته شد")
    else:
        marked.add(question_index)
        await update.callback_query.answer("علامت‌گذاری شد")
    context.user_data['marked_questions'] = marked
    await show_question(update, context)


async def navigate_to_question(update: Update, context: ContextTypes.DEFAULT_TYPE, new_index: int):
    """پرش به سوال"""
    quiz_data = context.user_data.get('current_quiz')
    if quiz_data and 0 <= new_index < len(quiz_data['questions']):
        quiz_data['current_index'] = new_index
        await show_question(update, context)


async def submit_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """ثبت نهایی"""
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')
    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        return

    total_time = (datetime.now() - quiz_data['start_time']).seconds
    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}

    score = 0
    correct_answers = wrong_answers = unanswered_questions = 0
    total_questions = len(quiz_data['questions'])

    for i, question in enumerate( | quiz_data['questions']):
        question_id, _, correct_answer = question
        user_answer = user_answers_dict.get(question_id)
        if user_answer is None:
            unanswered_questions += 1
        elif user_answer == correct_answer:
            correct_answers += 1
        else:
            wrong_answers += 1

    raw_score = correct_answers
    penalty = wrong_answers / 3.0
    final_score = max(0, raw_score - penalty)
    final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0

    save_result(user_id, quiz_id, final_percentage, total_time, correct_answers, wrong_answers, unanswered_questions)

    user_message = (
        f"آزمون ثبت شد!\n\n"
        f"صحیح: {correct_answers}\n"
        f"غلط: {wrong_answers}\n"
        f"بی‌پاسخ: {unanswered_questions}\n"
        f"درصد: {final_percentage:.2f}%\n"
        f"زمان: {total_time // 60}:{total_time % 60:02d}"
    )

    keyboard = [[InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]]
    await update.callback_query.edit_message_text(user_message, reply_markup=InlineKeyboardMarkup(keyboard))

    # پاکسازی
    for key in ['current_quiz', 'marked_questions', 'review_mode']:
        context.user_data.pop(key, None)


async def quiz_timeout(context: ContextTypes.DEFAULT_TYPE):
    """اتمام زمان"""
    job = context.job
    user_id = job.user_id
    data = job.data
    quiz_id = data['quiz_id']
    chat_id = data['chat_id']

    questions = get_quiz_questions(quiz_id)
    if not questions:
        return

    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}

    correct_answers = wrong_answers = unanswered_questions = 0
    total_questions = len(questions)

    for i, question in enumerate(questions):
        question_id, _, correct_answer = question
        user_answer = user_answers_dict.get(question_id)
        if user_answer is None:
            unanswered_questions += 1
        elif user_answer == correct_answer:
            correct_answers += 1
        else:
            wrong_answers += 1

    raw_score = correct_answers
    penalty = wrong_answers / 3.0
    final_score = max(0, raw_score - penalty)
    final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0

    save_result(user_id, quiz_id, final_percentage, data['time_limit'] * 60, correct_answers, wrong_answers, unanswered_questions)

    user_message = (
        f"زمان به پایان رسید!\n\n"
        f"صحیح: {correct_answers}\n"
        f"غلط: {wrong_answers}\n"
        f"بی‌پاسخ: {unanswered_questions}\n"
        f"درصد: {final_percentage:.2f}%"
    )

    await context.bot.send_message(
        chat_id,
        user_message,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]])
    )


# ==============================
# مدیریت پیام‌های متنی
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی"""
    text = update.message.text

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
    elif text.startswith(("فعال کردن", "غیرفعال کردن")):
        title = text.split("'", 1)[1].rsplit("'", 1)[0]
        quizzes = execute_query("SELECT id FROM quizzes WHERE title = %s", (title,))
        if quizzes:
            toggle_quiz_status(quizzes[0][0])
            await update.message.reply_text(f"وضعیت آزمون '{title}' تغییر کرد.")
            await admin_manage_quizzes(update, context)
    elif any(text.endswith(f" دقیقه - {q[1]}") for q in get_active_quizzes()):
        title = text.split(" - ", 1)[1]
        quizzes = execute_query("SELECT id FROM quizzes WHERE title = %s AND is_active = TRUE", (title,))
        if quizzes:
            await start_quiz(update, context, quizzes[0][0])
    else:
        await handle_admin_text(update, context)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت callback (فقط داخل آزمون)"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("ans_"):
        parts = data.split("_")
        await handle_answer(update, context, int(parts[1]), int(parts[2]), int(parts[3]))
    elif data.startswith("mark_"):
        await toggle_mark(update, context, int(data.split("_")[2]))
    elif data.startswith("nav_"):
        await navigate_to_question(update, context, int(data.split("_")[1]))
    elif data == "submit_":
        await submit_quiz(update, context, int(data.split("_")[1]))
    elif data == "main_menu":
        await show_main_menu(update, context)


# ==============================
# اجرای ربات
# ==============================

def main():
    init_database()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.PHOTO, handle_admin_photos))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("ربات در حال اجرا است...")
    application.run_polling()


if __name__ == "__main__":
    main()
