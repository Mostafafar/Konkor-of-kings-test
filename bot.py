import os
import logging
import psycopg2
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
    KeyboardButton,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputTextMessageContent
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes, 
    filters,
    InlineQueryHandler,
    ChosenInlineResultHandler
)
from telegram.constants import ParseMode
import requests
import random
from math import ceil

# تنظیمات دیتابیس PostgreSQL
DB_CONFIG = {
    'dbname': 'quiz_bot_db',
    'user': 'postgres',
    'password': 'f13821382',
    'host': 'localhost',
    'port': '5432'
}

# تنظیمات ربات
BOT_TOKEN = "7502637474:AAGQmU_4c4p5TS6PJrP_e5dOPvu2v8K95L0"
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
                created_by_admin BOOLEAN DEFAULT FALSE,
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
                user_rank INTEGER DEFAULT 0,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول مباحث
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topics (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول بانک سوالات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS question_bank (
                id SERIAL PRIMARY KEY,
                topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
                question_image TEXT NOT NULL,
                correct_answer INTEGER NOT NULL,
                difficulty_level TEXT DEFAULT 'medium',
                auto_difficulty_score REAL DEFAULT 0.5,
                total_attempts INTEGER DEFAULT 0,
                correct_attempts INTEGER DEFAULT 0,
                average_time REAL DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول قالب‌های آزمون
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_templates (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                topics INTEGER[] DEFAULT '{}',
                question_count INTEGER DEFAULT 20,
                time_limit INTEGER DEFAULT 30,
                difficulty_level TEXT DEFAULT 'all',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# توابع کاربران
def get_user(user_id: int):
    return execute_query("SELECT * FROM users WHERE user_id = %s", (user_id,))

def add_user(user_id: int, phone_number: str, username: str, full_name: str):
    return execute_query('''
        INSERT INTO users (user_id, phone_number, username, full_name) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET 
        phone_number = EXCLUDED.phone_number,
        username = EXCLUDED.username,
        full_name = EXCLUDED.full_name
    ''', (user_id, phone_number, username, full_name))

def get_active_quizzes():
    return execute_query(
        "SELECT id, title, description, time_limit, created_by_admin FROM quizzes WHERE is_active = TRUE ORDER BY id"
    )

# توابع مباحث
def get_all_topics():
    return execute_query("SELECT id, name, description FROM topics WHERE is_active = TRUE ORDER BY name")

def get_topic_by_name(name: str):
    return execute_query("SELECT id, name, description FROM topics WHERE name = %s AND is_active = TRUE", (name,))

def add_topic(name: str, description: str = ""):
    return execute_query(
        "INSERT INTO topics (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING RETURNING id",
        (name, description), return_id=True
    )

# توابع بانک سوالات
def add_question_to_bank(topic_id: int, question_image: str, correct_answer: int):
    return execute_query('''
        INSERT INTO question_bank (topic_id, question_image, correct_answer)
        VALUES (%s, %s, %s) RETURNING id
    ''', (topic_id, question_image, correct_answer), return_id=True)

def get_questions_by_topics(topic_ids: List[int], difficulty: str = 'all', limit: int = 20):
    if not topic_ids:
        return []
    
    if difficulty == 'all':
        query = """
            SELECT id, question_image, correct_answer, auto_difficulty_score 
            FROM question_bank 
            WHERE topic_id = ANY(%s) AND is_active = TRUE
            ORDER BY RANDOM() 
            LIMIT %s
        """
        return execute_query(query, (topic_ids, limit))
    else:
        query = """
            SELECT id, question_image, correct_answer, auto_difficulty_score 
            FROM question_bank 
            WHERE topic_id = ANY(%s) AND is_active = TRUE
            ORDER BY auto_difficulty_score {}
            LIMIT %s
        """.format("DESC" if difficulty == 'hard' else "ASC")
        return execute_query(query, (topic_ids, limit))

# توابع قالب‌های آزمون
def save_quiz_template(user_id: int, name: str, topics: List[int], question_count: int, time_limit: int, difficulty: str):
    return execute_query('''
        INSERT INTO quiz_templates (user_id, name, topics, question_count, time_limit, difficulty_level)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    ''', (user_id, name, topics, question_count, time_limit, difficulty), return_id=True)

def get_user_templates(user_id: int):
    return execute_query(
        "SELECT id, name, topics, question_count, time_limit, difficulty_level FROM quiz_templates WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )

# توابع نتایج و رتبه‌بندی
def save_result_with_rank(user_id: int, quiz_id: int, score: float, total_time: int, correct_answers: int, wrong_answers: int, unanswered_questions: int):
    # ابتدا نتیجه را ذخیره می‌کنیم
    result = execute_query('''
        INSERT INTO results (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions) 
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions), return_id=True)
    
    if result:
        # محاسبه رتبه‌ها برای این آزمون
        update_ranks_for_quiz(quiz_id)
    
    return result

def update_ranks_for_quiz(quiz_id: int):
    """به‌روزرسانی رتبه‌های یک آزمون"""
    execute_query('''
        WITH ranked_results AS (
            SELECT id,
                   ROW_NUMBER() OVER (ORDER BY score DESC, total_time ASC) as new_rank
            FROM results 
            WHERE quiz_id = %s
        )
        UPDATE results 
        SET user_rank = ranked_results.new_rank
        FROM ranked_results
        WHERE results.id = ranked_results.id
    ''', (quiz_id,))

def get_quiz_rankings(quiz_id: int):
    """دریافت رتبه‌بندی کامل یک آزمون"""
    return execute_query('''
        SELECT u.full_name, r.score, r.correct_answers, r.total_time, r.user_rank
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.quiz_id = %s
        ORDER BY r.user_rank
    ''', (quiz_id,))

def get_user_rank(user_id: int, quiz_id: int):
    """دریافت رتبه کاربر در یک آزمون"""
    return execute_query(
        "SELECT user_rank FROM results WHERE user_id = %s AND quiz_id = %s",
        (user_id, quiz_id)
    )

# تحلیل‌گر سطح سختی
class DifficultyAnalyzer:
    @staticmethod
    def update_question_difficulty(question_id: int, is_correct: bool, time_spent: float):
        """به‌روزرسانی سطح سختی سوال بر اساس پاسخ کاربر"""
        # دریافت داده‌های فعلی
        current_data = execute_query(
            "SELECT total_attempts, correct_attempts, average_time FROM question_bank WHERE id = %s",
            (question_id,)
        )
        
        if not current_data:
            return
        
        total_attempts, correct_attempts, avg_time = current_data[0]
        
        # به‌روزرسانی آمار
        new_total = total_attempts + 1
        new_correct = correct_attempts + (1 if is_correct else 0)
        
        # محاسبه زمان متوسط جدید
        if avg_time == 0:
            new_avg_time = time_spent
        else:
            new_avg_time = (avg_time * total_attempts + time_spent) / new_total
        
        # محاسبه نرخ موفقیت
        success_rate = new_correct / new_total if new_total > 0 else 0
        
        # محاسبه امتیاز سختی (0=آسان, 1=سخت)
        difficulty_score = DifficultyAnalyzer.calculate_difficulty_score(success_rate, new_avg_time)
        
        # ذخیره در دیتابیس
        execute_query('''
            UPDATE question_bank 
            SET total_attempts = %s, correct_attempts = %s, average_time = %s, auto_difficulty_score = %s
            WHERE id = %s
        ''', (new_total, new_correct, new_avg_time, difficulty_score, question_id))
    
    @staticmethod
    def calculate_difficulty_score(success_rate: float, avg_time: float) -> float:
        """محاسبه امتیاز سختی سوال"""
        # نرمال‌سازی زمان (فرض: زمان ایده‌آل 30 ثانیه)
        time_factor = min(avg_time / 60.0, 1.0)  # نرمال‌سازی به دقیقه
        
        # ترکیب نرخ موفقیت و زمان
        difficulty = (1 - success_rate) * 0.7 + time_factor * 0.3
        return max(0.0, min(1.0, difficulty))

# توابع اصلی ربات
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    user_data = get_user(user_id)
    if not user_data:
        add_user(user_id, "", user.username, user.full_name)
        
        admin_message = (
            "👤 کاربر جدید ثبت نام کرد:\n"
            f"🆔 آیدی: {user.id}\n"
            f"👤 نام: {user.full_name}\n"
            f"🔗 یوزرنیم: @{user.username if user.username else 'ندارد'}"
        )
        
        try:
            await context.bot.send_message(ADMIN_ID, admin_message)
        except Exception as e:
            logger.error(f"Error sending message to admin: {e}")
    
    has_start_param = context.args and len(context.args) > 0
    
    if has_start_param:
        welcome_message = (
            "🎯 قبل از آزمون اصلی، در محیطی رقابتی سطح خودت رو بسنج!\n\n"
            "تو میدان ماز خودتو محک بزن!\n"
            "مثل آزمون واقعی، همون زمان، همون شرایط 💪\n\n"
            "📊 ویژگیای باحال آزمون:\n"
            "• طراحی شبیه فضای آزمون\n"
            "• زمان‌بندی واقعی\n"
            "• مطابق برنامه قلمچی\n\n"
            "🔥 قبل از آزمون اصلی، تو محیط رقابتی بدرخش!\n"
            "• سطحت رو بسنج\n"
            "• با بقیه مقایسه شو\n"
            "• ضعف‌هات رو پیدا کن\n\n"
            "🤖 حالا میتونی شروع کنی:"
        )
        
        photo_path = os.path.join(PHOTOS_DIR, "welcome.jpg")
        if os.path.exists(photo_path):
            try:
                with open(photo_path, 'rb') as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=welcome_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as e:
                logger.error(f"Error sending welcome photo: {e}")
                await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("🤖 به ربات آزمون خوش آمدید!")

    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 شرکت در آزمون", callback_data="take_quiz")],
        [InlineKeyboardButton("🎯 ساخت آزمون سفارشی", callback_data="create_custom_quiz")],
        [InlineKeyboardButton("📊 نتایج من", callback_data="my_results")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")]
    ]
    
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🔧 پنل ادمین", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text("🎯 منوی اصلی:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("🎯 منوی اصلی:", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "take_quiz":
        await show_quiz_list(update, context)
    elif data == "create_custom_quiz":
        await start_custom_quiz_creation(update, context)
    elif data == "my_results":
        await show_my_results(update, context)
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
    elif data == "admin_manage_topics":
        await admin_manage_topics(update, context)
    elif data == "admin_add_question":
        await admin_add_question(update, context)
    elif data == "admin_quiz_rankings":
        await admin_quiz_rankings(update, context)

# ساخت آزمون سفارشی
async def start_custom_quiz_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['custom_quiz'] = {
        'step': 'select_topics',
        'selected_topics': [],
        'settings': {}
    }
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب مباحث", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 ساخت آزمون سفارشی\n\n"
        "مرحله ۱/۴: انتخاب مباحث\n\n"
        "روی دکمه زیر کلیک کنید و مباحث مورد نظرتان را جستجو و انتخاب کنید:",
        reply_markup=reply_markup
    )

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    results = []
    
    topics = get_all_topics()
    
    for topic in topics:
        topic_id, name, description = topic
        results.append(InlineQueryResultArticle(
            id=str(topic_id),
            title=name,
            description=description or "بدون توضیح",
            input_message_content=InputTextMessageContent(
                f"مبحث انتخاب شده: {name}"
            )
        ))
    
    await update.inline_query.answer(results)

async def chosen_inline_result_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result_id = update.chosen_inline_result.result_id
    user_id = update.chosen_inline_result.from_user.id
    
    if 'custom_quiz' not in context.user_data:
        return
    
    # افزودن مبحث به لیست انتخاب‌شده
    if int(result_id) not in context.user_data['custom_quiz']['selected_topics']:
        context.user_data['custom_quiz']['selected_topics'].append(int(result_id))
    
    # نمایش مباحث انتخاب شده
    selected_topics = context.user_data['custom_quiz']['selected_topics']
    topics_text = "\n".join([get_topic_by_name(str(topic_id))[0][1] for topic_id in selected_topics])
    
    keyboard = [
        [InlineKeyboardButton("✅ ادامه تنظیمات", callback_data="custom_quiz_settings")],
        [InlineKeyboardButton("🔍 افزودن مبحث دیگر", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📚 مباحث انتخاب شده:\n{topics_text}\n\nتعداد: {len(selected_topics)} مبحث",
        reply_markup=reply_markup
    )

async def custom_quiz_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['custom_quiz']['step'] = 'settings'
    
    keyboard = [
        [InlineKeyboardButton("📊 تعداد سوالات: ۲۰", callback_data="set_count_20")],
        [InlineKeyboardButton("⏱ زمان: ۳۰ دقیقه", callback_data="set_time_30")],
        [InlineKeyboardButton("🎯 سطح: همه سطوح", callback_data="set_difficulty_all")],
        [InlineKeyboardButton("🚀 شروع آزمون", callback_data="generate_custom_quiz")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 ساخت آزمون سفارشی\n\n"
        "مرحله ۲/۴: تنظیمات آزمون\n\n"
        "لطفاً تنظیمات مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def generate_custom_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    quiz_data = context.user_data['custom_quiz']
    
    # تولید آزمون از بانک سوالات
    questions = get_questions_by_topics(
        quiz_data['selected_topics'],
        quiz_data['settings'].get('difficulty', 'all'),
        quiz_data['settings'].get('count', 20)
    )
    
    if not questions:
        await update.callback_query.edit_message_text(
            "❌ هیچ سوالی برای مباحث انتخاب شده یافت نشد!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]])
        )
        return
    
    # ایجاد آزمون موقت
    quiz_title = f"آزمون سفارشی - {datetime.now().strftime('%Y%m%d_%H%M')}"
    quiz_id = create_quiz(quiz_title, "آزمون سفارشی کاربر", 30, False)
    
    if not quiz_id:
        await update.callback_query.edit_message_text(
            "❌ خطا در ایجاد آزمون!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )
        return
    
    # افزودن سوالات به آزمون
    for i, question in enumerate(questions):
        add_question(quiz_id, question[1], question[2], i)
    
    # شروع آزمون
    await start_quiz(update, context, quiz_id)

# توابع آزمون (مانند قبل)
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    user_id = update.effective_user.id
    
    quiz_info = get_quiz_info(quiz_id)
    if not quiz_info:
        await update.callback_query.edit_message_text("آزمون یافت نشد!")
        return
    
    title, description, time_limit, is_active, created_by_admin = quiz_info
    
    if not is_active:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به لیست آزمون‌ها", callback_data="take_quiz")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("❌ این آزمون غیرفعال است.", reply_markup=reply_markup)
        return
    
    questions = get_quiz_questions(quiz_id)
    if not questions:
        await update.callback_query.edit_message_text("هیچ سوالی برای این آزمون تعریف نشده!")
        return
    
    clear_user_answers(user_id, quiz_id)
    
    context.user_data['current_quiz'] = {
        'quiz_id': quiz_id,
        'questions': questions,
        'current_index': 0,
        'start_time': datetime.now(),
        'time_limit': time_limit,
        'title': title,
        'created_by_admin': created_by_admin
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
    quiz_data = context.user_data['current_quiz']
    current_index = quiz_data['current_index']
    questions = quiz_data['questions']
    
    if current_index >= len(questions):
        await update.callback_query.answer("شما در انتهای سوالات هستید!")
        return
    
    question = questions[current_index]
    question_id, question_image, correct_answer = question
    
    user_answers = get_user_answers(update.effective_user.id, quiz_data['quiz_id'])
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    selected = user_answers_dict.get(question_id)
    
    keyboard = []
    for i in range(1, 5):
        check = "✅ " if selected == i else ""
        keyboard.append([InlineKeyboardButton(f"{check}گزینه {i}", callback_data=f"ans_{quiz_data['quiz_id']}_{current_index}_{i}")])
    
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"nav_{current_index-1}"))
    if current_index < len(questions) - 1:
        nav_buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"nav_{current_index+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    if current_index == len(questions) - 1:
        keyboard.append([InlineKeyboardButton("✅ ثبت نهایی پاسخ‌ها", callback_data=f"submit_{quiz_data['quiz_id']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    caption = f"📝 سوال {current_index + 1} از {len(questions)}\n📚 {quiz_data.get('title', '')}"
    
    try:
        if os.path.exists(question_image):
            with open(question_image, 'rb') as photo:
                if update.callback_query.message.photo:
                    await update.callback_query.edit_message_media(
                        media=InputMediaPhoto(photo, caption=caption),
                        reply_markup=reply_markup
                    )
                else:
                    await update.callback_query.message.reply_photo(
                        photo=photo,
                        caption=caption,
                        reply_markup=reply_markup
                    )
        else:
            await update.callback_query.edit_message_text(caption, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error showing question: {e}")
        await update.callback_query.edit_message_text(caption, reply_markup=reply_markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int, question_index: int, answer: int):
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')
    
    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        await update.callback_query.answer("خطا! لطفاً آزمون را دوباره شروع کنید.")
        return
    
    question = quiz_data['questions'][question_index]
    question_id = question[0]
    
    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    current_answer = user_answers_dict.get(question_id)
    
    if current_answer == answer:
        execute_query("DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s AND question_id = %s", (user_id, quiz_id, question_id))
        await update.callback_query.answer("✅ تیک برداشته شد")
    else:
        save_user_answer(user_id, quiz_id, question_id, answer)
        await update.callback_query.answer("✅ پاسخ ثبت شد")
    
    await show_question(update, context)

async def submit_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')
    
    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        await update.callback_query.answer("خطا! لطفاً آزمون را دوباره شروع کنید.")
        return
    
    total_time = (datetime.now() - quiz_data['start_time']).seconds
    user_answers = get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: ans for q_id, ans in user_answers}
    
    score = 0
    total_questions = len(quiz_data['questions'])
    correct_answers = 0
    wrong_answers = 0
    unanswered_questions = 0
    
    # محاسبه نتایج و به‌روزرسانی سطح سختی
    for i, question in enumerate(quiz_data['questions']):
        question_id, question_image, correct_answer = question
        user_answer = user_answers_dict.get(question_id)
        
        # محاسبه زمان صرف شده برای این سوال (تقریبی)
        time_per_question = total_time / total_questions if total_questions > 0 else 0
        
        if user_answer is None:
            unanswered_questions += 1
            # به‌روزرسانی سطح سختی برای سوالات بی‌پاسخ
            DifficultyAnalyzer.update_question_difficulty(question_id, False, time_per_question)
        elif user_answer == correct_answer:
            score += 1
            correct_answers += 1
            DifficultyAnalyzer.update_question_difficulty(question_id, True, time_per_question)
        else:
            wrong_answers += 1
            DifficultyAnalyzer.update_question_difficulty(question_id, False, time_per_question)
    
    # محاسبه نمره نهایی با نمره منفی
    raw_score = correct_answers
    penalty = wrong_answers / 3.0
    final_score = max(0, raw_score - penalty)
    final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0
    
    # ذخیره نتیجه با رتبه
    save_result_with_rank(user_id, quiz_id, final_percentage, total_time, correct_answers, wrong_answers, unanswered_questions)
    
    # نمایش نتایج به کاربر
    user_message = (
        f"✅ آزمون شما با موفقیت ثبت شد!\n\n"
        f"📊 نتایج:\n"
        f"✅ صحیح: {correct_answers} از {total_questions}\n"
        f"❌ غلط: {wrong_answers} از {total_questions}\n"
        f"⏸️ بی‌پاسخ: {unanswered_questions} از {total_questions}\n"
        f"📈 درصد نهایی: {final_percentage:.2f}%\n"
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n"
    )
    
    # اگر آزمون ادمین باشد، نمایش رتبه
    if quiz_data.get('created_by_admin'):
        user_rank = get_user_rank(user_id, quiz_id)
        if user_rank:
            user_message += f"🏆 رتبه شما: {user_rank[0][0]}\n"
    
    user_message += f"\n💡 نکته: هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد."
    
    keyboard = [[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.callback_query.edit_message_text(user_message, reply_markup=reply_markup)
    except:
        await update.callback_query.message.reply_text(user_message, reply_markup=reply_markup)
    
    # ارسال نتایج به ادمین
    await send_results_to_admin(context, user_id, quiz_id, final_percentage, total_time, correct_answers, wrong_answers, unanswered_questions)
    
    # پاک کردن داده‌های موقت
    if 'current_quiz' in context.user_data:
        del context.user_data['current_quiz']

async def send_results_to_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int, quiz_id: int, score: float, total_time: int, correct: int, wrong: int, unanswered: int):
    user_info = get_user(user_id)
    quiz_info = get_quiz_info(quiz_id)
    
    if not user_info or not quiz_info:
        return
    
    user_data = user_info[0]
    quiz_title = quiz_info[0]
    
    admin_message = (
        "🎯 نتایج آزمون جدید:\n\n"
        f"👤 کاربر: {user_data[3]} (@{user_data[2] if user_data[2] else 'ندارد'})\n"
        f"📞 شماره: {user_data[1]}\n"
        f"🆔 آیدی: {user_id}\n\n"
        f"📚 آزمون: {quiz_title}\n"
        f"✅ پاسخ‌های صحیح: {correct}\n"
        f"❌ پاسخ‌های غلط: {wrong}\n"
        f"⏸️ بی‌پاسخ: {unanswered}\n"
        f"📈 درصد نهایی: {score:.2f}%\n"
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}"
    )
    
    try:
        await context.bot.send_message(ADMIN_ID, admin_message)
    except Exception as e:
        logger.error(f"Error sending results to admin: {e}")

# پنل ادمین
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.edit_message_text("دسترسی denied!")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ ایجاد آزمون جدید", callback_data="admin_create_quiz")],
        [InlineKeyboardButton("📋 مدیریت آزمون‌ها", callback_data="admin_manage_quizzes")],
        [InlineKeyboardButton("📚 مدیریت مباحث", callback_data="admin_manage_topics")],
        [InlineKeyboardButton("❓ افزودن سوال به بانک", callback_data="admin_add_question")],
        [InlineKeyboardButton("🏆 مشاهده رتبه‌بندی", callback_data="admin_quiz_rankings")],
        [InlineKeyboardButton("👥 مشاهده کاربران", callback_data="admin_view_users")],
        [InlineKeyboardButton("📊 مشاهده نتایج", callback_data="admin_view_results")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("🔧 پنل مدیریت ادمین:", reply_markup=reply_markup)

async def admin_quiz_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    quizzes = execute_query("SELECT id, title FROM quizzes WHERE created_by_admin = TRUE ORDER BY created_at DESC")
    
    if not quizzes:
        await update.callback_query.edit_message_text("⚠️ هیچ آزمون ادمینی یافت نشد.")
        return
    
    keyboard = []
    for quiz_id, title in quizzes:
        keyboard.append([InlineKeyboardButton(f"📊 {title}", callback_data=f"quiz_ranking_{quiz_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text("🏆 انتخاب آزمون برای مشاهده رتبه‌بندی:", reply_markup=reply_markup)

async def show_quiz_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    rankings = get_quiz_rankings(quiz_id)
    
    if not rankings:
        await update.callback_query.edit_message_text("⚠️ هیچ نتیجه‌ای برای این آزمون یافت نشد.")
        return
    
    text = f"🏆 رتبه‌بندی آزمون:\n\n"
    for rank in rankings[:20]:  # نمایش 20 رتبه اول
        full_name, score, correct_answers, total_time, user_rank = rank
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        text += f"{user_rank}. {full_name}\n   📈 {score:.1f}% | ✅ {correct_answers} | ⏱ {time_str}\n\n"
    
    if len(rankings) > 20:
        text += f"📊 و {len(rankings) - 20} شرکت‌کننده دیگر..."
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_quiz_rankings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

# توابع کمکی (مانند قبل)
def create_quiz(title: str, description: str, time_limit: int, by_admin: bool = True):
    result = execute_query('''
        INSERT INTO quizzes (title, description, time_limit, is_active, created_by_admin) 
        VALUES (%s, %s, %s, TRUE, %s) RETURNING id
    ''', (title, description, time_limit, by_admin), return_id=True)
    return result[0][0] if result else None

def add_question(quiz_id: int, question_image: str, correct_answer: int, question_order: int):
    return execute_query('''
        INSERT INTO questions (quiz_id, question_image, correct_answer, question_order)
        VALUES (%s, %s, %s, %s)
    ''', (quiz_id, question_image, correct_answer, question_order))

def get_quiz_info(quiz_id: int):
    result = execute_query("SELECT title, description, time_limit, is_active, created_by_admin FROM quizzes WHERE id = %s", (quiz_id,))
    return result[0] if result else None

def get_quiz_questions(quiz_id: int):
    return execute_query("SELECT id, question_image, correct_answer FROM questions WHERE quiz_id = %s ORDER BY question_order, id", (quiz_id,))

def save_user_answer(user_id: int, quiz_id: int, question_id: int, answer: int):
    return execute_query('''
        INSERT INTO user_answers (user_id, quiz_id, question_id, selected_answer) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, quiz_id, question_id) 
        DO UPDATE SET selected_answer = EXCLUDED.selected_answer, answered_at = CURRENT_TIMESTAMP
    ''', (user_id, quiz_id, question_id, answer))

def get_user_answers(user_id: int, quiz_id: int):
    return execute_query("SELECT question_id, selected_answer FROM user_answers WHERE user_id = %s AND quiz_id = %s", (user_id, quiz_id))

def clear_user_answers(user_id: int, quiz_id: int):
    return execute_query("DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s", (user_id, quiz_id))

def get_all_users():
    return execute_query("SELECT user_id, full_name, username, phone_number, registered_at FROM users ORDER BY registered_at DESC")

def get_all_results():
    return execute_query('''
        SELECT u.full_name, q.title, r.score, r.total_time, r.completed_at 
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        JOIN quizzes q ON r.quiz_id = q.id
        ORDER BY r.completed_at DESC
    ''')

async def show_quiz_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quizzes = get_active_quizzes()
    
    if not quizzes:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("⚠️ در حال حاضر هیچ آزمون فعالی وجود ندارد.", reply_markup=reply_markup)
        return
    
    keyboard = []
    for quiz in quizzes:
        quiz_id, title, description, time_limit, created_by_admin = quiz
        admin_icon = " 👑" if created_by_admin else ""
        button_text = f"⏱ {time_limit} دقیقه - {title}{admin_icon}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"quiz_{quiz_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "📋 لیست آزمون‌های فعال:\n\n"
    for quiz in quizzes:
        quiz_id, title, description, time_limit, created_by_admin = quiz
        admin_text = " (آزمون ادمین) 👑" if created_by_admin else ""
        text += f"• {title}{admin_text}\n⏱ {time_limit} دقیقه\n📝 {description}\n\n"
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    results = execute_query('''
        SELECT q.title, r.score, r.correct_answers, r.wrong_answers, r.unanswered_questions, 
               r.total_time, r.completed_at, r.user_rank, q.created_by_admin
        FROM results r
        JOIN quizzes q ON r.quiz_id = q.id
        WHERE r.user_id = %s
        ORDER BY r.completed_at DESC
        LIMIT 10
    ''', (user_id,))
    
    if not results:
        await update.callback_query.edit_message_text("📭 شما هنوز هیچ آزمونی نداده‌اید.")
        return
    
    result_text = "📋 نتایج آزمون‌های شما:\n\n"
    
    for i, result in enumerate(results, 1):
        title, score, correct, wrong, unanswered, total_time, completed_at, user_rank, created_by_admin = result
        
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        completed_date = completed_at.strftime("%Y/%m/%d %H:%M")
        rank_text = f" | 🏆 رتبه: {user_rank}" if created_by_admin and user_rank else ""
        
        result_text += f"{i}. {title}\n"
        result_text += f"   ✅ {correct} | ❌ {wrong} | ⏸️ {unanswered}\n"
        result_text += f"   📈 {score:.1f}% | ⏱ {time_str}{rank_text}\n"
        result_text += f"   📅 {completed_date}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(result_text, reply_markup=reply_markup)

# توابع مدیریت ادمین (مانند قبل)
async def admin_create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    # پیاده‌سازی مشابه قبل...

async def admin_manage_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    # پیاده‌سازی مشابه قبل...

async def admin_view_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    # پیاده‌سازی مشابه قبل...

async def admin_view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    # پیاده‌سازی مشابه قبل...

async def admin_manage_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    # پیاده‌سازی مدیریت مباحث...

async def admin_add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    # پیاده‌سازی افزودن سوال به بانک...

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 راهنمای ربات آزمون:\n\n"
        "1. 📝 شرکت در آزمون: از بین آزمون‌های فعال یکی را انتخاب کنید\n"
        "2. 🎯 ساخت آزمون سفارشی: آزمون شخصی‌سازی شده بسازید\n"
        "3. 📊 نتایج من: مشاهده نتایج و رتبه‌های گذشته\n"
        "4. ⏱ زمان‌بندی: هر آزمون زمان محدودی دارد\n"
        "5. ✅ انتخاب پاسخ: روی گزینه‌ها کلیک کنید\n"
        "6. 🏆 رتبه‌بندی: در آزمون‌های ادمین رتبه کسب کنید\n\n"
        "موفق باشید! 🎯"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup)

async def quiz_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.user_id
    data = job.data
    
    try:
        quiz_id = data['quiz_id']
        chat_id = data['chat_id']
        
        questions = get_quiz_questions(quiz_id)
        if not questions:
            await context.bot.send_message(chat_id, "خطا در دریافت سوالات آزمون!")
            return
        
        user_answers = get_user_answers(user_id, quiz_id)
        user_answers_dict = {q_id: ans for q_id, ans in user_answers}
        
        correct_answers = 0
        wrong_answers = 0
        unanswered_questions = 0
        total_questions = len(questions)
        
        for question in questions:
            question_id, question_image, correct_answer = question
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
        
        save_result_with_rank(user_id, quiz_id, final_percentage, data['time_limit'] * 60, correct_answers, wrong_answers, unanswered_questions)
        
        quiz_info = get_quiz_info(quiz_id)
        quiz_title = quiz_info[0] if quiz_info else "نامشخص"
        
        user_message = (
            "⏰ زمان آزمون به پایان رسید!\n\n"
            f"📊 نتایج:\n"
            f"✅ صحیح: {correct_answers} از {total_questions}\n"
            f"❌ غلط: {wrong_answers} از {total_questions}\n"
            f"⏸️ بی‌پاسخ: {unanswered_questions} از {total_questions}\n"
            f"📈 درصد نهایی: {final_percentage:.2f}%\n"
        )
        
        # بررسی رتبه برای آزمون‌های ادمین
        if quiz_info[4]:  # created_by_admin
            user_rank = get_user_rank(user_id, quiz_id)
            if user_rank:
                user_message += f"🏆 رتبه شما: {user_rank[0][0]}\n"
        
        await context.bot.send_message(
            chat_id,
            user_message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]])
        )
        
    except Exception as e:
        logger.error(f"Error in quiz timeout: {e}")
        await context.bot.send_message(chat_id, "⏰ زمان آزمون به پایان رسید! پاسخ‌های شما ثبت شد.")

def main():
    init_database()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(ChosenInlineResultHandler(chosen_inline_result_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("🤖 ربات در حال اجرا است...")
    application.run_polling()

if __name__ == "__main__":
    main()
