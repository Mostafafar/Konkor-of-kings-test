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

# تنظیمات دیتابیس PostgreSQL
DB_CONFIG = {
    'dbname': 'quiz_bot_db',
    'user': 'postgres',
    'password': 'f13821382',
    'host': 'localhost',
    'port': '5432'
}

# تنظیمات ربات
BOT_TOKEN = "7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ"
ADMIN_ID = 6680287530
PHOTOS_DIR = "photos"

# ایجاد دایرکتوری عکس‌ها
os.makedirs(PHOTOS_DIR, exist_ok=True)

# تنظیم لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# متغیرهای سراسری
db_connection = None

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
                score INTEGER DEFAULT 0,
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
    return execute_query(
        "SELECT * FROM users WHERE user_id = %s", 
        (user_id,)
    )

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

def save_result(user_id: int, quiz_id: int, score: int, total_time: int):
    """ذخیره نتیجه آزمون"""
    return execute_query('''
        INSERT INTO results (user_id, quiz_id, score, total_time) 
        VALUES (%s, %s, %s, %s)
    ''', (user_id, quiz_id, score, total_time))

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
    result = execute_query(
        "SELECT COUNT(*) FROM questions WHERE quiz_id = %s",
        (quiz_id,)
    )
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

# توابع اصلی ربات
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ربات و دریافت شماره تلفن"""
    user = update.effective_user
    user_id = user.id
    
    user_data = get_user(user_id)
    
    if user_data:
        await show_main_menu(update, context)
    else:
        keyboard = [
            [KeyboardButton("📞 ارسال شماره تلفن", request_contact=True)]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard, 
            resize_keyboard=True, 
            one_time_keyboard=True
        )
        
        await update.message.reply_text(
            "👋 به ربات آزمون خوش آمدید!\n\n"
            "برای استفاده از ربات، لطفاً شماره تلفن خود را ارسال کنید:",
            reply_markup=reply_markup
        )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش شماره تلفن دریافتی"""
    contact = update.message.contact
    user = update.effective_user
    
    if contact.user_id != user.id:
        await update.message.reply_text("لطفاً شماره تلفن خودتان را ارسال کنید.")
        return
    
    add_user(
        user.id, 
        contact.phone_number, 
        user.username, 
        user.full_name
    )
    
    admin_message = (
        "👤 کاربر جدید ثبت نام کرد:\n"
        f"🆔 آیدی: {user.id}\n"
        f"📞 شماره: {contact.phone_number}\n"
        f"👤 نام: {user.full_name}\n"
        f"🔗 یوزرنیم: @{user.username if user.username else 'ندارد'}"
    )
    
    try:
        await context.bot.send_message(ADMIN_ID, admin_message)
    except Exception as e:
        logger.error(f"Error sending message to admin: {e}")
    
    await update.message.reply_text(
        "✅ ثبت نام شما با موفقیت انجام شد!",
        reply_markup=ReplyKeyboardRemove()
    )
    
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی"""
    keyboard = [
        [InlineKeyboardButton("📝 شرکت در آزمون", callback_data="take_quiz")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")]
    ]
    
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🔧 پنل ادمین", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🎯 منوی اصلی:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🎯 منوی اصلی:",
            reply_markup=reply_markup
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کلیک روی دکمه‌ها"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "take_quiz":
        await show_quiz_list(update, context)
    elif data == "help":
        await show_help(update, context)
    elif data == "admin_panel":
        await show_admin_panel(update, context)
    elif data.startswith("quiz_"):
        quiz_id = int(data.split("_")[1])
        await start_quiz(update, context, quiz_id)
    elif data.startswith("ans_"):
        parts = data.split("_")
        quiz_id = int(parts[1])
        question_index = int(parts[2])
        answer = int(parts[3])
        await handle_answer(update, context, quiz_id, question_index, answer)
    elif data.startswith("mark_"):
        parts = data.split("_")
        question_index = int(parts[2])
        await toggle_mark(update, context, question_index)
    elif data.startswith("nav_"):
        new_index = int(data.split("_")[1])
        await navigate_to_question(update, context, new_index)
    elif data == "review_marked":
        await review_marked_questions(update, context)
    elif data.startswith("submit_"):
        quiz_id = int(data.split("_")[1])
        await submit_quiz(update, context, quiz_id)
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "admin_create_quiz":
        await admin_create_quiz(update, context)
    elif data == "admin_manage_quizzes":
        await admin_manage_quizzes(update, context)
    elif data == "admin_view_users":
        await admin_view_users(update, context)
    elif data == "admin_view_results":
        await admin_view_results(update, context)
    elif data == "confirm_add_questions":
        await start_adding_questions(update, context)
    elif data == "add_another_question":
        await start_adding_questions(update, context)
    elif data.startswith("toggle_quiz_"):
        quiz_id = int(data.split("_")[2])
        await toggle_quiz_status_handler(update, context, quiz_id)

async def show_quiz_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست آزمون‌های فعال"""
    quizzes = get_active_quizzes()
    
    if not quizzes:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ در حال حاضر هیچ آزمون فعالی وجود ندارد.",
            reply_markup=reply_markup
        )
        return
    
    keyboard = []
    for quiz in quizzes:
        quiz_id, title, description, time_limit = quiz
        button_text = f"⏱ {time_limit} دقیقه - {title}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"quiz_{quiz_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "📋 لیست آزمون‌های فعال:\n\n"
    for quiz in quizzes:
        quiz_id, title, description, time_limit = quiz
        text += f"• {title}\n⏱ {time_limit} دقیقه\n📝 {description}\n\n"
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup
    )

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """شروع آزمون"""
    user_id = update.effective_user.id
    
    # دریافت اطلاعات آزمون
    quiz_info = get_quiz_info(quiz_id)
    
    if not quiz_info:
        await update.callback_query.edit_message_text("آزمون یافت نشد!")
        return
    
    title, description, time_limit, is_active = quiz_info
    
    if not is_active:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به لیست آزمون‌ها", callback_data="take_quiz")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "❌ این آزمون در حال حاضر غیرفعال است و نمی‌توانید در آن شرکت کنید.",
            reply_markup=reply_markup
        )
        return
    
    # دریافت سوالات آزمون
    questions = get_quiz_questions(quiz_id)
    
    if not questions:
        await update.callback_query.edit_message_text("هیچ سوالی برای این آزمون تعریف نشده!")
        return
    
    # پاک کردن پاسخ‌های قبلی
    clear_user_answers(user_id, quiz_id)
    
    # ذخیره اطلاعات آزمون در context
    context.user_data['current_quiz'] = {
        'quiz_id': quiz_id,
        'questions': questions,
        'current_index': 0,
        'start_time': datetime.now(),
        'time_limit': time_limit,
        'title': title
    }
    
    # شروع تایمر
    context.job_queue.run_once(
        quiz_timeout, 
        time_limit * 60, 
        user_id=user_id, 
        data={'quiz_id': quiz_id, 'chat_id': update.effective_chat.id}
    )
    
    await show_question(update, context)

