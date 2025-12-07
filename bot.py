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
BOT_TOKEN = "8334186975:AAHcwOGUBYrx436aO3wP_Of_76L2R7DbMwU"
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

# در ابتدای فایل، بعد از imports این تابع کمکی را اضافه کنید
def clear_admin_context(context: ContextTypes.DEFAULT_TYPE):
    """پاک کردن تمام contextهای مربوط به ادمین"""
    keys_to_remove = [
        'admin_quiz', 'quiz_data', 'admin_action', 
        'question_bank_data', 'editing_topic', 'topic_data',
        'resource_data', 'editing_resource'  # جدید
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)

def download_welcome_photo():
    """دانلود عکس از گیت‌هاب"""
    photo_url = "https://raw.githubusercontent.com/Mostafafar/Konkor-of-kings-test/main/welcome.jpg"
    local_path = os.path.join(PHOTOS_DIR, "welcome.jpg")
    
    try:
        # همیشه دانلود کن (حتی اگر فایل وجود دارد)
        response = requests.get(photo_url, timeout=10)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(response.content)
            logger.info("Welcome photo downloaded/updated successfully")
            return True
        else:
            logger.error(f"Failed to download photo. Status code: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error downloading welcome photo: {e}")
        return False


        
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
        
        # جدول آزمون‌ها - اضافه کردن ستون created_by_admin
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
        
        # اضافه کردن ستون created_by_admin اگر وجود ندارد
        cursor.execute('''
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='quizzes' AND column_name='created_by_admin') THEN
                    ALTER TABLE quizzes ADD COLUMN created_by_admin BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        ''')
        
        # بقیه جداول...
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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topics (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول منابع (جدید)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resources (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS question_bank (
                id SERIAL PRIMARY KEY,
                topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
                resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
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
        
        # تغییر جدول question_bank برای اضافه کردن resource_id اگر وجود ندارد
        cursor.execute('''
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='question_bank' AND column_name='resource_id') THEN
                    ALTER TABLE question_bank ADD COLUMN resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL;
                END IF;
            END $$;
        ''')
        
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
async def admin_manage_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت منابع"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    resources = get_all_resources()
    
    if not resources:
        keyboard = [
            [InlineKeyboardButton("➕ افزودن منبع جدید", callback_data="admin_add_resource")],
            [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ منبعی یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    text = "📖 مدیریت منابع:\n\n"
    for resource in resources:
        resource_id, name, description, is_active = resource
        status = "✅ فعال" if is_active else "❌ غیرفعال"
        text += f"• {name} ({status})\n"
        if description:
            text += f"  📝 {description}\n"
        text += f"  🆔 کد: {resource_id}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ افزودن منبع جدید", callback_data="admin_add_resource")],
        [InlineKeyboardButton("✏️ ویرایش منبع", callback_data="admin_edit_resource")],
        [InlineKeyboardButton("❌ حذف منبع", callback_data="admin_delete_resource")],
        [InlineKeyboardButton("🔍 مشاهده سوالات منبع", callback_data="admin_view_resource_questions")],
        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def admin_add_resource(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن منبع جدید"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'adding_resource'
    context.user_data['resource_data'] = {'step': 'name'}
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به مدیریت منابع", callback_data="admin_manage_resources")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📖 افزودن منبع جدید:\n\n"
        "لطفاً نام منبع را ارسال کنید:",
        reply_markup=reply_markup
    )
async def handle_first_resource_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب منبع اول"""
    try:
        text = update.message.text
        resource_name = text.replace("منبع انتخاب شده:", "").strip()
        
        resource_info = get_resource_by_name(resource_name)
        if not resource_info:
            await update.message.reply_text(f"❌ منبع '{resource_name}' یافت نشد!")
            return
        
        resource_id, name, description, is_active = resource_info[0]
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_resource(resource_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای منبع '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن منبع به لیست
        context.user_data['custom_quiz']['selected_resources'].append(resource_id)
        context.user_data['custom_quiz']['step'] = 'settings'
        context.user_data['custom_quiz']['first_resource_name'] = name
        
        await show_initial_settings_for_resources(update, context)
        
    except Exception as e:
        logger.error(f"Error in first resource selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب منبع!")

async def handle_resource_selection_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب منبع از پیام"""
    try:
        text = update.message.text
        resource_name = text.replace("منبع انتخاب شده:", "").strip()
        
        resource_info = get_resource_by_name(resource_name)
        if not resource_info:
            await update.message.reply_text(f"❌ منبع '{resource_name}' یافت نشد!")
            return
        
        resource_id, name, description, is_active = resource_info[0]
        
        # ذخیره منبع و رفتن به مرحله بعد
        question_data = context.user_data['question_bank_data']
        question_data['resource_id'] = resource_id
        question_data['resource_name'] = name
        question_data['step'] = 'waiting_for_photo'
        
        await update.message.reply_text(
            f"✅ منبع انتخاب شد: **{name}**\n\n"
            f"**مرحله ۳/۴: ارسال عکس سوال**\n\n"
            f"📸 لطفاً عکس سوال را ارسال کنید:",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error in resource selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب منبع!")
# توابعمدیریت منابع
def get_all_resources():
    return execute_query("SELECT id, name, description, is_active FROM resources ORDER BY name")

def get_resource_by_id(resource_id: int):
    return execute_query("SELECT id, name, description, is_active FROM resources WHERE id = %s", (resource_id,))

def get_resource_by_name(name: str):
    return execute_query("SELECT id, name, description, is_active FROM resources WHERE name = %s AND is_active = TRUE", (name,))

def get_questions_count_by_resource(resource_id: int):
    """دریافت تعداد سوالات موجود برای یک منبع"""
    return execute_query(
        "SELECT COUNT(*) FROM question_bank WHERE resource_id = %s AND is_active = TRUE",
        (resource_id,)
    )

def get_resource_name(resource_id: int):
    """دریافت نام منبع بر اساس ID"""
    result = execute_query("SELECT name FROM resources WHERE id = %s", (resource_id,))
    return result[0][0] if result else "نامشخص"

def add_resource(name: str, description: str = ""):
    return execute_query(
        "INSERT INTO resources (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING RETURNING id",
        (name, description), return_id=True
    )

def update_resource(resource_id: int, name: str, description: str = ""):
    return execute_query(
        "UPDATE resources SET name = %s, description = %s WHERE id = %s",
        (name, description, resource_id)
    )

def delete_resource(resource_id: int):
    return execute_query("DELETE FROM resources WHERE id = %s", (resource_id,))

def toggle_resource_status(resource_id: int):
    """تغییر وضعیت فعال/غیرفعال منبع"""
    return execute_query(
        "UPDATE resources SET is_active = NOT is_active WHERE id = %s", 
        (resource_id,)
    )

# تابع اصلاح شده برای افزودن سوال به بانک با منبع

# تابع اصلاح شده برای دریافت سوالات
def get_questions_by_resources(resource_ids: List[int], difficulty: str = 'all', limit: int = 20):
    if not resource_ids:
        return []
    
    if difficulty == 'all':
        query = """
            SELECT id, question_image, correct_answer, auto_difficulty_score 
            FROM question_bank 
            WHERE resource_id = ANY(%s) AND is_active = TRUE
            ORDER BY RANDOM() 
            LIMIT %s
        """
        return execute_query(query, (resource_ids, limit))
    else:
        query = """
            SELECT id, question_image, correct_answer, auto_difficulty_score 
            FROM question_bank 
            WHERE resource_id = ANY(%s) AND is_active = TRUE
            ORDER BY auto_difficulty_score {}
            LIMIT %s
        """.format("DESC" if difficulty == 'hard' else "ASC")
        return execute_query(query, (resource_ids, limit))
        

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
    return execute_query("SELECT id, name, description, is_active FROM topics ORDER BY name")

def get_topic_by_id(topic_id: int):
    return execute_query("SELECT id, name, description, is_active FROM topics WHERE id = %s", (topic_id,))

def get_topic_by_name(name: str):
    return execute_query("SELECT id, name, description, is_active FROM topics WHERE name = %s AND is_active = TRUE", (name,))
def get_questions_count_by_topic(topic_id: int):
    """دریافت تعداد سوالات موجود برای یک مبحث"""
    return execute_query(
        "SELECT COUNT(*) FROM question_bank WHERE topic_id = %s AND is_active = TRUE",
        (topic_id,)
    )

def get_topic_name(topic_id: int):
    """دریافت نام مبحث بر اساس ID"""
    result = execute_query("SELECT name FROM topics WHERE id = %s", (topic_id,))
    return result[0][0] if result else "نامشخص"

def add_topic(name: str, description: str = ""):
    return execute_query(
        "INSERT INTO topics (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING RETURNING id",
        (name, description), return_id=True
    )

# توابع بانک سوالات
def add_question_to_bank(topic_id: int, resource_id: int, question_image: str, correct_answer: int):
    """افزودن سوال به بانک با مبحث و منبع"""
    return execute_query('''
        INSERT INTO question_bank (topic_id, resource_id, question_image, correct_answer)
        VALUES (%s, %s, %s, %s) RETURNING id
    ''', (topic_id, resource_id, question_image, correct_answer), return_id=True)

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
                "🎯 **آزمون آزمایشی قلمچی — رایگان!** 🎯\n\n"
                
                "🔥 **قلمچی امروز رو رایگان شرکت کن**\n"
                "✅ آزمون‌ قلمچی\n"
                "✅ شرایط واقعی سر جلسه\n"
                "✅ تراز + درصد + رتبه\n\n"
                
                "📊 **همه امکانات رایگان:**\n"
                "🎯 تراز دقیق کنکوری\n"
                "📈 درصد دروس مختلف\n"
                "🏆 رتبه‌بندی کشوری\n"
                "⏱ زمان‌بندی واقعی\n\n"
                
                "📚 **ساخت آزمون شخصی:**\n"
                "✨ انتخاب مباحث دلخواه\n"
                "✨ سطح‌بندی سوالات\n"
                "✨ تست هوشمند\n\n"
                
                "🚀 **برنامه شخصی‌سازی شده بعد از آزمون می‌گیری!**\n"
                "👇 از منوی زیر آزمون خودت رو شروع کن:"
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
    
    # هندلرهای جدید برای مدیریت منابع
    # هندلرهای جدید برای تنظیمات اولیه
    if data == "ask_question_count":
        await ask_for_question_count(update, context)
    elif data == "ask_time_limit":
        await ask_for_time_limit(update, context)
    elif data == "initial_set_difficulty":
        await initial_set_difficulty(update, context)
    elif data.startswith("initial_set_difficulty_"):
        difficulty = data.split("_")[3]
        context.user_data['custom_quiz']['settings']['difficulty'] = difficulty
        await back_to_initial_settings(update, context)
    elif data == "add_more_topics":
        await add_more_topics(update, context)
    elif data == "back_to_initial_settings":
        await back_to_initial_settings(update, context)
    # در تابع handle_callback (حدود خط 500) این موارد را اضافه کنید:
    elif data == "add_more_resources":
        await add_more_resources(update, context)
    
    # هندلرهای جدید برای مدیریت منابع
    elif data == "admin_manage_resources":
        await admin_manage_resources(update, context)
    elif data == "admin_add_resource":
        await admin_add_resource(update, context)
    elif data == "admin_edit_resource":
        await admin_edit_resource(update, context)
    elif data == "admin_delete_resource":
        await admin_delete_resource(update, context)
    elif data == "admin_view_resource_questions":
        await admin_view_resource_questions(update, context)
    elif data.startswith("edit_resource_"):
        resource_id = int(data.split("_")[2])
        await start_resource_editing(update, context, resource_id)
    elif data.startswith("delete_resource_"):
        resource_id = int(data.split("_")[2])
        await confirm_resource_deletion(update, context, resource_id)
    elif data.startswith("view_resource_questions_"):
        resource_id = int(data.split("_")[3])
        await show_resource_questions(update, context, resource_id)
    elif data.startswith("confirm_delete_resource_"):
        resource_id = int(data.split("_")[3])
        await delete_resource_handler(update, context, resource_id)
    elif data.startswith("toggle_resource_status_"):
        resource_id = int(data.split("_")[3])
        await toggle_resource_status(update, context, resource_id)
    elif data == "edit_resource_name":
        await edit_resource_name_handler(update, context)
    elif data == "edit_resource_description":
        await edit_resource_description_handler(update, context)
    elif data == "back_to_resource_editing":
        if 'editing_resource' in context.user_data:
            resource_id = context.user_data['editing_resource']['resource_id']
            await start_resource_editing(update, context, resource_id)
    elif data == "back_to_resource_management":
        await admin_manage_resources(update, context)
    
    # هندلرهای مدیریت مباحث
    elif data == "edit_topic_name":
        await edit_topic_name_handler(update, context)
    elif data == "edit_topic_description":
        await edit_topic_description_handler(update, context)
    elif data == "admin_edit_topic":
        await admin_edit_topic(update, context)
    elif data == "admin_delete_topic":
        await admin_delete_topic(update, context)
    elif data == "admin_view_topic_questions":
        await admin_view_topic_questions(update, context)
    elif data.startswith("edit_topic_"):
        topic_id = int(data.split("_")[2])
        await start_topic_editing(update, context, topic_id)
    elif data.startswith("delete_topic_"):
        topic_id = int(data.split("_")[2])
        await confirm_topic_deletion(update, context, topic_id)
    elif data.startswith("view_topic_questions_"):
        topic_id = int(data.split("_")[3])
        await show_topic_questions(update, context, topic_id)
    elif data.startswith("confirm_delete_topic_"):
        topic_id = int(data.split("_")[3])
        await delete_topic(update, context, topic_id)
    elif data.startswith("toggle_topic_status_"):
        topic_id = int(data.split("_")[3])
        await toggle_topic_status(update, context, topic_id)
    
    # هندلرهای اصلی منو
    elif data == "take_quiz":
        await show_quiz_list(update, context)
    elif data == "create_custom_quiz":
        await start_custom_quiz_creation(update, context)
    elif data == "my_results":
        await show_my_results(update, context)
    elif data == "help":
        await show_help(update, context)
    elif data == "admin_panel":
        await show_admin_panel(update, context)
    
    # هندلرهای آزمون
    elif data.startswith("quiz_"):
        # بررسی اینکه آیا quiz_ranking است یا quiz معمولی
        if data.startswith("quiz_ranking_"):
            quiz_id = int(data.split("_")[2])
            await show_quiz_rankings(update, context, quiz_id)
        else:
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
    
    # هندلرهای ناوبری
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "back_to_admin_panel":
        await show_admin_panel(update, context)
    elif data == "back_to_quiz_list":
        await show_quiz_list(update, context)
    elif data == "back_to_custom_quiz":
        await start_custom_quiz_creation(update, context)
    elif data == "back_to_topic_editing":
        if 'editing_topic' in context.user_data:
            topic_id = context.user_data['editing_topic']['topic_id']
            await start_topic_editing(update, context, topic_id)
    
    # هندلرهای پنل ادمین
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
        await admin_add_question_to_bank(update, context)
    elif data == "admin_quiz_rankings":
        await admin_quiz_rankings(update, context)
    elif data == "admin_broadcast":
        await admin_broadcast_message(update, context)
    elif data == "confirm_add_questions":
        await start_adding_questions(update, context)
    elif data == "add_another_question":
        await start_adding_questions(update, context)
    elif data.startswith("toggle_quiz_"):
        quiz_id = int(data.split("_")[2])
        await toggle_quiz_status_handler(update, context, quiz_id)
    elif data.startswith("quiz_ranking_"):
        quiz_id = int(data.split("_")[2])
        await show_quiz_rankings(update, context, quiz_id)
    # در تابع handle_callback این موارد را اضافه کنید:
    elif data == "admin_select_topics_mode":
        await admin_select_topics_mode(update, context)
    elif data == "admin_select_resources_mode":
        await admin_select_resources_mode(update, context)
    elif data == "admin_select_both_mode":
        await admin_select_both_mode(update, context)    
    # هندلرهای ایجاد آزمون ادمین
    elif data == "admin_ask_title":
        await admin_ask_for_title(update, context)
    elif data == "admin_ask_description":
        await admin_ask_for_description(update, context)
    elif data == "admin_ask_question_count":
        await admin_ask_for_question_count(update, context)
    elif data == "admin_ask_time_limit":
        await admin_ask_for_time_limit(update, context)
    elif data == "admin_set_difficulty":
        await admin_set_difficulty(update, context)
    elif data.startswith("admin_set_difficulty_"):
        difficulty = data.split("_")[3]
        context.user_data['admin_quiz']['settings']['difficulty'] = difficulty
        await admin_back_to_settings(update, context)
    elif data == "admin_add_more_topics":
        await admin_add_more_topics(update, context)
    elif data == "admin_back_to_settings":
        await admin_back_to_settings(update, context)
    elif data == "admin_generate_quiz":
        await admin_generate_quiz(update, context)
    
    # هندلرهای آزمون سفارشی
    elif data == "custom_quiz_settings":
        await custom_quiz_settings(update, context)
    elif data.startswith("set_count_"):
        count = int(data.split("_")[2])
        if 'custom_quiz' in context.user_data:
            context.user_data['custom_quiz']['settings']['count'] = count
        await custom_quiz_settings(update, context)
    elif data.startswith("set_time_"):
        time_limit = int(data.split("_")[2])
        if 'custom_quiz' in context.user_data:
            context.user_data['custom_quiz']['settings']['time_limit'] = time_limit
        await custom_quiz_settings(update, context)
    elif data.startswith("set_difficulty_"):
        difficulty = data.split("_")[2]
        if 'custom_quiz' in context.user_data:
            context.user_data['custom_quiz']['settings']['difficulty'] = difficulty
        await custom_quiz_settings(update, context)
    elif data == "generate_custom_quiz":
        await generate_custom_quiz(update, context)
    elif data == "select_topics_mode":
        await select_topics_mode(update, context)
    elif data == "select_resources_mode":
        await select_resources_mode(update, context)
    
    # هندلرهای مدیریت منابع
    elif data == "admin_manage_resources":
        await admin_manage_resources(update, context)
    elif data == "admin_add_resource":
        await admin_add_resource(update, context)
    
    # هندلرهای منوهای تنظیمات
    elif data == "set_count_menu":
        await set_count_menu(update, context)
    elif data == "set_time_menu":
        await set_time_menu(update, context)
    elif data == "set_difficulty_menu":
        await set_difficulty_menu(update, context)
    elif data == "clear_custom_topics":
        await clear_custom_topics(update, context)
    
    # هندلرهای مدیریت مباحث
    elif data == "admin_add_topic":
        await admin_add_topic(update, context)
    
    # هندلرهای اضافی برای مشاهده جزئیات
    elif data.startswith("full_ranking_"):
        quiz_id = int(data.split("_")[2])
        await show_full_ranking(update, context, quiz_id)
    elif data == "detailed_stats":
        await show_detailed_stats(update, context)
    
    else:
        # اگر هیچکدام از هندلرها مطابقت نداشت
        logger.warning(f"Unknown callback data: {data}")
        await query.answer("⚠️ این دکمه در حال حاضر فعال نیست!")
async def show_full_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """نمایش جزئیات کامل رتبه‌بندی یک آزمون"""
    rankings = get_quiz_comprehensive_rankings(quiz_id)
    quiz_info = get_quiz_info(quiz_id)
    
    if not rankings or not quiz_info:
        await update.callback_query.answer("❌ اطلاعات یافت نشد!")
        return
    
    quiz_title = quiz_info[0]
    
    text = f"📊 جزئیات کامل رتبه‌بندی: **{quiz_title}**\n\n"
    
    for rank in rankings:
        full_name, score, correct, wrong, unanswered, total_time, user_rank, completed_at = rank
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        date_str = completed_at.strftime("%m/%d %H:%M")
        
        text += f"**{user_rank}. {full_name}**\n"
        text += f"   📈 {score:.1f}% | ✅{correct} ❌{wrong} ⏸️{unanswered}\n"
        text += f"   ⏱ {time_str} | 📅 {date_str}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"quiz_ranking_{quiz_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)



def get_quiz_comprehensive_rankings(quiz_id: int):
    """دریافت رتبه‌بندی کامل یک آزمون با تمام جزئیات"""
    return execute_query('''
        SELECT 
            u.full_name, 
            r.score, 
            r.correct_answers,
            r.wrong_answers,
            r.unanswered_questions,
            r.total_time, 
            r.user_rank,
            r.completed_at
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.quiz_id = %s
        ORDER BY r.user_rank, r.completed_at
    ''', (quiz_id,))

def get_user_comprehensive_stats():
    """دریافت آمار تلفیقی کاربران با محاسبه امتیاز ترکیبی"""
    return execute_query('''
        SELECT 
            u.user_id,
            u.full_name,
            COUNT(r.id) as total_quizzes,
            COALESCE(AVG(r.score), 0) as avg_score,
            COALESCE(MAX(r.score), 0) as best_score,
            COALESCE(SUM(r.correct_answers), 0) as total_correct,
            COALESCE(SUM(r.total_time), 0) as total_time,
            -- محاسبه امتیاز ترکیبی
            (COALESCE(AVG(r.score), 0) * 0.7) + (
                CASE 
                    WHEN COUNT(r.id) > 10 THEN 30
                    ELSE COUNT(r.id) * 3
                END
            ) as composite_score
        FROM users u
        LEFT JOIN results r ON u.user_id = r.user_id
        WHERE r.id IS NOT NULL
        GROUP BY u.user_id, u.full_name
        HAVING COUNT(r.id) > 0
        ORDER BY composite_score DESC
    ''')
# ساخت آزمون سفارشی
async def start_custom_quiz_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['custom_quiz'] = {
        'step': 'select_first_topic',
        'selected_topics': [],
        'settings': {
            'count': 20,
            'time_limit': 30,
            'difficulty': 'all'
        }
    }
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب مبحث اول", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 ساخت آزمون سفارشی\n\n"
        "مرحله ۱/۴: انتخاب مبحث اول\n\n"
        "روی دکمه زیر کلیک کنید و مبحث اول را انتخاب کنید:",
        reply_markup=reply_markup
        )

async def handle_first_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """مدیریت انتخاب مبحث اول در آزمون سفارشی"""
    try:
        user_id = update.effective_user.id
        
        # دریافت اطلاعات مبحث
        topic_info = get_topic_by_id(topic_id)
        if not topic_info:
            await update.message.reply_text("❌ مبحث یافت نشد!")
            return
        
        topic_id, name, description, is_active = topic_info[0]
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_topic(topic_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای مبحث '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن مبحث به لیست
        context.user_data['custom_quiz']['selected_topics'].append(topic_id)
        context.user_data['custom_quiz']['step'] = 'settings'
        context.user_data['custom_quiz']['first_topic_name'] = name
        
        # نمایش تنظیمات
        await show_initial_settings(update, context)
        
    except Exception as e:
        logger.error(f"Error in first topic selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")

# تابع جدید برای نمایش تنظیمات اولیه
async def show_initial_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تنظیمات اولیه بعد از انتخاب مبحث اول"""
    quiz_data = context.user_data['custom_quiz']
    settings = quiz_data['settings']
    first_topic_name = quiz_data.get('first_topic_name', 'نامشخص')
    
    # محاسبه سوالات قابل دسترس برای مبحث اول
    available_questions = get_questions_count_by_topic(quiz_data['selected_topics'][0])[0][0]
    
    # متن نمایشی برای سطح سختی
    difficulty_texts = {
        'all': '🎯 همه سطوح',
        'easy': '🟢 آسان', 
        'medium': '🟡 متوسط',
        'hard': '🔴 سخت'
    }
    difficulty_text = difficulty_texts.get(settings['difficulty'], '🎯 همه سطوح')
    
    keyboard = [
        [InlineKeyboardButton(f"📊 تعداد سوالات: {settings['count']}", callback_data="initial_set_count")],
        [InlineKeyboardButton(f"🎯 سطح سختی: {difficulty_text}", callback_data="initial_set_difficulty")],
        [InlineKeyboardButton(f"⏱ زمان: {settings['time_limit']} دقیقه", callback_data="initial_set_time")],
        [InlineKeyboardButton("➕ افزودن مبحث دیگر", callback_data="add_more_topics")],
        [InlineKeyboardButton("🚀 ساخت و شروع آزمون", callback_data="generate_custom_quiz")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"✅ مبحث اول انتخاب شد: **{first_topic_name}**\n\n"
        f"📊 سوالات قابل دسترس: {available_questions}\n\n"
        f"⚙️ تنظیمات آزمون:\n"
        f"• تعداد سوالات: {settings['count']}\n" 
        f"• سطح سختی: {difficulty_text}\n"
        f"• زمان: {settings['time_limit']} دقیقه\n\n"
        f"می‌توانید:\n"
        f"• تنظیمات را تغییر دهید\n"
        f"• مباحث بیشتری اضافه کنید\n" 
        f"• یا آزمون را شروع کنید"
    )
    
    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# توابع جدید برای تنظیمات اولیه
async def ask_for_question_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست تعداد سوالات از کاربر"""
    context.user_data['custom_quiz']['step'] = 'waiting_for_count'
    
    # محاسبه حداکثر سوالات قابل دسترس
    total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in context.user_data['custom_quiz']['selected_topics']])
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_initial_settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📊 تعیین تعداد سوالات\n\n"
        f"📚 سوالات قابل دسترس: {total_available}\n\n"
        f"لطفاً تعداد سوالات مورد نظر را وارد کنید (عدد بین ۱ تا {total_available}):",
        reply_markup=reply_markup
    )

async def ask_for_time_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست زمان آزمون از کاربر"""
    context.user_data['custom_quiz']['step'] = 'waiting_for_time'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_initial_settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "⏱ تعیین زمان آزمون\n\n"
        "لطفاً زمان آزمون را به دقیقه وارد کنید (مثلاً 30 برای ۳۰ دقیقه):\n\n"
        "💡 پیشنهاد: برای هر سوال ۱-۲ دقیقه در نظر بگیرید",
        reply_markup=reply_markup
    )

async def initial_set_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنظیم سطح سختی در مرحله اولیه"""
    keyboard = [
        [InlineKeyboardButton("🎯 همه سطوح", callback_data="initial_set_difficulty_all")],
        [InlineKeyboardButton("🟢 آسان", callback_data="initial_set_difficulty_easy")],
        [InlineKeyboardButton("🟡 متوسط", callback_data="initial_set_difficulty_medium")],
        [InlineKeyboardButton("🔴 سخت", callback_data="initial_set_difficulty_hard")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="back_to_initial_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 انتخاب سطح سختی\n\n"
        "لطفاً سطح مورد نظر را انتخاب کنید:\n\n"
        "• 🎯 همه سطوح: ترکیبی از سوالات آسان، متوسط و سخت\n"
        "• 🟢 آسان: سوالات با نرخ موفقیت بالا\n" 
        "• 🟡 متوسط: سوالات با سختی متوسط\n"
        "• 🔴 سخت: سوالات چالشی با نرخ موفقیت پایین",
        reply_markup=reply_markup
    )




async def add_more_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن مباحث بیشتر"""
    context.user_data['custom_quiz']['step'] = 'adding_more_topics'
    
    # نمایش مباحث انتخاب شده فعلی
    topics_text = "\n".join([
        f"• {get_topic_name(tid)}"
        for tid in context.user_data['custom_quiz']['selected_topics']
    ])
    
    keyboard = [
        [InlineKeyboardButton("🔍 افزودن مبحث جدید", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="back_to_initial_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📚 افزودن مباحث بیشتر\n\n"
        f"مباحث انتخاب شده فعلی:\n{topics_text}\n\n"
        f"روی دکمه زیر کلیک کنید تا مبحث جدیدی اضافه کنید:",
        reply_markup=reply_markup
    )

async def back_to_initial_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به تنظیمات اولیه"""
    context.user_data['custom_quiz']['step'] = 'settings'
    await show_initial_settings_from_callback(update, context)

async def show_initial_settings_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تنظیمات اولیه از callback"""
    quiz_data = context.user_data['custom_quiz']
    settings = quiz_data['settings']
    
    # محاسبه کل سوالات قابل دسترس
    total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in quiz_data['selected_topics']])
    
    # نمایش نام مباحث انتخاب شده
    topics_text = "\n".join([f"• {get_topic_name(tid)}" for tid in quiz_data['selected_topics']])
    
    # متن نمایشی برای سطح سختی
    difficulty_texts = {
        'all': '🎯 همه سطوح',
        'easy': '🟢 آسان',
        'medium': '🟡 متوسط', 
        'hard': '🔴 سخت'
    }
    difficulty_text = difficulty_texts.get(settings['difficulty'], '🎯 همه سطوح')
    
    # تغییر دکمه‌ها به ورود عددی
    keyboard = [
        [InlineKeyboardButton(f"📊 تعداد سوالات: {settings['count']}", callback_data="ask_question_count")],
        [InlineKeyboardButton(f"🎯 سطح سختی: {difficulty_text}", callback_data="initial_set_difficulty")],
        [InlineKeyboardButton(f"⏱ زمان: {settings['time_limit']} دقیقه", callback_data="ask_time_limit")],
        [InlineKeyboardButton("➕ افزودن مبحث دیگر", callback_data="add_more_topics")],
        [InlineKeyboardButton("🚀 ساخت و شروع آزمون", callback_data="generate_custom_quiz")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"🎯 تنظیمات آزمون سفارشی\n\n"
        f"📚 مباحث انتخاب شده:\n{topics_text}\n\n"
        f"📊 سوالات قابل دسترس: {total_available}\n\n"
        f"⚙️ تنظیمات فعلی:\n"
        f"• تعداد سوالات: {settings['count']}\n"
        f"• سطح سختی: {difficulty_text}\n"
        f"• زمان: {settings['time_limit']} دقیقه\n\n"
        f"برای تغییر هر مورد، روی آن کلیک کنید:"
    )
    
    await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)

async def set_count_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب تعداد سوالات"""
    # محاسبه حداکثر سوالات قابل دسترس
    total_available = 0
    if context.user_data['custom_quiz']['selected_topics']:
        total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in context.user_data['custom_quiz']['selected_topics']])
    
    keyboard = []
    counts = [10, 15, 20, 25, 30, 40, 50]
    
    for count in counts:
        if count <= total_available:
            keyboard.append([InlineKeyboardButton(f"{count} سوال", callback_data=f"set_count_{count}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="custom_quiz_settings")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📊 انتخاب تعداد سوالات\n\n"
        f"📚 سوالات قابل دسترس: {total_available}\n\n"
        f"لطفاً تعداد سوالات را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def set_time_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب زمان"""
    keyboard = [
        [InlineKeyboardButton("۱۵ دقیقه", callback_data="set_time_15")],
        [InlineKeyboardButton("۳۰ دقیقه", callback_data="set_time_30")],
        [InlineKeyboardButton("۴۵ دقیقه", callback_data="set_time_45")],
        [InlineKeyboardButton("۶۰ دقیقه", callback_data="set_time_60")],
        [InlineKeyboardButton("۹۰ دقیقه", callback_data="set_time_90")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="custom_quiz_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "⏱ انتخاب زمان آزمون\n\nلطفاً زمان مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def set_difficulty_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب سطح سختی"""
    keyboard = [
        [InlineKeyboardButton("🎯 همه سطوح", callback_data="set_difficulty_all")],
        [InlineKeyboardButton("🟢 آسان", callback_data="set_difficulty_easy")],
        [InlineKeyboardButton("🟡 متوسط", callback_data="set_difficulty_medium")],
        [InlineKeyboardButton("🔴 سخت", callback_data="set_difficulty_hard")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="custom_quiz_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 انتخاب سطح سختی\n\nلطفاً سطح مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def clear_custom_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاک کردن همه مباحث انتخاب شده"""
    if 'custom_quiz' in context.user_data:
        context.user_data['custom_quiz']['selected_topics'] = []
    
    keyboard = [
        [InlineKeyboardButton("➕ افزودن مبحث", switch_inline_query_current_chat="مبحث ")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🗑️ همه مباحث حذف شدند.\n\n"
        "لطفاً مباحث جدید را انتخاب کنید:",
        reply_markup=reply_markup
    )
async def handle_first_topic_selection_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب مبحث اول از طریق پیام"""
    try:
        text = update.message.text
        topic_name = text.replace("مبحث انتخاب شده:", "").strip()
        
        topic_info = get_topic_by_name(topic_name)
        if not topic_info:
            await update.message.reply_text(f"❌ مبحث '{topic_name}' یافت نشد!")
            return
        
        topic_id, name, description, is_active = topic_info[0]
        await handle_first_topic_selection(update, context, topic_id)
        
    except Exception as e:
        logger.error(f"Error in first topic selection from message: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")

# تابع جدید برای پردازش انتخاب مباحث اضافی
async def handle_additional_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب مباحث اضافی"""
    try:
        text = update.message.text
        topic_name = text.replace("مبحث انتخاب شده:", "").strip()
        
        topic_info = get_topic_by_name(topic_name)
        if not topic_info:
            await update.message.reply_text(f"❌ مبحث '{topic_name}' یافت نشد!")
            return
        
        topic_id, name, description, is_active = topic_info[0]
        
        # بررسی تکراری نبودن مبحث
        if topic_id in context.user_data['custom_quiz']['selected_topics']:
            await update.message.reply_text(f"❌ مبحث '{name}' قبلاً اضافه شده است!")
            return
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_topic(topic_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای مبحث '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن مبحث به لیست
        context.user_data['custom_quiz']['selected_topics'].append(topic_id)
        
        # بازگشت به تنظیمات
        context.user_data['custom_quiz']['step'] = 'settings'
        await show_initial_settings_from_message(update, context)
        
    except Exception as e:
        logger.error(f"Error in additional topic selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")


async def process_question_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش تعداد سوالات وارد شده توسط کاربر"""
    try:
        text = update.message.text.strip()
        count = int(text)
        
        # محاسبه حداکثر سوالات قابل دسترس
        total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in context.user_data['custom_quiz']['selected_topics']])
        
        if count < 1:
            await update.message.reply_text("❌ تعداد سوالات باید حداقل ۱ باشد!")
            return
        elif count > total_available:
            await update.message.reply_text(
                f"❌ تعداد سوالات نمی‌تواند بیشتر از {total_available} باشد!\n\n"
                f"لطفاً عدد کوچکتری وارد کنید:"
            )
            return
        
        # ذخیره تعداد سوالات
        context.user_data['custom_quiz']['settings']['count'] = count
        context.user_data['custom_quiz']['step'] = 'settings'
        
        await update.message.reply_text(f"✅ تعداد سوالات روی {count} تنظیم شد")
        await show_initial_settings_from_message(update, context)
        
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")

async def process_time_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش زمان آزمون وارد شده توسط کاربر"""
    try:
        text = update.message.text.strip()
        time_limit = int(text)
        
        if time_limit < 1:
            await update.message.reply_text("❌ زمان آزمون باید حداقل ۱ دقیقه باشد!")
            return
        elif time_limit > 180:  # حداکثر ۳ ساعت
            await update.message.reply_text("❌ زمان آزمون نمی‌تواند بیشتر از ۱۸۰ دقیقه باشد!")
            return
        
        # ذخیره زمان آزمون
        context.user_data['custom_quiz']['settings']['time_limit'] = time_limit
        context.user_data['custom_quiz']['step'] = 'settings'
        
        await update.message.reply_text(f"✅ زمان آزمون روی {time_limit} دقیقه تنظیم شد")
        await show_initial_settings_from_message(update, context)
        
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")
            
            
    
    

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی"""
    if update.message.contact:
        await handle_contact(update, context)
        return
    
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    
    logger.info(f"📝 HANDLE_MESSAGE: User {user_id}, Text: '{text}', Context: {context.user_data}")

    # ===== اولویت 1: پردازش عملیات ادمین =====
    if user_id == ADMIN_ID:
        # 1.1 پردازش افزودن منبع جدید
        if (context.user_data.get('admin_action') == 'adding_resource' and
            'resource_data' in context.user_data):
            
            resource_data = context.user_data['resource_data']
            
            if resource_data.get('step') == 'name':
                resource_name = text.strip()
                
                if len(resource_name) < 2:
                    await update.message.reply_text("❌ نام منبع باید حداقل ۲ کاراکتر باشد!")
                    return
                
                existing_resource = get_resource_by_name(resource_name)
                if existing_resource:
                    await update.message.reply_text("❌ منبعی با این نام از قبل وجود دارد!")
                    return
                
                resource_data['name'] = resource_name
                resource_data['step'] = 'description'
                
                await update.message.reply_text(
                    f"✅ نام منبع ذخیره شد: **{resource_name}**\n\n"
                    f"لطفاً توضیحات منبع را ارسال کنید (اختیاری):\n\n"
                    f"💡 می‌توانید 'ندارد' را ارسال کنید تا از توضیحات صرف نظر کنید.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            elif resource_data.get('step') == 'description':
                description = text.strip()
                
                if description == 'ندارد':
                    description = ""
                
                result = add_resource(resource_data['name'], description)
                
                if result:
                    await update.message.reply_text(
                        f"✅ منبع **{resource_data['name']}** با موفقیت اضافه شد!",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text("❌ خطا در افزودن منبع!")
                
                # پاک کردن داده‌های موقت
                context.user_data.pop('resource_data', None)
                context.user_data.pop('admin_action', None)
                return

        # 1.2 پردازش انتخاب مبحث برای افزودن سوال به بانک
        if (text.startswith('مبحث انتخاب شده:') and
            context.user_data.get('admin_action') == 'adding_question_to_bank' and
            context.user_data.get('question_bank_data', {}).get('step') == 'selecting_topic'):
            
            await handle_topic_selection_for_question_bank(update, context)
            return

        # 1.3 پردازش انتخاب منبع برای افزودن سوال به بانک
        if (text.startswith('منبع انتخاب شده:') and
            context.user_data.get('admin_action') == 'adding_question_to_bank' and
            context.user_data.get('question_bank_data', {}).get('step') == 'selecting_resource'):
            
            await handle_resource_selection_for_question_bank(update, context)
            return

        # 1.4 پردازش پاسخ صحیح برای سوال بانک
        if (context.user_data.get('admin_action') == 'adding_question_to_bank' and
            'question_bank_data' in context.user_data and
            context.user_data['question_bank_data'].get('step') == 'waiting_for_answer'):
            
            try:
                correct_answer = int(text)
                if correct_answer < 1 or correct_answer > 4:
                    raise ValueError("Answer out of range")
                
                question_data = context.user_data['question_bank_data']
                
                # ذخیره سوال در بانک
                result = add_question_to_bank(
                    question_data['topic_id'],
                    question_data.get('resource_id'),  # می‌تواند None باشد
                    question_data['question_image'],
                    correct_answer
                )
                
                if result:
                    topic_name = question_data.get('topic_name', 'نامشخص')
                    resource_name = question_data.get('resource_name', 'ندارد')
                    
                    success_message = (
                        f"✅ سوال با موفقیت به بانک اضافه شد!\n\n"
                        f"📚 مبحث: {topic_name}\n"
                        f"📖 منبع: {resource_name}\n"
                        f"📸 عکس: {os.path.basename(question_data['question_image'])}\n"
                        f"✅ پاسخ صحیح: گزینه {correct_answer}"
                    )
                    
                    await update.message.reply_text(success_message)
                else:
                    await update.message.reply_text("❌ خطا در ذخیره سوال!")
                
                # پاک کردن داده‌های موقت
                context.user_data.pop('question_bank_data', None)
                context.user_data.pop('admin_action', None)
                
            except ValueError:
                await update.message.reply_text("❌ لطفاً عددی بین 1 تا 4 وارد کنید:")
            except Exception as e:
                logger.error(f"Error adding question to bank: {e}")
                await update.message.reply_text("❌ خطا در ذخیره سوال!")
            return

        # 1.5 پردازش ویرایش نام مبحث
        if ('editing_topic' in context.user_data and
            context.user_data['editing_topic'].get('step') == 'waiting_for_new_name'):
            
            await process_topic_name_edit(update, context)
            return

        # 1.6 پردازش ویرایش توضیحات مبحث
        if ('editing_topic' in context.user_data and
            context.user_data['editing_topic'].get('step') == 'waiting_for_new_description'):
            
            await process_topic_description_edit(update, context)
            return

        # 1.7 پردازش افزودن مبحث جدید
        if context.user_data.get('admin_action') == 'adding_topic':
            topic_data = context.user_data.get('topic_data', {})
            
            if topic_data.get('step') == 'name':
                topic_data['name'] = text
                topic_data['step'] = 'description'
                context.user_data['topic_data'] = topic_data
                
                await update.message.reply_text(
                    "✅ نام مبحث ذخیره شد.\n\n"
                    "لطفاً توضیحات مبحث را ارسال کنید (اختیاری):\n\n"
                    "💡 می‌توانید 'ندارد' را ارسال کنید تا از توضیحات صرف نظر کنید."
                )
                return
            
            elif topic_data.get('step') == 'description':
                description = text if text != 'ندارد' else ""
                
                result = add_topic(topic_data['name'], description)
                
                if result:
                    await update.message.reply_text(
                        f"✅ مبحث '{topic_data['name']}' با موفقیت اضافه شد!"
                    )
                else:
                    await update.message.reply_text(
                        "❌ خطا در افزودن مبحث! ممکن است مبحثی با این نام از قبل وجود داشته باشد."
                    )
                
                context.user_data.pop('topic_data', None)
                context.user_data.pop('admin_action', None)
                return

        # 1.8 پردازش عنوان آزمون ادمین
        if ('admin_quiz' in context.user_data and
            context.user_data['admin_quiz'].get('step') == 'waiting_for_title'):
            
            await process_admin_title_input(update, context)
            return

        # 1.9 پردازش توضیحات آزمون ادمین
        if ('admin_quiz' in context.user_data and
            context.user_data['admin_quiz'].get('step') == 'waiting_for_description'):
            
            await process_admin_description_input(update, context)
            return

        # 1.10 پردازش تعداد سوالات آزمون ادمین
        if ('admin_quiz' in context.user_data and
            context.user_data['admin_quiz'].get('step') == 'waiting_for_count'):
            
            await process_admin_question_count_input(update, context)
            return

        # 1.11 پردازش زمان آزمون ادمین
        if ('admin_quiz' in context.user_data and
            context.user_data['admin_quiz'].get('step') == 'waiting_for_time'):
            
            await process_admin_time_limit_input(update, context)
            return

        # 1.12 پردازش انتخاب مبحث برای آزمون ادمین
        # در تابع handle_message، بخش پردازش انتخاب مبحث برای آزمون ادمین:

# 1.12 پردازش انتخاب مبحث برای آزمون ادمین
        if (text.startswith('مبحث انتخاب شده:') and
            'admin_quiz' in context.user_data):
    
            quiz_data = context.user_data['admin_quiz']
            mode = quiz_data.get('mode', 'topics')
    
            if quiz_data['step'] == 'select_first_topic':
               if mode in ['topics', 'both']:
                  await admin_handle_first_topic_selection(update, context)
                  return
            elif quiz_data['step'] == 'adding_more_topics':
              if mode in ['topics', 'both']:
                   await admin_handle_additional_topic_selection(update, context)
                   return
        # 1.13 پردازش انتخاب منبع برای آزمون ادمین
        if (text.startswith('منبع انتخاب شده:') and
            'admin_quiz' in context.user_data):
            
            quiz_data = context.user_data['admin_quiz']
            
            if quiz_data.get('mode') == 'both' and quiz_data['step'] == 'select_first_resource':
                await admin_handle_first_resource_selection(update, context)
                return
            elif quiz_data.get('mode') == 'both' and quiz_data['step'] == 'adding_more_resources':
                await admin_handle_additional_resource_selection(update, context)
                return
        # 1.15 پردازش انتخاب منبع اول برای آزمون ادمین
        if (text.startswith('منبع انتخاب شده:') and
            'admin_quiz' in context.user_data and
            context.user_data['admin_quiz'].get('mode') == 'resources' and
            context.user_data['admin_quiz'].get('step') == 'select_first_resource'):
    
            await admin_handle_first_resource_selection(update, context)
            return

        # 1.14 پردازش پیام همگانی
        # در تابع handle_message، بخش پردازش پیام‌های ادمین، این بخش را اضافه کنید:

# 1.14 پردازش پیام همگانی (تغییر یافته)
        if context.user_data.get('admin_action') == 'broadcasting':
    # بررسی اینکه آیا پیام حاوی محتوای قابل ارسال است
           if (update.message.text or 
               update.message.photo or 
               update.message.poll or 
               update.message.video or 
               update.message.document or 
               update.message.audio or 
               update.message.voice):
               await handle_broadcast(update, context)
           else:
               await update.message.reply_text("❌ محتوای نامعتبر! لطفاً متن، عکس، نظرسنجی یا فایل ارسال کنید.")
           return
    # ===== اولویت 2: پردازش کاربران عادی =====
    
    # 2.1 پردازش انتخاب مبحث برای آزمون سفارشی
    if (text.startswith('مبحث انتخاب شده:') and
        'custom_quiz' in context.user_data):
        
        quiz_data = context.user_data['custom_quiz']
        
        if quiz_data['step'] == 'select_first_topic':
            await handle_first_topic_selection_from_message(update, context)
            return
        elif quiz_data['step'] == 'adding_more_topics':
            await handle_additional_topic_selection(update, context)
            return

    # 2.2 پردازش انتخاب منبع برای آزمون سفارشی
    if (text.startswith('منبع انتخاب شده:') and
        'custom_quiz' in context.user_data):
        
        quiz_data = context.user_data['custom_quiz']
        
        if quiz_data.get('mode') == 'resources':
            if quiz_data['step'] == 'select_first_resource':
                await handle_first_resource_selection(update, context)
                return
            elif quiz_data['step'] == 'adding_more_resources':
                await handle_additional_resource_selection(update, context)
                return

    # 2.3 پردازش تعداد سوالات آزمون سفارشی
    if ('custom_quiz' in context.user_data and
        context.user_data['custom_quiz'].get('step') == 'waiting_for_count'):
        
        await process_question_count_input(update, context)
        return

    # 2.4 پردازش زمان آزمون سفارشی
    if ('custom_quiz' in context.user_data and
        context.user_data['custom_quiz'].get('step') == 'waiting_for_time'):
        
        await process_time_limit_input(update, context)
        return

    # ===== پردازش پیشفرض =====
    
    # برای ادمین: نمایش پیام راهنما
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "🔧 دستور نامعتبر!\n\n"
            "لطفاً از منوی ادمین استفاده کنید یا دستور معتبری ارسال کنید."
        )
        return
    
    # برای کاربران عادی
    await update.message.reply_text(
        "لطفاً از منوی ربات استفاده کنید.\n\n"
        "برای شروع می‌توانید از دستور /start استفاده کنید."
           )

async def handle_topic_selection_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب مبحث از طریق پیام"""
    try:
        text = update.message.text
        logger.info(f"🎯 TOPIC_SELECTION: Processing topic selection: {text}")
        
        # استخراج نام مبحث از متن
        topic_name = text.replace("مبحث انتخاب شده:", "").strip()
        
        # پیدا کردن مبحث در دیتابیس
        topic_info = get_topic_by_name(topic_name)
        if not topic_info:
            logger.error(f"❌ TOPIC_SELECTION: Topic not found: {topic_name}")
            await update.message.reply_text(
                f"❌ مبحث '{topic_name}' یافت نشد! لطفاً دوباره تلاش کنید."
            )
            return
        
        topic_id, name, description, is_active = topic_info[0]
        logger.info(f"✅ TOPIC_SELECTION: Found topic - ID: {topic_id}, Name: {name}")
        
        # به‌روزرسانی context
        context.user_data['question_bank_data'] = {
            'topic_id': topic_id,
            'topic_name': name,
            'step': 'waiting_for_photo'
        }
        context.user_data['admin_action'] = 'adding_question_to_bank'
        
        logger.info(f"✅ TOPIC_SELECTION: Context updated: {context.user_data['question_bank_data']}")
        
        await update.message.reply_text(
            f"✅ مبحث انتخاب شد: **{name}**\n\n"
            f"**مرحله ۲/۳: ارسال عکس سوال**\n\n"
            f"📸 لطفاً عکس سوال را ارسال کنید:",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"❌ TOPIC_SELECTION: Error: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث! لطفاً دوباره تلاش کنید.")

async def debug_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تابع دیباگ برای بررسی وضعیت context"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    context_info = {
        'user_data_keys': list(context.user_data.keys()),
        'user_data_values': {key: str(context.user_data[key]) for key in context.user_data.keys()}
    }
    
    debug_text = f"🔍 دیباگ Context:\n```{context_info}```"
    
    await context.bot.send_message(
        chat_id=user_id,
        text=debug_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def custom_quiz_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنظیمات آزمون سفارشی"""
    if 'custom_quiz' not in context.user_data:
        context.user_data['custom_quiz'] = {
            'selected_topics': [],
            'settings': {
                'count': 20,
                'time_limit': 30,
                'difficulty': 'all'
            }
        }
    
    context.user_data['custom_quiz']['step'] = 'settings'
    settings = context.user_data['custom_quiz']['settings']
    
    # محاسبه حداکثر سوالات قابل دسترس
    total_available = 0
    if context.user_data['custom_quiz']['selected_topics']:
        total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in context.user_data['custom_quiz']['selected_topics']])
    
    count = settings.get('count', 20)
    time_limit = settings.get('time_limit', 30)
    difficulty = settings.get('difficulty', 'all')
    
    # نمایش نام مباحث انتخاب شده
    topics_text = ""
    if context.user_data['custom_quiz']['selected_topics']:
        topics_list = [f"• {get_topic_name(tid)}" for tid in context.user_data['custom_quiz']['selected_topics']]
        topics_text = "\n".join(topics_list) + "\n\n"
    
    keyboard = [
        [InlineKeyboardButton(f"📊 تعداد سوالات: {count}", callback_data="set_count_menu")],
        [InlineKeyboardButton(f"⏱ زمان: {time_limit} دقیقه", callback_data="set_time_menu")],
        [InlineKeyboardButton(f"🎯 سطح: {difficulty}", callback_data="set_difficulty_menu")],
        [InlineKeyboardButton("➕ افزودن مبحث دیگر", switch_inline_query_current_chat="مبحث ")],
        [InlineKeyboardButton("🚀 شروع آزمون", callback_data="generate_custom_quiz")],
        [InlineKeyboardButton("🔙 بازگشت به آزمون سفارشی", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"🎯 تنظیمات آزمون سفارشی\n\n"
        f"📚 مباحث انتخاب شده:\n{topics_text}"
        f"📊 سوالات قابل دسترس: {total_available}\n\n"
        f"⚙️ تنظیمات فعلی:\n"
        f"• تعداد سوالات: {count}\n"
        f"• زمان: {time_limit} دقیقه\n"
        f"• سطح: {difficulty}\n\n"
        f"لطفاً تنظیمات مورد نظر را انتخاب کنید:"
    )
    
    await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)

# در تابع generate_custom_quiz (حدود خط 1800) این تغییرات را انجام دهید:
async def generate_custom_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد و شروع آزمون سفارشی"""
    try:
        user_id = update.effective_user.id
        
        if 'custom_quiz' not in context.user_data:
            await update.callback_query.edit_message_text(
                "❌ خطا در داده‌های آزمون!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]])
            )
            return
        
        quiz_data = context.user_data['custom_quiz']
        mode = quiz_data.get('mode', 'topics')
        
        # اعتبارسنجی بر اساس حالت انتخاب شده
        if mode == 'topics' and not quiz_data['selected_topics']:
            await update.callback_query.edit_message_text(
                "❌ لطفاً حداقل یک مبحث انتخاب کنید!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]])
            )
            return
        elif mode == 'resources' and not quiz_data['selected_resources']:
            await update.callback_query.edit_message_text(
                "❌ لطفاً حداقل یک منبع انتخاب کنید!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]])
            )
            return
        
        # دریافت سوالات بر اساس حالت
        questions = []
        total_available = 0
        
        if mode == 'topics':
            questions = get_questions_by_topics(
                quiz_data['selected_topics'],
                quiz_data['settings'].get('difficulty', 'all'),
                quiz_data['settings'].get('count', 20)
            )
            # محاسبه سوالات قابل دسترس
            for topic_id in quiz_data['selected_topics']:
                count_result = get_questions_count_by_topic(topic_id)
                total_available += count_result[0][0] if count_result else 0
                
        elif mode == 'resources':
            questions = get_questions_by_resources(
                quiz_data['selected_resources'],
                quiz_data['settings'].get('difficulty', 'all'),
                quiz_data['settings'].get('count', 20)
            )
            # محاسبه سوالات قابل دسترس
            for resource_id in quiz_data['selected_resources']:
                count_result = get_questions_count_by_resource(resource_id)
                total_available += count_result[0][0] if count_result else 0
        
        if not questions:
            await update.callback_query.edit_message_text(
                f"❌ هیچ سوالی برای انتخاب‌های شما یافت نشد!\n\nسوالات قابل دسترس: {total_available}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]])
            )
            return
        
        # اگر تعداد سوالات کمتر از تعداد درخواستی باشد
        if len(questions) < quiz_data['settings']['count']:
            await update.callback_query.answer(
                f"⚠️ فقط {len(questions)} سوال از {quiz_data['settings']['count']} سوال درخواستی موجود بود!",
                show_alert=True
            )
        
        # ایجاد آزمون موقت
        if mode == 'topics':
            topics_names = [get_topic_name(tid) for tid in quiz_data['selected_topics']]
            quiz_title = f"آزمون سفارشی - {', '.join(topics_names)[:50]}..."
            quiz_description = f"آزمون سفارشی شامل {len(questions)} سوال از {len(topics_names)} مبحث"
        else:
            resource_names = [get_resource_name(rid) for rid in quiz_data['selected_resources']]
            quiz_title = f"آزمون سفارشی - {', '.join(resource_names)[:50]}..."
            quiz_description = f"آزمون سفارشی شامل {len(questions)} سوال از {len(resource_names)} منبع"
        
        quiz_id = create_quiz(quiz_title, quiz_description, quiz_data['settings'].get('time_limit', 30), False)
        
        if not quiz_id:
            await update.callback_query.edit_message_text(
                "❌ خطا در ایجاد آزمون!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]])
            )
            return
        
        # افزودن سوالات به آزمون
        for i, question in enumerate(questions):
            add_question(quiz_id, question[1], question[2], i)
        
        # پاک کردن داده‌های موقت
        if 'custom_quiz' in context.user_data:
            del context.user_data['custom_quiz']
        
        # شروع آزمون
        await start_quiz(update, context, quiz_id)
        
    except Exception as e:
        logger.error(f"Error generating custom quiz: {e}")
        await update.callback_query.edit_message_text(
            "❌ خطا در ایجاد آزمون! لطفاً دوباره تلاش کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]])
        )

# توابع آزمون
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
    
    # ایجاد کیبورد با تیک‌ها
    keyboard = []
    for i in range(1, 5):
        check = "✅ " if selected == i else ""
        keyboard.append([InlineKeyboardButton(f"{check}گزینه {i}", callback_data=f"ans_{quiz_data['quiz_id']}_{current_index}_{i}")])
    
    # دکمه علامت‌گذاری
    marked = context.user_data.get('marked_questions', set())
    mark_text = "✅ علامت گذاری شده" if current_index in marked else "🏷 علامت‌گذاری"
    keyboard.append([InlineKeyboardButton(mark_text, callback_data=f"mark_{quiz_data['quiz_id']}_{current_index}")])
    
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
            keyboard.append([InlineKeyboardButton(f"🔄 مرور سوالات علامت‌گذاری شده ({marked_count})", callback_data=f"review_marked")])
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
    
    correct_questions = []
    wrong_questions = []
    unanswered_questions_list = []
    
    result_details = "📊 جزئیات پاسخ‌ها:\n\n"
    
    # محاسبه نتایج و به‌روزرسانی سطح سختی
    for i, question in enumerate(quiz_data['questions']):
        question_id, question_image, correct_answer = question
        user_answer = user_answers_dict.get(question_id)
        
        # محاسبه زمان صرف شده برای این سوال (تقریبی)
        time_per_question = total_time / total_questions if total_questions > 0 else 0
        
        if user_answer is None:
            unanswered_questions += 1
            unanswered_questions_list.append(i + 1)
            result_details += f"⏸️ سوال {i+1}: بی‌پاسخ\n"
            # به‌روزرسانی سطح سختی برای سوالات بی‌پاسخ
            DifficultyAnalyzer.update_question_difficulty(question_id, False, time_per_question)
        elif user_answer == correct_answer:
            score += 1
            correct_answers += 1
            correct_questions.append(i + 1)
            result_details += f"✅ سوال {i+1}: صحیح\n"
            DifficultyAnalyzer.update_question_difficulty(question_id, True, time_per_question)
        else:
            wrong_answers += 1
            wrong_questions.append(i + 1)
            user_answer_text = user_answer if user_answer else "پاسخی داده نشد"
            result_details += f"❌ سوال {i+1}: غلط (پاسخ شما: {user_answer_text}, پاسخ صحیح: {correct_answer})\n"
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
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n\n"
    )
    
    # اضافه کردن شماره سوالات به پیام کاربر
    if correct_questions:
        user_message += f"🔢 سوالات صحیح: {', '.join(map(str, correct_questions))}\n"
    if wrong_questions:
        user_message += f"🔢 سوالات غلط: {', '.join(map(str, wrong_questions))}\n"
    if unanswered_questions_list:
        user_message += f"🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions_list))}\n"
    
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
    await send_results_to_admin(context, user_id, quiz_id, final_percentage, total_time, correct_answers, wrong_answers, unanswered_questions, result_details)
    
    # پاک کردن داده‌های موقت
    if 'current_quiz' in context.user_data:
        del context.user_data['current_quiz']
    if 'marked_questions' in context.user_data:
        del context.user_data['marked_questions']
    if 'review_mode' in context.user_data:
        del context.user_data['review_mode']

async def send_results_to_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int, quiz_id: int, score: float, total_time: int, correct: int, wrong: int, unanswered: int, result_details: str = ""):
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
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n\n"
        f"{result_details}"
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
        [InlineKeyboardButton("📖 مدیریت منابع", callback_data="admin_manage_resources")],
        [InlineKeyboardButton("❓ افزودن سوال به بانک", callback_data="admin_add_question")],
        [InlineKeyboardButton("🏆 مشاهده رتبه‌بندی", callback_data="admin_quiz_rankings")],
        [InlineKeyboardButton("👥 مشاهده کاربران", callback_data="admin_view_users")],
        [InlineKeyboardButton("📊 مشاهده نتایج", callback_data="admin_view_results")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("🔧 پنل مدیریت ادمین:", reply_markup=reply_markup)

async def admin_quiz_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    quizzes = execute_query("SELECT id, title FROM quizzes WHERE created_by_admin = TRUE ORDER BY created_at DESC")
    
    if not quizzes:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("⚠️ هیچ آزمون ادمینی یافت نشد.", reply_markup=reply_markup)
        return
    
    keyboard = []
    for quiz_id, title in quizzes:
        keyboard.append([InlineKeyboardButton(f"📊 {title}", callback_data=f"quiz_ranking_{quiz_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text("🏆 انتخاب آزمون برای مشاهده رتبه‌بندی:", reply_markup=reply_markup)


async def show_quiz_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """دریافت و نمایش رتبه‌بندی کامل یک آزمون با جزئیات بیشتر"""
    # دریافت اطلاعات آزمون
    quiz_info = get_quiz_info(quiz_id)
    if not quiz_info:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به رتبه‌بندی", callback_data="admin_quiz_rankings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("⚠️ آزمون یافت نشد.", reply_markup=reply_markup)
        return
    
    quiz_title, description, time_limit, is_active, created_by_admin = quiz_info
    
    # دریافت رتبه‌بندی
    rankings = get_quiz_rankings(quiz_id)
    
    if not rankings:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به رتبه‌بندی", callback_data="admin_quiz_rankings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("⚠️ هیچ نتیجه‌ای برای این آزمون یافت نشد.", reply_markup=reply_markup)
        return
    
    # آمار کلی آزمون
    total_participants = len(rankings)
    avg_score = sum(rank[1] for rank in rankings) / total_participants if total_participants > 0 else 0
    best_score = max(rank[1] for rank in rankings) if rankings else 0
    
    text = f"🏆 رتبه‌بندی آزمون: **{quiz_title}**\n\n"
    text += f"📊 آمار کلی:\n"
    text += f"• 👥 تعداد شرکت‌کنندگان: {total_participants}\n"
    text += f"• 📈 میانگین نمره: {avg_score:.1f}%\n"
    text += f"• 🎖️ بهترین نمره: {best_score:.1f}%\n"
    text += f"• ⏱ زمان آزمون: {time_limit} دقیقه\n\n"
    
    text += "📋 رتبه‌بندی شرکت‌کنندگان:\n\n"
    
    # نمایش 15 رتبه اول
    for i, rank in enumerate(rankings[:15]):
        full_name, score, correct_answers, total_time, user_rank = rank
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        
        # کوتاه کردن نام اگر طولانی باشد
        display_name = full_name[:20] + "..." if len(full_name) > 20 else full_name
        
        text += f"{user_rank}. **{display_name}**\n"
        text += f"   📈 {score:.1f}% | ✅ {correct_answers} | ⏱ {time_str}\n\n"
    
    if len(rankings) > 15:
        text += f"📊 و {len(rankings) - 15} شرکت‌کننده دیگر...\n\n"
    
    keyboard = [
        [InlineKeyboardButton("📊 مشاهده جزئیات کامل", callback_data=f"full_ranking_{quiz_id}")],
        [InlineKeyboardButton("🔙 بازگشت به رتبه‌بندی", callback_data="admin_quiz_rankings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
# توابع مدیریت ادمین

async def admin_create_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ایجاد آزمون جدید با انتخاب مبحث و منبع"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    # پاک کردن contextهای قبلی
    clear_admin_context(context)
    
    context.user_data['admin_quiz'] = {
        'step': 'select_mode',
        'selected_topics': [],
        'selected_resources': [],
        'settings': {
            'title': '',
            'description': '',
            'count': 20,
            'time_limit': 30,
            'difficulty': 'all'
        },
        'quiz_type': 'admin'
    }
    
    keyboard = [
        [InlineKeyboardButton("📚 انتخاب از مباحث", callback_data="admin_select_topics_mode")],
        [InlineKeyboardButton("📖 انتخاب از منابع", callback_data="admin_select_resources_mode")],
        [InlineKeyboardButton("📚📖 انتخاب از مباحث و منابع", callback_data="admin_select_both_mode")],
        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 ایجاد آزمون جدید (ادمین)\n\n"
        "لطفاً نوع انتخاب سوالات را مشخص کنید:\n\n"
        "• 📚 **انتخاب از مباحث**: سوالات بر اساس موضوع درسی\n"
        "• 📖 **انتخاب از منابع**: سوالات بر اساس کتاب‌های درسی\n"
        "• 📚📖 **انتخاب از مباحث و منابع**: ترکیبی از هر دو",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
async def admin_select_topics_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالت انتخاب از مباحث برای آزمون ادمین"""
    context.user_data['admin_quiz']['mode'] = 'topics'
    context.user_data['admin_quiz']['step'] = 'select_first_topic'
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب مبحث اول", switch_inline_query_current_chat="مبحث ")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_create_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚 حالت: انتخاب از مباحث\n\n"
        "مرحله ۱/۵: انتخاب مبحث اول\n\n"
        "روی دکمه زیر کلیک کنید و مبحث اول را انتخاب کنید:",
        reply_markup=reply_markup
    )
# بعد از تابع show_initial_settings_from_callback (حدود خط 1700) این تابع را اضافه کنید:

async def show_initial_settings_for_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تنظیمات اولیه بعد از انتخاب منبع اول"""
    quiz_data = context.user_data['custom_quiz']
    settings = quiz_data['settings']
    first_resource_name = quiz_data.get('first_resource_name', 'نامشخص')
    
    # محاسبه سوالات قابل دسترس برای منبع اول
    available_questions = get_questions_count_by_resource(quiz_data['selected_resources'][0])[0][0]
    
    # متن نمایشی برای سطح سختی
    difficulty_texts = {
        'all': '🎯 همه سطوح',
        'easy': '🟢 آسان', 
        'medium': '🟡 متوسط',
        'hard': '🔴 سخت'
    }
    difficulty_text = difficulty_texts.get(settings['difficulty'], '🎯 همه سطوح')
    
    keyboard = [
        [InlineKeyboardButton(f"📊 تعداد سوالات: {settings['count']}", callback_data="initial_set_count")],
        [InlineKeyboardButton(f"🎯 سطح سختی: {difficulty_text}", callback_data="initial_set_difficulty")],
        [InlineKeyboardButton(f"⏱ زمان: {settings['time_limit']} دقیقه", callback_data="initial_set_time")],
        [InlineKeyboardButton("➕ افزودن منبع دیگر", callback_data="add_more_resources")],
        [InlineKeyboardButton("🚀 ساخت و شروع آزمون", callback_data="generate_custom_quiz")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"✅ منبع اول انتخاب شد: **{first_resource_name}**\n\n"
        f"📊 سوالات قابل دسترس: {available_questions}\n\n"
        f"⚙️ تنظیمات آزمون:\n"
        f"• تعداد سوالات: {settings['count']}\n" 
        f"• سطح سختی: {difficulty_text}\n"
        f"• زمان: {settings['time_limit']} دقیقه\n\n"
        f"می‌توانید:\n"
        f"• تنظیمات را تغییر دهید\n"
        f"• منابع بیشتری اضافه کنید\n" 
        f"• یا آزمون را شروع کنید"
    )
    
    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def add_more_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن منابع بیشتر"""
    context.user_data['custom_quiz']['step'] = 'adding_more_resources'
    
    # نمایش منابع انتخاب شده فعلی
    resources_text = "\n".join([
        f"• {get_resource_name(rid)}"
        for rid in context.user_data['custom_quiz']['selected_resources']
    ])
    
    keyboard = [
        [InlineKeyboardButton("🔍 افزودن منبع جدید", switch_inline_query_current_chat="منبع ")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="back_to_initial_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📖 افزودن منابع بیشتر\n\n"
        f"منابع انتخاب شده فعلی:\n{resources_text}\n\n"
        f"روی دکمه زیر کلیک کنید تا منبع جدیدی اضافه کنید:",
        reply_markup=reply_markup
    )

async def handle_additional_resource_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب منابع اضافی"""
    try:
        text = update.message.text
        resource_name = text.replace("منبع انتخاب شده:", "").strip()
        
        resource_info = get_resource_by_name(resource_name)
        if not resource_info:
            await update.message.reply_text(f"❌ منبع '{resource_name}' یافت نشد!")
            return
        
        resource_id, name, description, is_active = resource_info[0]
        
        # بررسی تکراری نبودن منبع
        if resource_id in context.user_data['custom_quiz']['selected_resources']:
            await update.message.reply_text(f"❌ منبع '{name}' قبلاً اضافه شده است!")
            return
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_resource(resource_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای منبع '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن منبع به لیست
        context.user_data['custom_quiz']['selected_resources'].append(resource_id)
        
        # بازگشت به تنظیمات
        context.user_data['custom_quiz']['step'] = 'settings'
        await show_initial_settings_from_message_for_resources(update, context)
        
    except Exception as e:
        logger.error(f"Error in additional resource selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب منبع!")

async def show_initial_settings_from_message_for_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تنظیمات اولیه برای منابع از پیام"""
    quiz_data = context.user_data['custom_quiz']
    settings = quiz_data['settings']
    
    # محاسبه کل سوالات قابل دسترس
    total_available = sum([get_questions_count_by_resource(rid)[0][0] for rid in quiz_data['selected_resources']])
    
    # نمایش نام منابع انتخاب شده
    resources_text = "\n".join([f"• {get_resource_name(rid)}" for rid in quiz_data['selected_resources']])
    
    # متن نمایشی برای سطح سختی
    difficulty_texts = {
        'all': '🎯 همه سطوح',
        'easy': '🟢 آسان',
        'medium': '🟡 متوسط', 
        'hard': '🔴 سخت'
    }
    difficulty_text = difficulty_texts.get(settings['difficulty'], '🎯 همه سطوح')
    
    keyboard = [
        [InlineKeyboardButton(f"📊 تعداد سوالات: {settings['count']}", callback_data="ask_question_count")],
        [InlineKeyboardButton(f"🎯 سطح سختی: {difficulty_text}", callback_data="initial_set_difficulty")],
        [InlineKeyboardButton(f"⏱ زمان: {settings['time_limit']} دقیقه", callback_data="ask_time_limit")],
        [InlineKeyboardButton("➕ افزودن منبع دیگر", callback_data="add_more_resources")],
        [InlineKeyboardButton("🚀 ساخت و شروع آزمون", callback_data="generate_custom_quiz")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"🎯 تنظیمات آزمون سفارشی (منابع)\n\n"
        f"📖 منابع انتخاب شده:\n{resources_text}\n\n"
        f"📊 سوالات قابل دسترس: {total_available}\n\n"
        f"⚙️ تنظیمات فعلی:\n"
        f"• تعداد سوالات: {settings['count']}\n"
        f"• سطح سختی: {difficulty_text}\n"
        f"• زمان: {settings['time_limit']} دقیقه\n\n"
        f"برای تغییر هر مورد، روی آن کلیک کنید:"
    )
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)
async def admin_handle_first_resource_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب منبع اول برای آزمون ادمین"""
    try:
        text = update.message.text
        resource_name = text.replace("منبع انتخاب شده:", "").strip()
        
        resource_info = get_resource_by_name(resource_name)
        if not resource_info:
            await update.message.reply_text(f"❌ منبع '{resource_name}' یافت نشد!")
            return
        
        resource_id, name, description, is_active = resource_info[0]
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_resource(resource_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای منبع '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن منبع به لیست
        context.user_data['admin_quiz']['selected_resources'].append(resource_id)
        context.user_data['admin_quiz']['step'] = 'waiting_for_title'
        context.user_data['admin_quiz']['first_resource_name'] = name
        
        # درخواست عنوان آزمون
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_to_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ منبع اول انتخاب شد: **{name}**\n\n"
            f"📊 سوالات قابل دسترس: {available_questions}\n\n"
            f"**مرحله ۲/۵: تعیین عنوان آزمون**\n\n"
            f"لطفاً عنوان آزمون را وارد کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in admin first resource selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب منبع!")

async def admin_handle_additional_resource_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب منابع اضافی برای آزمون ادمین"""
    try:
        text = update.message.text
        resource_name = text.replace("منبع انتخاب شده:", "").strip()
        
        resource_info = get_resource_by_name(resource_name)
        if not resource_info:
            await update.message.reply_text(f"❌ منبع '{resource_name}' یافت نشد!")
            return
        
        resource_id, name, description, is_active = resource_info[0]
        
        # بررسی تکراری نبودن منبع
        if resource_id in context.user_data['admin_quiz']['selected_resources']:
            await update.message.reply_text(f"❌ منبع '{name}' قبلاً اضافه شده است!")
            return
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_resource(resource_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای منبع '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن منبع به لیست
        context.user_data['admin_quiz']['selected_resources'].append(resource_id)
        
        # بازگشت به تنظیمات
        context.user_data['admin_quiz']['step'] = 'settings'
        await admin_show_settings(update, context)
        
    except Exception as e:
        logger.error(f"Error in admin additional resource selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب منبع!")

async def admin_select_resources_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالت انتخاب از منابع برای آزمون ادمین"""
    context.user_data['admin_quiz']['mode'] = 'resources'
    context.user_data['admin_quiz']['step'] = 'select_first_resource'  # این خط مهم است
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب منبع اول", switch_inline_query_current_chat="منبع ")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_create_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📖 حالت: انتخاب از منابع\n\n"
        "مرحله ۱/۵: انتخاب منبع اول\n\n"
        "روی دکمه زیر کلیک کنید و منبع اول را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def admin_select_both_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالت انتخاب از مباحث و منابع برای آزمون ادمین"""
    context.user_data['admin_quiz']['mode'] = 'both'
    context.user_data['admin_quiz']['step'] = 'select_first_topic'
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب مبحث اول", switch_inline_query_current_chat="مبحث ")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_create_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚📖 حالت: انتخاب از مباحث و منابع\n\n"
        "مرحله ۱/۶: انتخاب مبحث اول\n\n"
        "ابتدا مباحث مورد نظر را انتخاب کنید، سپس منابع را انتخاب خواهید کرد.\n\n"
        "روی دکمه زیر کلیک کنید و مبحث اول را انتخاب کنید:",
        reply_markup=reply_markup
    )
async def admin_handle_first_topic_selection_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب مبحث اول برای آزمون ادمین از طریق پیام"""
    try:
        text = update.message.text
        topic_name = text.replace("مبحث انتخاب شده:", "").strip()
        
        topic_info = get_topic_by_name(topic_name)
        if not topic_info:
            await update.message.reply_text(f"❌ مبحث '{topic_name}' یافت نشد!")
            return
        
        topic_id, name, description, is_active = topic_info[0]
        await admin_handle_first_topic_selection(update, context, topic_id)
        
    except Exception as e:
        logger.error(f"Error in admin first topic selection from message: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")

async def admin_handle_additional_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب مباحث اضافی برای آزمون ادمین"""
    try:
        text = update.message.text
        topic_name = text.replace("مبحث انتخاب شده:", "").strip()
        
        topic_info = get_topic_by_name(topic_name)
        if not topic_info:
            await update.message.reply_text(f"❌ مبحث '{topic_name}' یافت نشد!")
            return
        
        topic_id, name, description = topic_info[0]
        
        # بررسی تکراری نبودن مبحث
        if topic_id in context.user_data['admin_quiz']['selected_topics']:
            await update.message.reply_text(f"❌ مبحث '{name}' قبلاً اضافه شده است!")
            return
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_topic(topic_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای مبحث '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن مبحث به لیست
        context.user_data['admin_quiz']['selected_topics'].append(topic_id)
        
        # بازگشت به تنظیمات
        context.user_data['admin_quiz']['step'] = 'settings'
        await admin_show_settings(update, context)
        
    except Exception as e:
        logger.error(f"Error in admin additional topic selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")
async def admin_handle_first_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """مدیریت انتخاب مبحث اول برای آزمون ادمین"""
    try:
        # دریافت اطلاعات مبحث
        topic_info = get_topic_by_id(topic_id)
        if not topic_info:
            await update.message.reply_text("❌ مبحث یافت نشد!")
            return
        
        topic_id, name, description, is_active = topic_info[0]
        
        # بررسی تعداد سوالات موجود
        questions_count = get_questions_count_by_topic(topic_id)
        available_questions = questions_count[0][0] if questions_count else 0
        
        if available_questions == 0:
            await update.message.reply_text(f"❌ هیچ سوالی برای مبحث '{name}' در بانک وجود ندارد!")
            return
        
        # افزودن مبحث به لیست
        context.user_data['admin_quiz']['selected_topics'].append(topic_id)
        context.user_data['admin_quiz']['step'] = 'waiting_for_title'
        context.user_data['admin_quiz']['first_topic_name'] = name
        
        # درخواست عنوان آزمون
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_to_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ مبحث اول انتخاب شد: **{name}**\n\n"
            f"📊 سوالات قابل دسترس: {available_questions}\n\n"
            f"**مرحله ۲/۵: تعیین عنوان آزمون**\n\n"
            f"لطفاً عنوان آزمون را وارد کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in admin first topic selection: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")

async def admin_show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تنظیمات آزمون ادمین"""
    quiz_data = context.user_data['admin_quiz']
    settings = quiz_data['settings']
    
    # محاسبه کل سوالات قابل دسترس
    total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in quiz_data['selected_topics']])
    
    # نمایش نام مباحث انتخاب شده
    topics_text = "\n".join([f"• {get_topic_name(tid)}" for tid in quiz_data['selected_topics']])
    
    # متن نمایشی برای سطح سختی
    difficulty_texts = {
        'all': '🎯 همه سطوح',
        'easy': '🟢 آسان',
        'medium': '🟡 متوسط', 
        'hard': '🔴 سخت'
    }
    difficulty_text = difficulty_texts.get(settings['difficulty'], '🎯 همه سطوح')
    
    keyboard = [
        [InlineKeyboardButton(f"📝 عنوان: {settings['title'] or 'تعیین نشده'}", callback_data="admin_ask_title")],
        [InlineKeyboardButton(f"📋 توضیحات: {settings['description'] or 'تعیین نشده'}", callback_data="admin_ask_description")],
        [InlineKeyboardButton(f"📊 تعداد سوالات: {settings['count']}", callback_data="admin_ask_question_count")],
        [InlineKeyboardButton(f"🎯 سطح سختی: {difficulty_text}", callback_data="admin_set_difficulty")],
        [InlineKeyboardButton(f"⏱ زمان: {settings['time_limit']} دقیقه", callback_data="admin_ask_time_limit")],
        [InlineKeyboardButton("➕ افزودن مبحث دیگر", callback_data="admin_add_more_topics")],
        [InlineKeyboardButton("🚀 ساخت آزمون", callback_data="admin_generate_quiz")],
        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"🎯 تنظیمات آزمون ادمین\n\n"
        f"📚 مباحث انتخاب شده:\n{topics_text}\n\n"
        f"📊 سوالات قابل دسترس: {total_available}\n\n"
        f"⚙️ تنظیمات فعلی:\n"
        f"• عنوان: {settings['title'] or '❌ تعیین نشده'}\n"
        f"• توضیحات: {settings['description'] or '❌ تعیین نشده'}\n"
        f"• تعداد سوالات: {settings['count']}\n"
        f"• سطح سختی: {difficulty_text}\n"
        f"• زمان: {settings['time_limit']} دقیقه\n\n"
        f"برای تغییر هر مورد، روی آن کلیک کنید:"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
async def admin_ask_for_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست عنوان آزمون از ادمین"""
    context.user_data['admin_quiz']['step'] = 'waiting_for_title'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_back_to_settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📝 تعیین عنوان آزمون\n\n"
        "لطفاً عنوان آزمون را وارد کنید:\n\n"
        "💡 مثال: 'آزمون ریاضی پیشرفته - آبان ۱۴۰۳'",
        reply_markup=reply_markup
    )

async def admin_ask_for_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست توضیحات آزمون از ادمین"""
    context.user_data['admin_quiz']['step'] = 'waiting_for_description'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_back_to_settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📋 تعیین توضیحات آزمون\n\n"
        "لطفاً توضیحات آزمون را وارد کنید (اختیاری):\n\n"
        "💡 می‌توانید 'ندارد' را ارسال کنید تا از توضیحات صرف نظر کنید.",
        reply_markup=reply_markup
    )

async def admin_ask_for_question_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست تعداد سوالات از ادمین"""
    context.user_data['admin_quiz']['step'] = 'waiting_for_count'
    
    # محاسبه حداکثر سوالات قابل دسترس
    total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in context.user_data['admin_quiz']['selected_topics']])
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_back_to_settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📊 تعیین تعداد سوالات\n\n"
        f"📚 سوالات قابل دسترس: {total_available}\n\n"
        f"لطفاً تعداد سوالات مورد نظر را وارد کنید (عدد بین ۱ تا {total_available}):",
        reply_markup=reply_markup
    )

async def admin_ask_for_time_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست زمان آزمون از ادمین"""
    context.user_data['admin_quiz']['step'] = 'waiting_for_time'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_back_to_settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "⏱ تعیین زمان آزمون\n\n"
        "لطفاً زمان آزمون را به دقیقه وارد کنید:\n\n"
        "💡 پیشنهاد: برای هر سوال ۱-۲ دقیقه در نظر بگیرید",
        reply_markup=reply_markup
    )

async def admin_set_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنظیم سطح سختی برای آزمون ادمین"""
    keyboard = [
        [InlineKeyboardButton("🎯 همه سطوح", callback_data="admin_set_difficulty_all")],
        [InlineKeyboardButton("🟢 آسان", callback_data="admin_set_difficulty_easy")],
        [InlineKeyboardButton("🟡 متوسط", callback_data="admin_set_difficulty_medium")],
        [InlineKeyboardButton("🔴 سخت", callback_data="admin_set_difficulty_hard")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_back_to_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 انتخاب سطح سختی\n\n"
        "لطفاً سطح مورد نظر را انتخاب کنید:\n\n"
        "• 🎯 همه سطوح: ترکیبی از سوالات آسان، متوسط و سخت\n"
        "• 🟢 آسان: سوالات با نرخ موفقیت بالا\n" 
        "• 🟡 متوسط: سوالات با سختی متوسط\n"
        "• 🔴 سخت: سوالات چالشی با نرخ موفقیت پایین",
        reply_markup=reply_markup
    )
async def process_admin_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش عنوان وارد شده توسط ادمین"""
    try:
        title = update.message.text.strip()
        
        if len(title) < 3:
            await update.message.reply_text("❌ عنوان باید حداقل ۳ کاراکتر باشد!")
            return
        
        context.user_data['admin_quiz']['settings']['title'] = title
        context.user_data['admin_quiz']['step'] = 'settings'
        
        await update.message.reply_text(f"✅ عنوان آزمون ثبت شد: {title}")
        await admin_show_settings(update, context)
        
    except Exception as e:
        logger.error(f"Error processing admin title: {e}")
        await update.message.reply_text("❌ خطا در پردازش عنوان!")

async def process_admin_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش توضیحات وارد شده توسط ادمین"""
    try:
        description = update.message.text.strip()
        
        if description == 'ندارد':
            description = ""
        
        context.user_data['admin_quiz']['settings']['description'] = description
        context.user_data['admin_quiz']['step'] = 'settings'
        
        if description:
            await update.message.reply_text(f"✅ توضیحات آزمون ثبت شد")
        else:
            await update.message.reply_text("✅ توضیحات حذف شد")
        
        await admin_show_settings(update, context)
        
    except Exception as e:
        logger.error(f"Error processing admin description: {e}")
        await update.message.reply_text("❌ خطا در پردازش توضیحات!")

async def process_admin_question_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش تعداد سوالات وارد شده توسط ادمین"""
    try:
        text = update.message.text.strip()
        count = int(text)
        
        # محاسبه حداکثر سوالات قابل دسترس
        total_available = sum([get_questions_count_by_topic(tid)[0][0] for tid in context.user_data['admin_quiz']['selected_topics']])
        
        if count < 1:
            await update.message.reply_text("❌ تعداد سوالات باید حداقل ۱ باشد!")
            return
        elif count > total_available:
            await update.message.reply_text(
                f"❌ تعداد سوالات نمی‌تواند بیشتر از {total_available} باشد!\n\n"
                f"لطفاً عدد کوچکتری وارد کنید:"
            )
            return
        
        context.user_data['admin_quiz']['settings']['count'] = count
        context.user_data['admin_quiz']['step'] = 'settings'
        
        await update.message.reply_text(f"✅ تعداد سوالات روی {count} تنظیم شد")
        await admin_show_settings(update, context)
        
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")

async def process_admin_time_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش زمان آزمون وارد شده توسط ادمین"""
    try:
        text = update.message.text.strip()
        time_limit = int(text)
        
        if time_limit < 1:
            await update.message.reply_text("❌ زمان آزمون باید حداقل ۱ دقیقه باشد!")
            return
        elif time_limit > 180:
            await update.message.reply_text("❌ زمان آزمون نمی‌تواند بیشتر از ۱۸۰ دقیقه باشد!")
            return
        
        context.user_data['admin_quiz']['settings']['time_limit'] = time_limit
        context.user_data['admin_quiz']['step'] = 'settings'
        
        await update.message.reply_text(f"✅ زمان آزمون روی {time_limit} دقیقه تنظیم شد")
        await admin_show_settings(update, context)
        
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")
async def admin_generate_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد نهایی آزمون توسط ادمین با پشتیبانی از همه حالت‌ها"""
    try:
        quiz_data = context.user_data['admin_quiz']
        settings = quiz_data['settings']
        mode = quiz_data.get('mode', 'topics')
        
        # اعتبارسنجی داده‌ها
        if not settings['title']:
            await update.callback_query.answer("❌ لطفاً عنوان آزمون را تعیین کنید!", show_alert=True)
            return
        
        # اعتبارسنجی بر اساس حالت انتخاب شده
        if mode == 'topics' and not quiz_data['selected_topics']:
            await update.callback_query.answer("❌ لطفاً حداقل یک مبحث انتخاب کنید!", show_alert=True)
            return
        elif mode == 'resources' and not quiz_data['selected_resources']:
            await update.callback_query.answer("❌ لطفاً حداقل یک منبع انتخاب کنید!", show_alert=True)
            return
        elif mode == 'both' and not quiz_data['selected_topics'] and not quiz_data['selected_resources']:
            await update.callback_query.answer("❌ لطفاً حداقل یک مبحث یا منبع انتخاب کنید!", show_alert=True)
            return
        
        # دریافت سوالات بر اساس حالت انتخاب شده
        questions = []
        total_available = 0
        
        if mode == 'topics':
            questions = get_questions_by_topics(
                quiz_data['selected_topics'],
                settings['difficulty'],
                settings['count']
            )
            # محاسبه سوالات قابل دسترس
            for topic_id in quiz_data['selected_topics']:
                count_result = get_questions_count_by_topic(topic_id)
                total_available += count_result[0][0] if count_result else 0
                
        elif mode == 'resources':
            questions = get_questions_by_resources(
                quiz_data['selected_resources'],
                settings['difficulty'],
                settings['count']
            )
            # محاسبه سوالات قابل دسترس
            for resource_id in quiz_data['selected_resources']:
                count_result = get_questions_count_by_resource(resource_id)
                total_available += count_result[0][0] if count_result else 0
                
        elif mode == 'both':
            # ترکیب سوالات از مباحث و منابع
            topic_questions = []
            resource_questions = []
            
            if quiz_data['selected_topics']:
                topic_questions = get_questions_by_topics(
                    quiz_data['selected_topics'],
                    settings['difficulty'],
                    settings['count'] // 2
                )
                # محاسبه سوالات قابل دسترس از مباحث
                for topic_id in quiz_data['selected_topics']:
                    count_result = get_questions_count_by_topic(topic_id)
                    total_available += count_result[0][0] if count_result else 0
            
            if quiz_data['selected_resources']:
                remaining_count = settings['count'] - len(topic_questions)
                if remaining_count > 0:
                    resource_questions = get_questions_by_resources(
                        quiz_data['selected_resources'],
                        settings['difficulty'],
                        remaining_count
                    )
                # محاسبه سوالات قابل دسترس از منابع
                for resource_id in quiz_data['selected_resources']:
                    count_result = get_questions_count_by_resource(resource_id)
                    total_available += count_result[0][0] if count_result else 0
            
            questions = topic_questions + resource_questions
        
        if not questions:
            await update.callback_query.answer(
                f"❌ هیچ سوالی برای انتخاب‌های شما یافت نشد!\n\n"
                f"سوالات قابل دسترس: {total_available}",
                show_alert=True
            )
            return
        
        # اگر تعداد سوالات کمتر از تعداد درخواستی باشد
        if len(questions) < settings['count']:
            await update.callback_query.answer(
                f"⚠️ فقط {len(questions)} سوال از {settings['count']} سوال درخواستی موجود بود!",
                show_alert=True
            )
        
        # ایجاد آزمون در دیتابیس
        quiz_id = create_quiz(
            settings['title'],
            settings['description'],
            settings['time_limit'],
            True  # created_by_admin = True
        )
        
        if not quiz_id:
            await update.callback_query.answer("❌ خطا در ایجاد آزمون!", show_alert=True)
            return
        
        # افزودن سوالات به آزمون
        for i, question in enumerate(questions):
            add_question(quiz_id, question[1], question[2], i)
        
        # پاک کردن داده‌های موقت
        if 'admin_quiz' in context.user_data:
            del context.user_data['admin_quiz']
        
        # ایجاد متن موفقیت بر اساس حالت
        mode_texts = {
            'topics': f"مباحث: {len(quiz_data['selected_topics'])} مبحث",
            'resources': f"منابع: {len(quiz_data['selected_resources'])} منبع", 
            'both': f"مباحث: {len(quiz_data['selected_topics'])}، منابع: {len(quiz_data['selected_resources'])}"
        }
        
        # نمایش نام مباحث و منابع انتخاب شده
        selected_items_text = ""
        if mode == 'topics' and quiz_data['selected_topics']:
            topic_names = [get_topic_name(tid) for tid in quiz_data['selected_topics']]
            selected_items_text = "\n📚 مباحث انتخاب شده:\n" + "\n".join([f"• {name}" for name in topic_names])
        elif mode == 'resources' and quiz_data['selected_resources']:
            resource_names = [get_resource_name(rid) for rid in quiz_data['selected_resources']]
            selected_items_text = "\n📖 منابع انتخاب شده:\n" + "\n".join([f"• {name}" for name in resource_names])
        elif mode == 'both':
            if quiz_data['selected_topics']:
                topic_names = [get_topic_name(tid) for tid in quiz_data['selected_topics']]
                selected_items_text += "\n📚 مباحث انتخاب شده:\n" + "\n".join([f"• {name}" for name in topic_names])
            if quiz_data['selected_resources']:
                resource_names = [get_resource_name(rid) for rid in quiz_data['selected_resources']]
                selected_items_text += "\n📖 منابع انتخاب شده:\n" + "\n".join([f"• {name}" for name in resource_names])
        
        # نمایش پیام موفقیت
        success_message = (
            f"✅ آزمون ادمین با موفقیت ایجاد شد!\n\n"
            f"📌 عنوان: {settings['title']}\n"
            f"📝 توضیحات: {settings['description'] or 'ندارد'}\n"
            f"🎯 حالت انتخاب: {mode_texts.get(mode, 'مباحث')}\n"
            f"📊 تعداد سوالات: {len(questions)} از {settings['count']} درخواستی\n"
            f"⏱ زمان: {settings['time_limit']} دقیقه\n"
            f"🎯 سطح سختی: {settings['difficulty']}"
            f"{selected_items_text}\n\n"
            f"آزمون اکنون در لیست آزمون‌های فعال قابل مشاهده است. 👑"
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 مدیریت آزمون‌ها", callback_data="admin_manage_quizzes")],
            [InlineKeyboardButton("🔙 پنل ادمین", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(success_message, reply_markup=reply_markup)
        
        # لاگ کردن اطلاعات آزمون
        logger.info(f"✅ ADMIN_QUIZ_CREATED: Title: {settings['title']}, "
                   f"Questions: {len(questions)}, Mode: {mode}, "
                   f"Topics: {len(quiz_data.get('selected_topics', []))}, "
                   f"Resources: {len(quiz_data.get('selected_resources', []))}")
        
    except Exception as e:
        logger.error(f"❌ Error in admin generate quiz: {e}")
        await update.callback_query.answer("❌ خطا در ایجاد آزمون!", show_alert=True)
async def admin_add_more_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن مباحث بیشتر به آزمون ادمین"""
    context.user_data['admin_quiz']['step'] = 'adding_more_topics'
    
    # نمایش مباحث انتخاب شده فعلی
    topics_text = "\n".join([
        f"• {get_topic_name(tid)}"
        for tid in context.user_data['admin_quiz']['selected_topics']
    ])
    
    keyboard = [
        [InlineKeyboardButton("🔍 افزودن مبحث جدید", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_back_to_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📚 افزودن مباحث بیشتر\n\n"
        f"مباحث انتخاب شده فعلی:\n{topics_text}\n\n"
        f"روی دکمه زیر کلیک کنید تا مبحث جدیدی اضافه کنید:",
        reply_markup=reply_markup
    )

async def admin_back_to_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به تنظیمات آزمون ادمین"""
    context.user_data['admin_quiz']['step'] = 'settings'
    await admin_show_settings(update, context)

async def admin_manage_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت آزمون‌ها"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    quizzes = execute_query("SELECT id, title, is_active FROM quizzes ORDER BY created_at DESC")
    
    if not quizzes:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
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
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")])
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
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ کاربری یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    # محاسبه تعداد کل کاربران
    total_users = len(users)
    
    text = f"👥 لیست کاربران (تعداد کل: {total_users}):\n\n"
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
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup
    )


async def admin_view_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده نتایج تلفیقی کاربران بر اساس امتیاز و آیدی"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    # دریافت نتایج تلفیقی کاربران
    user_stats = get_user_comprehensive_stats()
    
    if not user_stats:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ نتیجه‌ای یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    text = "🏆 رتبه‌بندی کاربران بر اساس امتیاز ترکیبی:\n\n"
    
    for i, stat in enumerate(user_stats[:20]):  # نمایش 20 کاربر برتر
        try:
            # بررسی تعداد فیلدها
            if len(stat) >= 8:
                user_id, full_name, total_quizzes, avg_score, best_score, total_correct, total_time, composite_score = stat
            elif len(stat) == 7:
                user_id, full_name, total_quizzes, avg_score, best_score, total_correct, total_time = stat
                composite_score = (float(avg_score) * 0.7) + (min(int(total_quizzes), 10) * 3)
            else:
                # اگر تعداد فیلدها کمتر است، از مقادیر پیش‌فرض استفاده کن
                user_id = stat[0] if len(stat) > 0 else "نامشخص"
                full_name = stat[1] if len(stat) > 1 else "نامشخص"
                total_quizzes = stat[2] if len(stat) > 2 else 0
                avg_score = stat[3] if len(stat) > 3 else 0
                best_score = stat[4] if len(stat) > 4 else 0
                total_correct = stat[5] if len(stat) > 5 else 0
                composite_score = (float(avg_score) * 0.7) + (min(int(total_quizzes), 10) * 3)
            
            # تبدیل مقادیر decimal به float برای نمایش
            avg_score_float = float(avg_score) if avg_score is not None else 0.0
            best_score_float = float(best_score) if best_score is not None else 0.0
            total_quizzes_int = int(total_quizzes) if total_quizzes is not None else 0
            total_correct_int = int(total_correct) if total_correct is not None else 0
            composite_score_float = float(composite_score) if composite_score is not None else 0.0
            
            # کوتاه کردن نام اگر طولانی باشد
            display_name = full_name[:20] + "..." if full_name and len(full_name) > 20 else full_name or "نامشخص"
            
            text += f"**{i+1}. {display_name}**\n"
            text += f"   🆔 آیدی: `{user_id}`\n"
            text += f"   ⭐ امتیاز: **{composite_score_float:.1f}**\n"
            text += f"   📈 میانگین: {avg_score_float:.1f}% | 🏆 بهترین: {best_score_float:.1f}%\n"
            text += f"   📚 آزمون‌ها: {total_quizzes_int} | ✅ صحیح کل: {total_correct_int}\n"
            text += "─" * 35 + "\n"
            
        except Exception as e:
            logger.error(f"Error processing user stat: {e}, stat: {stat}")
            continue
    
    if len(user_stats) > 20:
        text += f"\n📊 و {len(user_stats) - 20} کاربر دیگر..."
    
    text += f"\n💡 **معیار امتیازدهی:**\n"
    text += f"• 70% میانگین نمره آزمون‌ها\n"
    text += f"• 30% تعداد آزمون‌ها (حداکثر 10 آزمون)"
    
    keyboard = [
        [InlineKeyboardButton("📈 مشاهده آمار دقیق", callback_data="detailed_stats")],
        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش آمار دقیق کاربران با جزئیات کامل"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    # دریافت آمار دقیق
    user_stats = get_user_comprehensive_stats()
    
    if not user_stats:
        await update.callback_query.answer("❌ هیچ آماری یافت نشد!")
        return
    
    text = "📊 آمار دقیق عملکرد کاربران:\n\n"
    
    for i, stat in enumerate(user_stats[:15]):
        try:
            # بررسی تعداد فیلدها
            if len(stat) >= 8:
                user_id, full_name, total_quizzes, avg_score, best_score, total_correct, total_time, composite_score = stat
            elif len(stat) == 7:
                user_id, full_name, total_quizzes, avg_score, best_score, total_correct, total_time = stat
                composite_score = (float(avg_score) * 0.7) + (min(int(total_quizzes), 10) * 3)
            else:
                user_id = stat[0] if len(stat) > 0 else "نامشخص"
                full_name = stat[1] if len(stat) > 1 else "نامشخص"
                total_quizzes = stat[2] if len(stat) > 2 else 0
                avg_score = stat[3] if len(stat) > 3 else 0
                best_score = stat[4] if len(stat) > 4 else 0
                total_correct = stat[5] if len(stat) > 5 else 0
                composite_score = (float(avg_score) * 0.7) + (min(int(total_quizzes), 10) * 3)
            
            # تبدیل مقادیر
            avg_score_float = float(avg_score) if avg_score is not None else 0.0
            best_score_float = float(best_score) if best_score is not None else 0.0
            total_quizzes_int = int(total_quizzes) if total_quizzes is not None else 0
            total_correct_int = int(total_correct) if total_correct is not None else 0
            total_time_float = float(total_time) if total_time is not None else 0.0
            composite_score_float = float(composite_score) if composite_score is not None else 0.0
            
            display_name = full_name[:18] + "..." if full_name and len(full_name) > 18 else full_name or "نامشخص"
            
            # محاسبه میانگین زمان و صحیح
            avg_time_per_quiz = total_time_float / total_quizzes_int if total_quizzes_int > 0 else 0
            avg_correct_per_quiz = total_correct_int / total_quizzes_int if total_quizzes_int > 0 else 0
            avg_time_str = f"{int(avg_time_per_quiz) // 60}:{int(avg_time_per_quiz) % 60:02d}"
            
            text += f"**{i+1}. {display_name}**\n"
            text += f"   🆔 آیدی: `{user_id}`\n"
            text += f"   ⭐ امتیاز ترکیبی: **{composite_score_float:.1f}**\n"
            text += f"   📊 تعداد آزمون: {total_quizzes_int}\n"
            text += f"   📈 میانگین نمره: {avg_score_float:.1f}%\n"
            text += f"   🏆 بهترین نمره: {best_score_float:.1f}%\n"
            text += f"   ✅ پاسخ‌های صحیح: {total_correct_int}\n"
            text += f"   ⏱ زمان میانگین: {avg_time_str}\n"
            text += f"   📝 میانگین صحیح: {avg_correct_per_quiz:.1f} در هر آزمون\n\n"
            
        except Exception as e:
            logger.error(f"Error processing detailed stat: {e}, stat: {stat}")
            continue
    
    if len(user_stats) > 15:
        text += f"📈 و {len(user_stats) - 15} کاربر دیگر..."
    
    text += f"\n🔍 **جزئیات محاسبه امتیاز:**\n"
    text += f"امتیاز ترکیبی = (میانگین نمره × 0.7) + (تعداد آزمون × 3)\n"
    text += f"• حداکثر 10 آزمون در محاسبه اعمال می‌شود"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_view_results")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)



async def admin_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ارسال پیام همگانی با قابلیت‌های کامل"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'broadcasting'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📢 ارسال پیام همگانی:\n\n"
        "✅ **قابلیت‌های موجود:**\n"
        "• 📝 متن ساده\n"
        "• 📸 عکس (با یا بدون توضیح)\n"
        "• 📊 نظرسنجی (Poll)\n"
        "• 🎬 ویدئو\n"
        "• 📄 فایل\n"
        "• 🎵 فایل صوتی\n"
        "• 🎙️ پیام صوتی\n\n"
        "**لطفاً محتوای مورد نظر را ارسال کنید:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش و ارسال پیام همگانی با پشتیبانی از عکس، نظرسنجی و سایر رسانه‌ها"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    if 'admin_action' not in context.user_data or context.user_data['admin_action'] != 'broadcasting':
        return
    
    # دریافت تمام کاربران
    users = get_all_users()
    if not users:
        await update.message.reply_text("❌ هیچ کاربری برای ارسال پیام وجود ندارد!")
        return
    
    total_users = len(users)
    logger.info(f"📊 BROADCAST: Found {total_users} users in database")
    
    successful_sends = 0
    failed_sends = 0
    errors_log = []
    
    # اطلاع رسانی شروع ارسال
    progress_msg = await update.message.reply_text(
        f"📤 شروع ارسال پیام به {total_users} کاربر...\n\n"
        f"✅ موفق: 0\n"
        f"❌ ناموفق: 0\n"
        f"📊 پیشرفت: 0%\n"
        f"🔄 در حال ارسال..."
    )
    
    # بررسی نوع محتوای ارسالی
    message_type = "text"
    media_content = None
    poll_data = None
    
    # تشخیص نوع پیام
    if update.message.photo:
        message_type = "photo"
        media_content = await update.message.photo[-1].get_file()
        caption = update.message.caption
        logger.info(f"📸 BROADCAST: Photo detected, caption: {caption}")
        
    elif update.message.poll:
        message_type = "poll"
        poll_data = {
            'question': update.message.poll.question,
            'options': [option.text for option in update.message.poll.options],
            'is_anonymous': update.message.poll.is_anonymous,
            'type': update.message.poll.type,
            'allows_multiple_answers': update.message.poll.allows_multiple_answers
        }
        logger.info(f"📊 BROADCAST: Poll detected, question: {poll_data['question']}")
        
    elif update.message.video:
        message_type = "video"
        media_content = await update.message.video.get_file()
        caption = update.message.caption
        logger.info(f"🎬 BROADCAST: Video detected")
        
    elif update.message.document:
        message_type = "document"
        media_content = await update.message.document.get_file()
        caption = update.message.caption
        logger.info(f"📄 BROADCAST: Document detected")
        
    elif update.message.audio:
        message_type = "audio"
        media_content = await update.message.audio.get_file()
        caption = update.message.caption
        logger.info(f"🎵 BROADCAST: Audio detected")
        
    elif update.message.voice:
        message_type = "voice"
        media_content = await update.message.voice.get_file()
        logger.info(f"🎙️ BROADCAST: Voice message detected")
        
    elif update.message.text:
        message_type = "text"
        text_content = update.message.text
        logger.info(f"📝 BROADCAST: Text message detected")
    
    # ارسال به کاربران
    for index, user in enumerate(users):
        user_id = user[0]
        
        try:
            logger.info(f"📨 BROADCAST: Attempting to send to user {user_id}, type: {message_type}")
            
            if message_type == "photo" and media_content:
                # ارسال عکس
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=media_content.file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN if update.message.caption else None
                )
                
            elif message_type == "poll" and poll_data:
                # ارسال نظرسنجی
                await context.bot.send_poll(
                    chat_id=user_id,
                    question=poll_data['question'],
                    options=poll_data['options'],
                    is_anonymous=poll_data['is_anonymous'],
                    type=poll_data['type'],
                    allows_multiple_answers=poll_data['allows_multiple_answers']
                )
                
            elif message_type == "video" and media_content:
                # ارسال ویدئو
                await context.bot.send_video(
                    chat_id=user_id,
                    video=media_content.file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN if update.message.caption else None
                )
                
            elif message_type == "document" and media_content:
                # ارسال فایل
                await context.bot.send_document(
                    chat_id=user_id,
                    document=media_content.file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN if update.message.caption else None
                )
                
            elif message_type == "audio" and media_content:
                # ارسال صوت
                await context.bot.send_audio(
                    chat_id=user_id,
                    audio=media_content.file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN if update.message.caption else None
                )
                
            elif message_type == "voice" and media_content:
                # ارسال پیام صوتی
                await context.bot.send_voice(
                    chat_id=user_id,
                    voice=media_content.file_id
                )
                
            elif message_type == "text" and update.message.text:
                # ارسال متن ساده
                await context.bot.send_message(
                    chat_id=user_id,
                    text=update.message.text,
                    parse_mode=ParseMode.MARKDOWN if update.message.parse_mode else None
                )
            else:
                logger.error(f"❌ BROADCAST: Unknown message type: {message_type}")
                failed_sends += 1
                errors_log.append(f"نوع پیام ناشناخته: {message_type}")
                continue
            
            successful_sends += 1
            logger.info(f"✅ BROADCAST: Successfully sent to user {user_id}")
            
        except Exception as e:
            error_msg = f"Failed to send to user {user_id}: {str(e)[:100]}"
            logger.error(f"❌ BROADCAST: {error_msg}")
            errors_log.append(error_msg)
            failed_sends += 1
        
        # بروزرسانی پیشرفت هر ۵ کاربر
        if (index + 1) % 5 == 0 or (index + 1) == total_users:
            progress = ((index + 1) / total_users) * 100
            try:
                await progress_msg.edit_text(
                    f"📤 ارسال پیام همگانی...\n\n"
                    f"✅ موفق: {successful_sends}\n"
                    f"❌ ناموفق: {failed_sends}\n"
                    f"📊 پیشرفت: {progress:.1f}%\n"
                    f"🆔 آخرین: {user_id}"
                )
            except Exception as e:
                logger.error(f"Failed to update progress: {e}")
        
        # تاخیر برای جلوگیری از محدودیت تلگرام (افزایش کمی برای رسانه‌های سنگین)
        delay = 0.3 if message_type in ["photo", "video", "document"] else 0.2
        await asyncio.sleep(delay)
    
    # نتیجه نهایی
    result_text = (
        f"🎉 ارسال پیام همگانی تکمیل شد!\n\n"
        f"📊 آمار ارسال:\n"
        f"• 👥 کاربران کل: {total_users}\n"
        f"• ✅ ارسال موفق: {successful_sends}\n"
        f"• ❌ ارسال ناموفق: {failed_sends}\n"
        f"• 📈 نرخ موفقیت: {(successful_sends/total_users)*100:.1f}%\n"
        f"• 📦 نوع محتوا: {message_type}"
    )
    
    # اضافه کردن نمونه‌ای از خطاها اگر وجود داشته باشد
    if errors_log and len(errors_log) > 0:
        sample_errors = "\n".join(errors_log[:3])  # ۳ خطای اول
        result_text += f"\n\n⚠️ نمونه خطاها:\n{sample_errors}"
        if len(errors_log) > 3:
            result_text += f"\n... و {len(errors_log) - 3} خطای دیگر"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await progress_msg.edit_text(result_text, reply_markup=reply_markup)
    
    # پاک کردن وضعیت
    if 'admin_action' in context.user_data:
        del context.user_data['admin_action']

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

async def handle_admin_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش عکس‌ها و فایل‌های ارسالی ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    logger.info(f"📸 ADMIN_PHOTO: Received media, context: {context.user_data}")
    
    # ===== اولویت 1: حالت پیام همگانی =====
    if context.user_data.get('admin_action') == 'broadcasting':
        logger.info(f"📸 BROADCAST_MEDIA: Processing media for broadcast")
        
        # برای پیام همگانی، محتوا مستقیماً به تابع handle_broadcast منتقل می‌شود
        # این کار در تابع handle_message انجام خواهد شد
        return
    
    # ===== اولویت 2: حالت افزودن سوال به بانک =====
    if (context.user_data.get('admin_action') == 'adding_question_to_bank' and
        'question_bank_data' in context.user_data):
        
        question_data = context.user_data['question_bank_data']
        logger.info(f"📸 ADMIN_PHOTO: Question bank data: {question_data}")
        
        # بررسی اینکه آیا مبحث انتخاب شده است
        if 'topic_id' not in question_data:
            logger.error("❌ ADMIN_PHOTO: No topic_id in question_data")
            await update.message.reply_text(
                "❌ ابتدا باید مبحث را انتخاب کنید!\n\n"
                "لطفاً از منوی ادمین دوباره گزینه 'افزودن سوال به بانک' را انتخاب کنید."
            )
            return
        
        # بررسی اینکه در مرحله دریافت عکس هستیم
        if question_data.get('step') != 'waiting_for_photo':
            logger.error(f"❌ ADMIN_PHOTO: Wrong step. Expected 'waiting_for_photo', got '{question_data.get('step')}'")
            await update.message.reply_text(
                "❌ در این مرحله نمی‌توانید عکس ارسال کنید! لطفاً فرآیند را از ابتدا شروع کنید."
            )
            return
        
        try:
            # فقط عکس‌ها را برای سوالات قبول می‌کنیم (نه فایل‌های دیگر)
            if update.message.photo:
                # دریافت و ذخیره عکس
                photo_file = await update.message.photo[-1].get_file()
                image_filename = f"question_bank_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}.jpg"
                image_path = os.path.join(PHOTOS_DIR, image_filename)
                
                await photo_file.download_to_drive(image_path)
                
                # ذخیره مسیر عکس و رفتن به مرحله بعد
                question_data['question_image'] = image_path
                question_data['step'] = 'waiting_for_answer'
                context.user_data['question_bank_data'] = question_data
                
                logger.info(f"✅ ADMIN_PHOTO: Question image saved: {image_path}")
                logger.info(f"✅ ADMIN_PHOTO: Moved to step: waiting_for_answer")
                
                await update.message.reply_text(
                    "✅ عکس سوال ذخیره شد.\n\n"
                    "**مرحله ۳/۳: تعیین پاسخ صحیح**\n\n"
                    "لطفاً شماره گزینه صحیح را ارسال کنید (1 تا 4):",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "❌ برای سوال آزمون فقط عکس قابل قبول است!"
                )
            
        except Exception as e:
            logger.error(f"❌ ADMIN_PHOTO: Error saving question image: {e}")
            await update.message.reply_text("❌ خطا در ذخیره عکس! لطفاً دوباره تلاش کنید.")
        
        return
    
    # ===== حالت عادی برای ایجاد آزمون =====
    if 'admin_action' not in context.user_data or context.user_data['admin_action'] != 'adding_questions':
        await update.message.reply_text("❌ ابتدا فرآیند ایجاد آزمون را شروع کنید.")
        return
    
    quiz_data = context.user_data.get('quiz_data', {})
    
    if quiz_data.get('current_step') != 'question_image':
        await update.message.reply_text("❌ در این مرحله نمی‌توانید عکس ارسال کنید.")
        return
    
    # دریافت عکس
    if update.message.photo:
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
    else:
        await update.message.reply_text("❌ برای سوال آزمون فقط عکس قابل قبول است!")
async def handle_admin_documents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش فایل‌های ارسالی ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    logger.info(f"📄 ADMIN_DOCUMENT: Received document, context: {context.user_data}")
    
    # فقط برای پیام همگانی فایل‌ها را قبول می‌کنیم
    if context.user_data.get('admin_action') == 'broadcasting':
        logger.info(f"📄 BROADCAST_DOCUMENT: Processing document for broadcast")
        # برای پیام همگانی، فایل مستقیماً به تابع handle_broadcast منتقل می‌شود
        # این کار در تابع handle_message انجام خواهد شد
        return
    
    # برای سایر موارد، فایل قبول نمی‌کنیم
    await update.message.reply_text(
        "❌ فایل فقط برای پیام همگانی قابل ارسال است!\n\n"
        "برای افزودن سوال به آزمون، لطفاً فقط عکس ارسال کنید."
    )

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش متن‌های ارسالی ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    text = update.message.text
    logger.info(f"📝 ADMIN_TEXT: Received text: '{text}', context: {context.user_data}")
    
    # اگر در حال افزودن سوال به بانک است
    if context.user_data.get('admin_action') == 'adding_question_to_bank':
        if 'question_bank_data' not in context.user_data:
            logger.error("❌ ADMIN_TEXT: No question_bank_data in context")
            await update.message.reply_text("❌ خطا! ابتدا فرآیند را دوباره شروع کنید.")
            return
        
        question_data = context.user_data['question_bank_data']
        logger.info(f"📝 ADMIN_TEXT: Question bank data: {question_data}")
        
        # بررسی اینکه آیا عکس و مبحث انتخاب شده است
        if 'question_image' not in question_data or 'topic_id' not in question_data:
            logger.error("❌ ADMIN_TEXT: Missing question_image or topic_id")
            await update.message.reply_text("❌ ابتدا مبحث و عکس سوال را انتخاب کنید.")
            return
        
        # بررسی اینکه در مرحله دریافت پاسخ هستیم
        if question_data.get('step') != 'waiting_for_answer':
            logger.error(f"❌ ADMIN_TEXT: Wrong step. Expected 'waiting_for_answer', got '{question_data.get('step')}'")
            await update.message.reply_text("❌ در این مرحله نمی‌توانید پاسخ ارسال کنید!")
            return
        
        try:
            correct_answer = int(text)
            if correct_answer < 1 or correct_answer > 4:
                raise ValueError("Answer out of range")
            
            # ذخیره سوال در بانک
            result = add_question_to_bank(
                question_data['topic_id'],
                question_data['question_image'],
                correct_answer
            )
            
            if result:
                topic_name = question_data.get('topic_name', 'نامشخص')
                
                success_message = (
                    f"✅ سوال با موفقیت به بانک اضافه شد!\n\n"
                    f"📚 مبحث: {topic_name}\n"
                    f"📸 عکس: {os.path.basename(question_data['question_image'])}\n"
                    f"✅ پاسخ صحیح: گزینه {correct_answer}"
                )
                
                await update.message.reply_text(success_message)
                logger.info(f"✅ ADMIN_TEXT: Question added to bank successfully")
            else:
                await update.message.reply_text("❌ خطا در ذخیره سوال!")
                logger.error("❌ ADMIN_TEXT: Failed to add question to bank")
            
            # پاک کردن داده‌های موقت
            del context.user_data['question_bank_data']
            del context.user_data['admin_action']
            logger.info("✅ ADMIN_TEXT: Cleaned up context data")
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً عددی بین 1 تا 4 وارد کنید:")
        except Exception as e:
            logger.error(f"❌ ADMIN_TEXT: Error adding question: {e}")
            await update.message.reply_text("❌ خطا در ذخیره سوال! لطفاً دوباره تلاش کنید.")
        
        return
    
    # حالت عادی برای ایجاد آزمون
    action = context.user_data.get('admin_action')
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
                    time_limit,
                    True
                )
                
                if quiz_id:
                    quiz_data['quiz_id'] = quiz_id
                    quiz_data['current_step'] = 'add_questions'
                    context.user_data['quiz_data'] = quiz_data
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ بله، افزودن سوالات", callback_data="confirm_add_questions")],
                        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
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

async def admin_add_question_to_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند افزودن سوال به بانک با انتخاب مبحث و منبع"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    logger.info("🔧 ADMIN: Starting admin_add_question_to_bank")
    
    # پاک کردن contextهای قبلی و تنظیم state جدید
    clear_admin_context(context)
    
    context.user_data['admin_action'] = 'adding_question_to_bank'
    context.user_data['question_bank_data'] = {
        'step': 'selecting_topic',
        'flow_type': 'question_bank'
    }
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب مبحث", switch_inline_query_current_chat="مبحث ")],
        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚 افزودن سوال به بانک:\n\n"
        "**مرحله ۱/۳: انتخاب مبحث**\n\n"
        "روی دکمه '🔍 انتخاب مبحث' کلیک کنید و مبحث مورد نظر را جستجو و انتخاب کنید.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
async def handle_topic_selection_for_question_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب مبحث برای افزودن سوال به بانک"""
    try:
        text = update.message.text
        topic_name = text.replace("مبحث انتخاب شده:", "").strip()
        
        topic_info = get_topic_by_name(topic_name)
        if not topic_info:
            await update.message.reply_text(f"❌ مبحث '{topic_name}' یافت نشد!")
            return
        
        topic_id, name, description, is_active = topic_info[0]
        
        # ذخیره مبحث و رفتن به مرحله انتخاب منبع
        context.user_data['question_bank_data'] = {
            'topic_id': topic_id,
            'topic_name': name,
            'step': 'selecting_resource'
        }
        
        keyboard = [
            [InlineKeyboardButton("🔍 انتخاب منبع", switch_inline_query_current_chat="منبع ")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_add_question")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ مبحث انتخاب شد: **{name}**\n\n"
            f"**مرحله ۲/۳: انتخاب منبع**\n\n"
            f"روی دکمه '🔍 انتخاب منبع' کلیک کنید و منبع سوال را انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in topic selection for question bank: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب مبحث!")
async def handle_resource_selection_for_question_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب منبع برای افزودن سوال به بانک"""
    try:
        text = update.message.text
        resource_name = text.replace("منبع انتخاب شده:", "").strip()
        
        resource_info = get_resource_by_name(resource_name)
        if not resource_info:
            await update.message.reply_text(f"❌ منبع '{resource_name}' یافت نشد!")
            return
        
        resource_id, name, description, is_active = resource_info[0]
        
        # ذخیره منبع و رفتن به مرحله دریافت عکس
        question_data = context.user_data['question_bank_data']
        question_data['resource_id'] = resource_id
        question_data['resource_name'] = name
        question_data['step'] = 'waiting_for_photo'
        
        await update.message.reply_text(
            f"✅ منبع انتخاب شد: **{name}**\n\n"
            f"**مرحله ۳/۳: ارسال عکس سوال**\n\n"
            f"📸 لطفاً عکس سوال را ارسال کنید:",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error in resource selection for question bank: {e}")
        await update.message.reply_text("❌ خطا در پردازش انتخاب منبع!")
async def start_custom_quiz_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ایجاد آزمون سفارشی با انتخاب حالت"""
    context.user_data['custom_quiz'] = {
        'step': 'select_mode',
        'selected_topics': [],
        'selected_resources': [],
        'settings': {
            'count': 20,
            'time_limit': 30,
            'difficulty': 'all'
        }
    }
    
    keyboard = [
        [InlineKeyboardButton("📚 انتخاب از مباحث", callback_data="select_topics_mode")],
        [InlineKeyboardButton("📖 انتخاب از منابع", callback_data="select_resources_mode")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 ساخت آزمون سفارشی\n\n"
        "لطفاً نوع انتخاب سوالات را مشخص کنید:\n\n"
        "• 📚 **انتخاب از مباحث**: سوالات بر اساس موضوع درسی انتخاب می‌شوند\n"
        "• 📖 **انتخاب از منابع**: سوالات بر اساس کتاب‌های درسی انتخاب می‌شوند",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_topics_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالت انتخاب از مباحث"""
    context.user_data['custom_quiz']['mode'] = 'topics'
    context.user_data['custom_quiz']['step'] = 'select_first_topic'
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب مبحث اول", switch_inline_query_current_chat="مبحث ")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚 حالت: انتخاب از مباحث\n\n"
        "مرحله ۱/۴: انتخاب مبحث اول\n\n"
        "روی دکمه زیر کلیک کنید و مبحث اول را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def select_resources_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حالت انتخاب از منابع"""
    context.user_data['custom_quiz']['mode'] = 'resources'
    context.user_data['custom_quiz']['step'] = 'select_first_resource'
    
    keyboard = [
        [InlineKeyboardButton("🔍 انتخاب منبع اول", switch_inline_query_current_chat="منبع ")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📖 حالت: انتخاب از منابع\n\n"
        "مرحله ۱/۴: انتخاب منبع اول\n\n"
        "روی دکمه زیر کلیک کنید و منبع اول را انتخاب کنید:",
        reply_markup=reply_markup
    )
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    user_id = update.effective_user.id
    
    logger.info(f"🔍 INLINE_QUERY: User {user_id}, Query: '{query}'")
    
    results = []
    
    # تشخیص نوع جستجو بر اساس کلمات کلیدی
    is_resource_search = "منبع" in query or "resource" in query
    is_topic_search = "مبحث" in query or "topic" in query or not (is_resource_search or query == "")
    
    # حذف کلمات کلیدی از query برای جستجوی واقعی
    clean_query = query.replace("منبع", "").replace("مبحث", "").replace("resource", "").replace("topic", "").strip()
    
    if is_topic_search:
        topics = get_all_topics()
        for topic in topics:
            topic_id, name, description, is_active = topic
            if not clean_query or clean_query in name.lower() or (description and clean_query in description.lower()):
                results.append(InlineQueryResultArticle(
                    id=f"topic_{topic_id}",
                    title=f"📚 {name}",
                    description=description or "بدون توضیح",
                    input_message_content=InputTextMessageContent(
                        f"مبحث انتخاب شده: {name}"
                    )
                ))
    
    if is_resource_search:
        resources = get_all_resources()
        for resource in resources:
            resource_id, name, description, is_active = resource
            if not clean_query or clean_query in name.lower() or (description and clean_query in description.lower()):
                results.append(InlineQueryResultArticle(
                    id=f"resource_{resource_id}",
                    title=f"📖 {name}",
                    description=description or "بدون توضیح",
                    input_message_content=InputTextMessageContent(
                        f"منبع انتخاب شده: {name}"
                    )
                ))
    
    logger.info(f"🔍 INLINE_QUERY: Returning {len(results)} results")
    await update.inline_query.answer(results, cache_time=1)

async def handle_admin_question_bank_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, result_id: str):
    """مدیریت جریان افزودن سوال به بانک برای ادمین"""
    logger.info(f"🔄 ADMIN_FLOW: Starting with result_id: '{result_id}'")
    
    try:
        # استخراج topic_id از result_id
        if result_id.startswith("topic_"):
            topic_id = int(result_id.replace("topic_", ""))
        else:
            topic_id = int(result_id)
        
        logger.info(f"🔄 ADMIN_FLOW: Topic ID extracted: {topic_id}")
        
        # تنظیم داده‌های مورد نیاز
        context.user_data['question_bank_data'] = {
            'topic_id': topic_id,
            'step': 'waiting_for_photo'
        }
        # اطمینان از اینکه admin_action همچنان تنظیم است
        context.user_data['admin_action'] = 'adding_question_to_bank'
        
        logger.info(f"🔄 ADMIN_FLOW: Context updated - question_bank_data: {context.user_data.get('question_bank_data')}")
        
        # دریافت اطلاعات مبحث
        topic_info = get_topic_by_id(topic_id)
        if not topic_info:
            logger.error(f"❌ ADMIN_FLOW: Topic not found for ID: {topic_id}")
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text="❌ اطلاعات مبحث یافت نشد!"
            )
            return
        
        topic_name = topic_info[0][1]
        logger.info(f"🔄 ADMIN_FLOW: Found topic: {topic_name}")
        
        # ارسال پیام به ادمین
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"✅ مبحث انتخاب شد: {topic_name}\n\n"
                f"**مرحله ۲/۳: ارسال عکس سوال**\n\n"
                f"📸 لطفاً عکس سوال را ارسال کنید:"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info("🔄 ADMIN_FLOW: Successfully moved to photo stage")
        
    except ValueError as e:
        logger.error(f"❌ ADMIN_FLOW: Invalid result_id '{result_id}': {e}")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"❌ خطا: شناسه مبحث نامعتبر ('{result_id}')"
        )
    except Exception as e:
        logger.error(f"❌ ADMIN_FLOW: Unexpected error: {e}")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="❌ خطای غیرمنتظره در پردازش انتخاب مبحث! لطفاً دوباره تلاش کنید."
        )

async def admin_manage_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت مباحث با قابلیت ویرایش"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    topics = get_all_topics()
    
    if not topics:
        keyboard = [
            [InlineKeyboardButton("➕ افزودن مبحث جدید", callback_data="admin_add_topic")],
            [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "⚠️ هیچ مبحثی یافت نشد.",
            reply_markup=reply_markup
        )
        return
    
    text = "📚 مدیریت مباحث:\n\n"
    for topic in topics:
        topic_id, name, description, is_active = topic
        status = "✅ فعال" if is_active else "❌ غیرفعال"
        text += f"• {name} ({status})\n"
        if description:
            text += f"  📝 {description}\n"
        text += f"  🆔 کد: {topic_id}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ افزودن مبحث جدید", callback_data="admin_add_topic")],
        [InlineKeyboardButton("✏️ ویرایش مبحث", callback_data="admin_edit_topic")],
        [InlineKeyboardButton("❌ حذف مبحث", callback_data="admin_delete_topic")],
        [InlineKeyboardButton("🔍 مشاهده سوالات مبحث", callback_data="admin_view_topic_questions")],
        [InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
async def admin_edit_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ویرایش مبحث"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    topics = get_all_topics()
    
    if not topics:
        await update.callback_query.answer("⚠️ هیچ مبحثی برای ویرایش وجود ندارد!")
        return
    
    keyboard = []
    for topic in topics:
        topic_id, name, description, is_active = topic
        status_icon = "✅" if is_active else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{status_icon} {name}", 
            callback_data=f"edit_topic_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به مدیریت مباحث", callback_data="admin_manage_topics")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "✏️ ویرایش مبحث:\n\n"
        "لطفاً مبحث مورد نظر برای ویرایش را انتخاب کنید:",
        reply_markup=reply_markup
        )
async def admin_delete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند حذف مبحث"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    topics = get_all_topics()
    
    if not topics:
        await update.callback_query.answer("⚠️ هیچ مبحثی برای حذف وجود ندارد!")
        return
    
    keyboard = []
    for topic in topics:
        topic_id, name, description, is_active = topic
        # بررسی آیا مبحث دارای سوال است یا نه
        questions_count = get_questions_count_by_topic(topic_id)
        has_questions = questions_count[0][0] > 0 if questions_count else False
        warning_icon = "⚠️" if has_questions else ""
        
        keyboard.append([InlineKeyboardButton(
            f"{warning_icon} {name}", 
            callback_data=f"delete_topic_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به مدیریت مباحث", callback_data="admin_manage_topics")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "❌ حذف مبحث:\n\n"
        "⚠️ توجه: حذف مباحثی که دارای سوال هستند ممکن است باعث مشکلات در آزمون‌ها شود!\n\n"
        "لطفاً مبحث مورد نظر برای حذف را انتخاب کنید:",
        reply_markup=reply_markup
    )
async def admin_view_topic_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده سوالات یک مبحث"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    topics = get_all_topics()
    
    if not topics:
        await update.callback_query.answer("⚠️ هیچ مبحثی وجود ندارد!")
        return
    
    keyboard = []
    for topic in topics:
        topic_id, name, description, is_active = topic
        questions_count = get_questions_count_by_topic(topic_id)
        count = questions_count[0][0] if questions_count else 0
        
        keyboard.append([InlineKeyboardButton(
            f"📚 {name} ({count} سوال)", 
            callback_data=f"view_topic_questions_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به مدیریت مباحث", callback_data="admin_manage_topics")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🔍 مشاهده سوالات مبحث:\n\n"
        "لطفاً مبحث مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )
async def start_topic_editing(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """شروع ویرایش مبحث"""
    topic_info = get_topic_by_id(topic_id)
    if not topic_info:
        await update.callback_query.answer("❌ مبحث یافت نشد!")
        return
    
    topic_id, name, description, is_active = topic_info[0]
    
    context.user_data['editing_topic'] = {
        'topic_id': topic_id,
        'current_name': name,
        'current_description': description or '',
        'current_status': is_active,
        'step': 'editing'
    }
    
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_topic_name")],
        [InlineKeyboardButton("📝 ویرایش توضیحات", callback_data="edit_topic_description")],
        [InlineKeyboardButton("🔄 تغییر وضعیت فعال/غیرفعال", callback_data=f"toggle_topic_status_{topic_id}")],
        [InlineKeyboardButton("🔙 بازگشت به ویرایش مباحث", callback_data="admin_edit_topic")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_text = "✅ فعال" if is_active else "❌ غیرفعال"
    
    await update.callback_query.edit_message_text(
        f"✏️ ویرایش مبحث:\n\n"
        f"📌 نام فعلی: {name}\n"
        f"📝 توضیحات: {description or 'ندارد'}\n"
        f"📊 وضعیت: {status_text}\n\n"
        f"لطفاً عملیات مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def edit_topic_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست نام جدید برای مبحث"""
    context.user_data['editing_topic']['step'] = 'waiting_for_new_name'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_topic_editing")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "✏️ ویرایش نام مبحث:\n\n"
        "لطفاً نام جدید مبحث را وارد کنید:",
        reply_markup=reply_markup
    )

async def edit_topic_description_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست توضیحات جدید برای مبحث"""
    context.user_data['editing_topic']['step'] = 'waiting_for_new_description'
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_topic_editing")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📝 ویرایش توضیحات مبحث:\n\n"
        "لطفاً توضیحات جدید مبحث را وارد کنید:\n\n"
        "💡 می‌توانید 'حذف' را وارد کنید تا توضیحات حذف شود.",
        reply_markup=reply_markup
    )
async def confirm_topic_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """تأیید حذف مبحث"""
    topic_info = get_topic_by_id(topic_id)
    if not topic_info:
        await update.callback_query.answer("❌ مبحث یافت نشد!")
        return
    
    topic_id, name, description, is_active = topic_info[0]
    
    # بررسی تعداد سوالات
    questions_count = get_questions_count_by_topic(topic_id)
    question_count = questions_count[0][0] if questions_count else 0
    
    warning_text = ""
    if question_count > 0:
        warning_text = f"\n⚠️ هشدار: این مبحث دارای {question_count} سوال است!\nحذف آن ممکن است باعث مشکلات در آزمون‌ها شود."
    
    keyboard = [
        [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"confirm_delete_topic_{topic_id}")],
        [InlineKeyboardButton("❌ خیر، انصراف", callback_data="admin_delete_topic")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"❌ تأیید حذف مبحث:\n\n"
        f"📌 نام: {name}\n"
        f"📝 توضیحات: {description or 'ندارد'}\n"
        f"📊 تعداد سوالات: {question_count}"
        f"{warning_text}\n\n"
        f"آیا از حذف این مبحث اطمینان دارید؟",
        reply_markup=reply_markup
    )

async def delete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """حذف نهایی مبحث"""
    topic_info = get_topic_by_id(topic_id)
    if not topic_info:
        await update.callback_query.answer("❌ مبحث یافت نشد!")
        return
    
    topic_name = topic_info[0][1]
    
    # حذف مبحث از دیتابیس
    result = execute_query("DELETE FROM topics WHERE id = %s", (topic_id,))
    
    if result:
        await update.callback_query.edit_message_text(
            f"✅ مبحث '{topic_name}' با موفقیت حذف شد!"
        )
    else:
        await update.callback_query.edit_message_text(
            f"❌ خطا در حذف مبحث '{topic_name}'!"
        )
async def toggle_topic_status(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """تغییر وضعیت فعال/غیرفعال مبحث"""
    topic_info = get_topic_by_id(topic_id)
    if not topic_info:
        await update.callback_query.answer("❌ مبحث یافت نشد!")
        return
    
    topic_id, name, description, is_active = topic_info[0]
    
    # تغییر وضعیت
    new_status = not is_active
    result = execute_query(
        "UPDATE topics SET is_active = %s WHERE id = %s", 
        (new_status, topic_id)
    )
    
    if result:
        status_text = "فعال" if new_status else "غیرفعال"
        await update.callback_query.answer(f"✅ وضعیت مبحث به {status_text} تغییر یافت")
        await start_topic_editing(update, context, topic_id)
    else:
        await update.callback_query.answer("❌ خطا در تغییر وضعیت!")
async def show_topic_questions(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """نمایش سوالات یک مبحث"""
    topic_info = get_topic_by_id(topic_id)
    if not topic_info:
        await update.callback_query.answer("❌ مبحث یافت نشد!")
        return
    
    topic_id, name, description, is_active = topic_info[0]
    
    # دریافت سوالات
    questions = execute_query(
        "SELECT id, question_image, correct_answer, is_active FROM question_bank WHERE topic_id = %s ORDER BY id",
        (topic_id,)
    )
    
    if not questions:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_view_topic_questions")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            f"📭 مبحث '{name}' هیچ سوالی ندارد.",
            reply_markup=reply_markup
        )
        return
    
    text = f"📚 سوالات مبحث: {name}\n\n"
    
    for i, question in enumerate(questions[:10]):  # نمایش 10 سوال اول
        question_id, question_image, correct_answer, question_active = question
        status = "✅" if question_active else "❌"
        text += f"{i+1}. سوال #{question_id} {status}\n"
        text += f"   ✅ پاسخ صحیح: گزینه {correct_answer}\n"
        text += f"   📸 فایل: {os.path.basename(question_image)}\n\n"
    
    if len(questions) > 10:
        text += f"📊 و {len(questions) - 10} سوال دیگر...\n\n"
    
    text += f"📈 جمع کل: {len(questions)} سوال"
    
    keyboard = [
        [InlineKeyboardButton("🔙 بازگشت به مشاهده مباحث", callback_data="admin_view_topic_questions")],
        [InlineKeyboardButton("📋 مدیریت سوالات این مبحث", callback_data=f"manage_topic_questions_{topic_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
async def process_topic_name_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش نام جدید مبحث"""
    try:
        new_name = update.message.text.strip()
        
        if len(new_name) < 2:
            await update.message.reply_text("❌ نام مبحث باید حداقل ۲ کاراکتر باشد!")
            return
        
        topic_data = context.user_data['editing_topic']
        
        # بررسی تکراری نبودن نام
        existing_topic = get_topic_by_name(new_name)
        if existing_topic and existing_topic[0][0] != topic_data['topic_id']:
            await update.message.reply_text("❌ مبحثی با این نام از قبل وجود دارد!")
            return
        
        # به‌روزرسانی نام در دیتابیس
        result = execute_query(
            "UPDATE topics SET name = %s WHERE id = %s",
            (new_name, topic_data['topic_id'])
        )
        
        if result:
            await update.message.reply_text(f"✅ نام مبحث به '{new_name}' تغییر یافت")
            topic_data['step'] = 'editing'
            await start_topic_editing(update, context, topic_data['topic_id'])
        else:
            await update.message.reply_text("❌ خطا در تغییر نام مبحث!")
        
    except Exception as e:
        logger.error(f"Error processing topic name edit: {e}")
        await update.message.reply_text("❌ خطا در پردازش نام جدید!")

async def process_topic_description_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش توضیحات جدید مبحث"""
    try:
        new_description = update.message.text.strip()
        
        if new_description.lower() == 'حذف':
            new_description = ""
        
        topic_data = context.user_data['editing_topic']
        
        # به‌روزرسانی توضیحات در دیتابیس
        result = execute_query(
            "UPDATE topics SET description = %s WHERE id = %s",
            (new_description, topic_data['topic_id'])
        )
        
        if result:
            if new_description:
                await update.message.reply_text("✅ توضیحات مبحث به‌روزرسانی شد")
            else:
                await update.message.reply_text("✅ توضیحات مبحث حذف شد")
            
            topic_data['step'] = 'editing'
            await start_topic_editing(update, context, topic_data['topic_id'])
        else:
            await update.message.reply_text("❌ خطا در تغییر توضیحات مبحث!")
        
    except Exception as e:
        logger.error(f"Error processing topic description edit: {e}")
        await update.message.reply_text("❌ خطا در پردازش توضیحات جدید!")

async def admin_add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن مبحث جدید"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'adding_topic'
    context.user_data['topic_data'] = {'step': 'name'}
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚 افزودن مبحث جدید:\n\n"
        "لطفاً نام مبحث را ارسال کنید:",
        reply_markup=reply_markup
    )

async def show_quiz_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quizzes = get_active_quizzes()
    
    if not quizzes:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("⚠️ در حال حاضر هیچ آزمون فعالی وجود ندارد.", reply_markup=reply_markup)
        return
    
    keyboard = []
    for quiz in quizzes:
        quiz_id, title, description, time_limit, created_by_admin = quiz
        admin_icon = " 👑" if created_by_admin else ""
        button_text = f"⏱ {time_limit} دقیقه - {title}{admin_icon}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"quiz_{quiz_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
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
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text("📭 شما هنوز هیچ آزمونی نداده‌اید.", reply_markup=reply_markup)
        return
    
    result_text = "📋 نتایج آزمون‌های شما:\n\n"
    
    for i, result in enumerate(results, 1):
        title, score, correct, wrong, unanswered, total_time, completed_at, user_rank, created_by_admin = result
        
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        completed_date = completed_at.strftime("%Y/%m/%d %H:%M")
        rank_text = f" | 🏆 رتبه: {user_rank}" if created_by_admin and user_rank else ""
        
        # نمایش نام آزمون به صورت واضح
        result_text += f"**{i}. {title}**\n"
        result_text += f"   ✅ {correct} صحیح | ❌ {wrong} غلط | ⏸️ {unanswered} بی‌پاسخ\n"
        result_text += f"   📈 نمره: {score:.1f}% | ⏱ زمان: {time_str}{rank_text}\n"
        result_text += f"   📅 تاریخ: {completed_date}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 راهنمای ربات آزمون:\n\n"
        "1. 📝 شرکت در آزمون: از بین آزمون‌های فعال یکی را انتخاب کنید\n"
        "2. 🎯 ساخت آزمون سفارشی: آزمون شخصی‌سازی شده بسازید\n"
        "3. 📊 نتایج من: مشاهده نتایج و رتبه‌های گذشته\n"
        "4. ⏱ زمان‌بندی: هر آزمون زمان محدودی دارد\n"
        "5. ✅ انتخاب پاسخ: روی گزینه‌ها کلیک کنید\n"
        "6. 🏷 علامت‌گذاری: سوالات مشکوک را علامت بگذارید\n"
        "7. 🔄 مرور: سوالات علامت‌گذاری شده را مرور کنید\n"
        "8. 🏆 رتبه‌بندی: در آزمون‌های ادمین رتبه کسب کنید\n\n"
        "موفق باشید! 🎯"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]
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
        
        correct_questions = []
        wrong_questions = []
        unanswered_questions_list = []
        
        for i, question in enumerate(questions):
            question_id, question_image, correct_answer = question
            user_answer = user_answers_dict.get(question_id)
            
            if user_answer is None:
                unanswered_questions += 1
                unanswered_questions_list.append(i + 1)
            elif user_answer == correct_answer:
                correct_answers += 1
                correct_questions.append(i + 1)
            else:
                wrong_answers += 1
                wrong_questions.append(i + 1)
        
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
            f"📝 تعداد پاسخ‌های شما: {len(user_answers)} از {total_questions}\n\n"
        )
        
        # اضافه کردن شماره سوالات به پیام کاربر
        if correct_questions:
            user_message += f"🔢 سوالات صحیح: {', '.join(map(str, correct_questions))}\n"
        if wrong_questions:
            user_message += f"🔢 سوالات غلط: {', '.join(map(str, wrong_questions))}\n"
        if unanswered_questions_list:
            user_message += f"🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions_list))}\n"
        
        user_message += f"\n💡 نکته: هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد.\n\n"
        user_message += f"با تشکر از مشارکت شما!"
        
        await context.bot.send_message(
            chat_id,
            user_message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])
        )
        
        logger.info(f"Quiz timeout handled for user {user_id}, score: {final_percentage:.2f}%")
        
    except Exception as e:
        logger.error(f"Error in quiz timeout: {e}")
        try:
            await context.bot.send_message(
                chat_id,
                "⏰ زمان آزمون به پایان رسید! پاسخ‌های شما ثبت شد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
            )
        except:
            pass

# توابع کمکی
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

def toggle_quiz_status(quiz_id: int):
    """تغییر وضعیت فعال/غیرفعال آزمون"""
    return execute_query('''
        UPDATE quizzes 
        SET is_active = NOT is_active 
        WHERE id = %s
    ''', (quiz_id,))
async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور دستی برای ارسال دعوت به کاربران قبلی"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ این دستور فقط برای ادمین است!")
        return
    
    await update.message.reply_text(
        "📨 شروع ارسال دعوت به کاربران قبلی...\n"
        "لطفاً منتظر بمانید."
    )
    
    users = get_all_users()
    successful_sends = 0
    failed_sends = 0
    
    # دریافت لینک ربات
    bot_username = (await context.bot.get_me()).username
    bot_link = f"https://t.me/{bot_username}"
    
    invitation_message = (
        "🎉 ربات جدید ما راه‌اندازی شد!\n\n"
        "برای استفاده از امکانات جدید، لطفاً روی لینک زیر کلیک کنید:\n"
        f"{bot_link}\n\n"
        "با تشکر از همراهی شما! 🤖"
    )
    
    for user in users:
        user_id = user[0]
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=invitation_message,
                disable_web_page_preview=False
            )
            successful_sends += 1
            
        except Exception as e:
            logger.error(f"Failed to send to user {user_id}: {e}")
            failed_sends += 1
        
        # تاخیر برای جلوگیری از محدودیت
        await asyncio.sleep(0.2)
    
    # نتیجه نهایی
    result_text = (
        f"✅ ارسال دعوت تکمیل شد!\n\n"
        f"📊 نتایج:\n"
        f"• 👥 کل کاربران: {len(users)}\n"
        f"• ✅ ارسال موفق: {successful_sends}\n"
        f"• ❌ ارسال ناموفق: {failed_sends}\n\n"
        f"لینک ربات: {bot_link}"
    )
    
    await update.message.reply_text(result_text)

def main():
    init_database()
    download_welcome_photo()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # همه هندلرها را اضافه کنید
    application.add_handler(CommandHandler("start", start))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.PHOTO, handle_admin_photos))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(CommandHandler("invite", invite_command))
    # در تابع main()، بعد از خطوط موجود، این خط را اضافه کنید:
    application.add_handler(MessageHandler(filters.Document.ALL, handle_admin_documents))
    
    # هندلر دیباگ را هم اضافه کنید
    application.add_handler(CommandHandler("debug", debug_context))
    
    print("🤖 ربات در حال اجرا است...")
    application.run_polling()

if __name__ == "__main__":
    main()