async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش سوال جاری"""
    quiz_data = context.user_data['current_quiz']
    current_index = quiz_data['current_index']
    questions = quiz_data['questions']
    
    if current_index >= len(questions):
        await update.callback_query.answer("شما در انتهای سوالات هستید!")
        return
    
    question = questions[current_index]
    question_id, question_image, correct_answer = question
    
    # دریافت پاسخ ذخیره شده کاربر
    user_answers = get_user_answers(
        update.effective_user.id, 
        quiz_data['quiz_id']
    )
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    selected = user_answers_dict.get(question_id)
    
    # ایجاد کیبورد با تیک‌ها
    keyboard = []
    for i in range(1, 5):
        check = "✅ " if selected == i else ""
        keyboard.append([InlineKeyboardButton(
            f"{check}گزینه {i}", 
            callback_data=f"ans_{quiz_data['quiz_id']}_{current_index}_{i}"
        )])
    
    # دکمه علامت‌گذاری
    marked = context.user_data.get('marked_questions', set())
    mark_text = "✅ علامت گذاری شده" if current_index in marked else "🏷 علامت‌گذاری"
    keyboard.append([InlineKeyboardButton(
        mark_text, 
        callback_data=f"mark_{quiz_data['quiz_id']}_{current_index}"
    )])
    
    # دکمه‌های ناوبری
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"nav_{current_index-1}"))
    if current_index < len(questions) - 1:
        nav_buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"nav_{current_index+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # اگر سوال آخر است، دکمه ارسال مجدد و ثبت نهایی
    if current_index == len(questions) - 1:
        marked_count = len(marked)
        if marked_count > 0:
            keyboard.append([InlineKeyboardButton(
                f"🔄 مرور سوالات علامت‌گذاری شده ({marked_count})", 
                callback_data=f"review_marked"
            )])
        keyboard.append([InlineKeyboardButton(
            "✅ ثبت نهایی پاسخ‌ها", 
            callback_data=f"submit_{quiz_data['quiz_id']}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    caption = f"📝 سوال {current_index + 1} از {len(questions)}\n📚 {quiz_data.get('title', '')}"
    
    try:
        # بررسی وجود فایل عکس
        if os.path.exists(question_image):
            with open(question_image, 'rb') as photo:
                # اگر پیام فعلی دارای عکس است، آن را ویرایش کن
                if update.callback_query.message.photo:
                    await update.callback_query.edit_message_media(
                        media=InputMediaPhoto(photo, caption=caption),
                        reply_markup=reply_markup
                    )
                else:
                    # اگر پیام فعلی عکس ندارد، پیام جدید بفرست
                    await update.callback_query.message.reply_photo(
                        photo=photo,
                        caption=caption,
                        reply_markup=reply_markup
                    )
        else:
            # اگر عکس وجود ندارد، فقط متن نمایش داده شود
            error_msg = f"{caption}\n\n⚠️ تصویر سوال یافت نشد!\nمسیر: {question_image}"
            await update.callback_query.edit_message_text(
                error_msg,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error showing question: {e}")
        try:
            await update.callback_query.edit_message_text(
                f"{caption}\n\n⚠️ خطا در نمایش سوال!",
                reply_markup=reply_markup
            )
        except:
            await update.callback_query.message.reply_text(
                f"{caption}\n\n⚠️ خطا در نمایش سوال!",
                reply_markup=reply_markup
            )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                      quiz_id: int, question_index: int, answer: int):
    """پردازش انتخاب/لغو انتخاب پاسخ"""
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')
    
    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        await update.callback_query.answer("خطا! لطفاً آزمون را دوباره شروع کنید.")
        return
    
    question = quiz_data['questions'][question_index]
    question_id = question[0]
    
    # دریافت پاسخ فعلی کاربر
    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    current_answer = user_answers_dict.get(question_id)
    
    # اگر همان پاسخ را دوباره انتخاب کرد، آن را حذف کن (برداشتن تیک)
    if current_answer == answer:
        execute_query(
            "DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s AND question_id = %s",
            (user_id, quiz_id, question_id)
        )
        await update.callback_query.answer("✅ تیک برداشته شد")
    else:
        # ذخیره پاسخ جدید
        save_user_answer(user_id, quiz_id, question_id, answer)
        await update.callback_query.answer("✅ پاسخ ثبت شد")
    
    # بروزرسانی نمایش سوال
    await show_question(update, context)

async def toggle_mark(update: Update, context: ContextTypes.DEFAULT_TYPE, question_index: int):
    """تغییر وضعیت علامت‌گذاری سوال"""
    marked = context.user_data.get('marked_questions', set())
    
    if question_index in marked:
        marked.remove(question_index)
        await update.callback_query.answer("🏷 علامت برداشته شد")
    else:
        marked.add(question_index)
        await update.callback_query.answer("✅ علامت‌گذاری شد")
    
    context.user_data['marked_questions'] = marked
    
    # بروزرسانی نمایش سوال
    await show_question(update, context)

async def navigate_to_question(update: Update, context: ContextTypes.DEFAULT_TYPE, new_index: int):
    """پرش به سوال مشخص شده"""
    quiz_data = context.user_data.get('current_quiz')
    
    if not quiz_data:
        await update.callback_query.answer("خطا! لطفاً آزمون را دوباره شروع کنید.")
        return
    
    if 0 <= new_index < len(quiz_data['questions']):
        quiz_data['current_index'] = new_index
        await show_question(update, context)
    else:
        await update.callback_query.answer("سوال مورد نظر یافت نشد!")

async def review_marked_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرور سوالات علامت‌گذاری شده"""
    quiz_data = context.user_data.get('current_quiz')
    marked = context.user_data.get('marked_questions', set())
    
    if not quiz_data or not marked:
        await update.callback_query.answer("هیچ سوالی علامت‌گذاری نشده است!")
        return
    
    # ایجاد لیست سوالات علامت‌گذاری شده
    marked_list = sorted(list(marked))
    
    if 'review_mode' not in context.user_data:
        context.user_data['review_mode'] = True
        context.user_data['marked_list'] = marked_list
        context.user_data['review_index'] = 0
    
    # نمایش اولین سوال علامت‌گذاری شده
    quiz_data['current_index'] = marked_list[0]
    await show_question(update, context)

async def submit_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """ثبت نهایی پاسخ‌ها و محاسبه نتایج"""
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')
    
    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        await update.callback_query.answer("خطا! لطفاً آزمون را دوباره شروع کنید.")
        return
    
    # محاسبه زمان صرف شده
    total_time = (datetime.now() - quiz_data['start_time']).seconds
    
    # محاسبه امتیاز
    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    
    score = 0
    total_questions = len(quiz_data['questions'])
    correct_answers = 0
    
    result_details = "📊 جزئیات پاسخ‌ها:\n\n"
    
    for i, question in enumerate(quiz_data['questions']):
        question_id, question_image, correct_answer = question
        user_answer = user_answers_dict.get(question_id)
        
        is_correct = user_answer == correct_answer
        
        if is_correct:
            score += 1
            correct_answers += 1
            result_details += f"✅ سوال {i+1}: صحیح\n"
        else:
            user_answer_text = user_answer if user_answer else "پاسخی داده نشد"
            result_details += f"❌ سوال {i+1}: غلط (پاسخ شما: {user_answer_text}, پاسخ صحیح: {correct_answer})\n"
    
    # ذخیره نتیجه
    save_result(user_id, quiz_id, score, total_time)
    
    # دریافت اطلاعات کاربر و آزمون
    user_info = get_user(user_id)
    quiz_info = get_quiz_info(quiz_id)
    
    user_data = user_info[0] if user_info else (user_id, "نامشخص", "نامشخص", "نامشخص")
    quiz_title = quiz_info[0] if quiz_info else "نامشخص"
    
    # ارسال نتایج کامل به ادمین
    admin_result_text = (
        "🎯 نتایج آزمون جدید:\n\n"
        f"👤 کاربر: {user_data[3]} (@{user_data[2] if user_data[2] else 'ندارد'})\n"
        f"📞 شماره: {user_data[1]}\n"
        f"🆔 آیدی: {user_id}\n\n"
        f"📚 آزمون: {quiz_title}\n"
        f"✅ امتیاز: {score} از {total_questions}\n"
        f"📈 صحیح: {correct_answers} از {total_questions}\n"
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n\n"
        f"{result_details}"
    )
    
    try:
        await context.bot.send_message(ADMIN_ID, admin_result_text)
    except Exception as e:
        logger.error(f"Error sending results to admin: {e}")
    
    # پیام به کاربر
    user_message = (
        f"✅ آزمون شما با موفقیت ثبت شد!\n\n"
        f"📊 نتیجه: {score} از {total_questions}\n"
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n\n"
        f"نتایج برای مدیران ارسال گردید."
    )
    
    keyboard = [[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.callback_query.edit_message_text(
            user_message,
            reply_markup=reply_markup
        )
    except:
        await update.callback_query.message.reply_text(
            user_message,
            reply_markup=reply_markup
        )
    
    # پاک کردن داده‌های موقت
    if 'current_quiz' in context.user_data:
        del context.user_data['current_quiz']
    if 'marked_questions' in context.user_data:
        del context.user_data['marked_questions']
    if 'review_mode' in context.user_data:
        del context.user_data['review_mode']

async def quiz_timeout(context: ContextTypes.DEFAULT_TYPE):
    """اتمام زمان آزمون"""
    job = context.job
    user_id = job.user_id
    quiz_id = job.data['quiz_id']
    chat_id = job.data['chat_id']
    
    try:
        # محاسبه نتایج
        user_answers = get_user_answers(user_id, quiz_id)
        score = len(user_answers)  # در این حالت فقط تعداد پاسخ‌های داده شده
        
        # ذخیره نتیجه
        save_result(user_id, quiz_id, score, job.data.get('time_limit', 60) * 60)
        
        await context.bot.send_message(
            chat_id,
            "⏰ زمان آزمون به پایان رسید! پاسخ‌های شما ثبت شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])
        )
    except Exception as e:
        logger.error(f"Error in quiz timeout: {e}")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش راهنما"""
    help_text = (
        "📖 راهنمای ربات آزمون:\n\n"
        "1. 📝 شرکت در آزمون: از بین آزمون‌های فعال یکی را انتخاب کنید\n"
        "2. ⏱ زمان‌بندی: هر آزمون زمان محدودی دارد\n"
        "3. ✅ انتخاب پاسخ: روی گزینه‌ها کلیک کنید (می‌توانید تغییر دهید)\n"
        "4. 🏷 علامت‌گذاری: سوالات مشکوک را علامت بگذارید\n"
        "5. 🔄 مرور: در پایان می‌توانید سوالات علامت‌گذاری شده را مرور کنید\n"
        "6. 📊 نتایج: نتایج برای مدیران ارسال می‌شود\n\n"
        "موفق باشید! 🎯"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        help_text,
        reply_markup=reply_markup
    )

# بخش مدیریت ادمین
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پنل ادمین"""
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.edit_message_text("دسترسی denied!")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ ایجاد آزمون جدید", callback_data="admin_create_quiz")],
        [InlineKeyboardButton("📋 مدیریت آزمون‌ها", callback_data="admin_manage_quizzes")],
        [InlineKeyboardButton("👥 مشاهده کاربران", callback_data="admin_view_users")],
        [InlineKeyboardButton("📊 مشاهده نتایج", callback_data="admin_view_results")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🔧 پنل مدیریت ادمین:",
        reply_markup=reply_markup
    )

async def admin_create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ایجاد آزمون جدید"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'creating_quiz'
    context.user_data['quiz_data'] = {
        'questions': [],
        'current_step': 'title'
    }
    
    await update.callback_query.edit_message_text(
        "📝 ایجاد آزمون جدید:\n\nلطفاً عنوان آزمون را ارسال کنید:"
    )

async def admin_manage_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت آزمون‌ها"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    quizzes = execute_query("SELECT id, title, is_active FROM quizzes ORDER BY created_at DESC")
    
    if not quizzes:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ آزمونی یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    text = "📋 مدیریت آزمون‌ها:\n\n"
    keyboard = []
    
    for quiz_id, title, is_active in quizzes:
        status = "✅ فعال" if is_active else "❌ غیرفعال"
        status_icon = "❌" if is_active else "✅"
        action_text = "غیرفعال" if is_active else "فعال"
        
        text += f"📌 {title} - {status}\n"
        keyboard.append([InlineKeyboardButton(
            f"{status_icon} {action_text} کردن '{title}'", 
            callback_data=f"toggle_quiz_{quiz_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup
    )

async def toggle_quiz_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """تغییر وضعیت فعال/غیرفعال آزمون"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    toggle_quiz_status(quiz_id)
    await update.callback_query.answer("✅ وضعیت آزمون تغییر کرد")
    await admin_manage_quizzes(update, context)

async def admin_view_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده کاربران"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    users = get_all_users()
    
    if not users:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ کاربری یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    text = "👥 لیست کاربران:\n\n"
    for user in users[:20]:  # فقط 20 کاربر اول
        user_id, full_name, username, phone_number, registered_at = user
        text += f"👤 {full_name}\n"
        text += f"📞 {phone_number}\n"
        text += f"🔗 @{username if username else 'ندارد'}\n"
        text += f"🆔 {user_id}\n"
        text += f"📅 {registered_at.strftime('%Y-%m-%d %H:%M')}\n"
        text += "─" * 20 + "\n"
    
    if len(users) > 20:
        text += f"\n📊 و {len(users) - 20} کاربر دیگر..."
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup
    )

async def admin_view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده نتایج"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    results = get_all_results()
    
    if not results:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ نتیجه‌ای یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    text = "📊 نتایج آزمون‌ها:\n\n"
    for result in results[:15]:  # فقط 15 نتیجه اول
        full_name, title, score, total_time, completed_at = result
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        text += f"👤 {full_name}\n"
        text += f"📚 {title}\n"
        text += f"✅ امتیاز: {score}\n"
        text += f"⏱ زمان: {time_str}\n"
        text += f"📅 {completed_at.strftime('%Y-%m-%d %H:%M')}\n"
        text += "─" * 20 + "\n"
    
    if len(results) > 15:
        text += f"\n📊 و {len(results) - 15} نتیجه دیگر..."
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup
    )

async def handle_admin_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش عکس‌های ارسالی ادمین برای سوالات"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    if 'admin_action' not in context.user_data or context.user_data['admin_action'] != 'adding_questions':
        await update.message.reply_text("❌ ابتدا فرآیند ایجاد آزمون را شروع کنید.")
        return
    
    quiz_data = context.user_data.get('quiz_data', {})
    
    if quiz_data.get('current_step') != 'question_image':
        await update.message.reply_text("❌ در این مرحله نمی‌توانید عکس ارسال کنید.")
        return
    
    # دریافت عکس
    photo_file = await update.message.photo[-1].get_file()
    image_filename = f"question_{quiz_data['quiz_id']}_{len(quiz_data['questions']) + 1}.jpg"
    image_path = os.path.join(PHOTOS_DIR, image_filename)
    
    await photo_file.download_to_drive(image_path)
    
    # ذخیره مسیر عکس
    quiz_data['current_question_image'] = image_path
    quiz_data['current_step'] = 'correct_answer'
    
    context.user_data['quiz_data'] = quiz_data
    
    await update.message.reply_text(
        "✅ عکس سوال ذخیره شد.\n\n"
        "لطفاً شماره گزینه صحیح را ارسال کنید (1 تا 4):"
    )

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش متن‌های ارسالی ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    text = update.message.text
    
    if 'admin_action' not in context.user_data:
        return
    
    action = context.user_data['admin_action']
    quiz_data = context.user_data.get('quiz_data', {})
    
    if action == 'creating_quiz':
        current_step = quiz_data.get('current_step')
        
        if current_step == 'title':
            quiz_data['title'] = text
            quiz_data['current_step'] = 'description'
            context.user_data['quiz_data'] = quiz_data
            
            await update.message.reply_text(
                "✅ عنوان آزمون ذخیره شد.\n\n"
                "لطفاً توضیحات آزمون را ارسال کنید:"
            )
        
        elif current_step == 'description':
            quiz_data['description'] = text
            quiz_data['current_step'] = 'time_limit'
            context.user_data['quiz_data'] = quiz_data
            
            await update.message.reply_text(
                "✅ توضیحات آزمون ذخیره شد.\n\n"
                "لطفاً زمان آزمون را به دقیقه ارسال کنید:"
            )
        
        elif current_step == 'time_limit':
            try:
                time_limit = int(text)
                if time_limit <= 0:
                    raise ValueError
                
                # ایجاد آزمون در دیتابیس
                quiz_id = create_quiz(
                    quiz_data['title'],
                    quiz_data['description'],
                    time_limit
                )
                
                if quiz_id:
                    quiz_data['quiz_id'] = quiz_id
                    quiz_data['current_step'] = 'add_questions'
                    context.user_data['quiz_data'] = quiz_data
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ بله، افزودن سوالات", callback_data="confirm_add_questions")],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        f"✅ آزمون با مشخصات زیر ایجاد شد:\n\n"
                        f"📌 عنوان: {quiz_data['title']}\n"
                        f"📝 توضیحات: {quiz_data['description']}\n"
                        f"⏱ زمان: {time_limit} دقیقه\n\n"
                        f"آیا می‌خواهید اکنون سوالات را اضافه کنید؟",
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_text("❌ خطا در ایجاد آزمون!")
                    
            except ValueError:
                await update.message.reply_text("❌ لطفاً یک عدد صحیح مثبت وارد کنید:")
    
    elif action == 'adding_questions':
        current_step = quiz_data.get('current_step')
        
        if current_step == 'correct_answer':
            try:
                correct_answer = int(text)
                if correct_answer < 1 or correct_answer > 4:
                    raise ValueError
                
                # ذخیره سوال در دیتابیس
                add_question(
                    quiz_data['quiz_id'],
                    quiz_data['current_question_image'],
                    correct_answer,
                    len(quiz_data['questions']) + 1
                )
                
                # افزودن به لیست سوالات
                quiz_data['questions'].append({
                    'image': quiz_data['current_question_image'],
                    'correct_answer': correct_answer
                })
                
                keyboard = [
                    [InlineKeyboardButton("➕ افزودن سوال دیگر", callback_data="add_another_question")],
                    [InlineKeyboardButton("🏁 اتمام افزودن سوالات", callback_data="admin_panel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"✅ سوال {len(quiz_data['questions'])} با موفقیت اضافه شد!\n\n"
                    f"📸 عکس: {os.path.basename(quiz_data['current_question_image'])}\n"
                    f"✅ پاسخ صحیح: گزینه {correct_answer}\n\n"
                    f"چه کاری می‌خواهید انجام دهید؟",
                    reply_markup=reply_markup
                )
                
                # پاک کردن داده‌های موقت
                if 'current_question_image' in quiz_data:
                    del quiz_data['current_question_image']
                
                quiz_data['current_step'] = 'waiting_decision'
                context.user_data['quiz_data'] = quiz_data
                
            except ValueError:
                await update.message.reply_text("❌ لطفاً عددی بین 1 تا 4 وارد کنید:")

async def start_adding_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند افزودن سوالات"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    quiz_data = context.user_data.get('quiz_data', {})
    
    if 'quiz_id' not in quiz_data:
        await update.callback_query.edit_message_text("❌ خطا! ابتدا آزمون را ایجاد کنید.")
        return
    
    context.user_data['admin_action'] = 'adding_questions'
    quiz_data['current_step'] = 'question_image'
    context.user_data['quiz_data'] = quiz_data
    
    await update.callback_query.edit_message_text(
        f"➕ افزودن سوال به آزمون '{quiz_data['title']}':\n\n"
        "لطفاً عکس سوال را ارسال کنید:"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی"""
    if update.message.contact:
        await handle_contact(update, context)
    elif update.message.text:
        await handle_admin_text(update, context)

def main():
    """تابع اصلی اجرای ربات"""
    # اتصال به دیتابیس
    init_database()
    
    # ساخت اپلیکیشن
    application = Application.builder().token(BOT_TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.PHOTO, handle_admin_photos))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # اجرای ربات
    print("🤖 ربات در حال اجرا است...")
    application.run_polling()

if __name__ == "__main__":
    main()
