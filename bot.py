import os
import logging
import psycopg2
import asyncio
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
import json
import uuid

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
QUESTION_IMAGES_DIR = "question_images"

# ایجاد دایرکتوری‌ها
os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(QUESTION_IMAGES_DIR, exist_ok=True)

# تنظیم لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# متغیرهای سراسری
db_connection = None

class DatabaseManager:
    """مدیریت ارتباط با دیتابیس"""
    
    @staticmethod
    def get_connection():
        global db_connection
        if db_connection is None or db_connection.closed:
            db_connection = psycopg2.connect(**DB_CONFIG)
        return db_connection
    
    @staticmethod
    def execute_query(query: str, params: tuple = None, return_id: bool = False, fetch_all: bool = True):
        """اجرای کوئری و بازگشت نتیجه"""
        try:
            connection = DatabaseManager.get_connection()
            cursor = connection.cursor()
            cursor.execute(query, params or ())
            
            if query.strip().upper().startswith('SELECT') or return_id:
                result = cursor.fetchall() if fetch_all else cursor.fetchone()
                connection.commit()
                return result
            else:
                connection.commit()
                return cursor.rowcount
                
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            if DatabaseManager.get_connection():
                DatabaseManager.get_connection().rollback()
            return None
    
    @staticmethod
    def init_database():
        """اتصال به دیتابیس و ایجاد جداول"""
        try:
            connection = DatabaseManager.get_connection()
            cursor = connection.cursor()
            
            # جدول کاربران
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    phone_number TEXT,
                    username TEXT,
                    full_name TEXT,
                    level TEXT DEFAULT 'beginner',
                    total_quizzes INTEGER DEFAULT 0,
                    total_correct_answers INTEGER DEFAULT 0,
                    total_wrong_answers INTEGER DEFAULT 0,
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
                    max_participants INTEGER DEFAULT 0,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
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
                    explanation TEXT,
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
                    time_spent REAL DEFAULT 0,
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
                    percentage REAL DEFAULT 0,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # جدول مباحث
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS topics (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    color TEXT DEFAULT '#3498db',
                    is_active BOOLEAN DEFAULT TRUE,
                    parent_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
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
                    explanation TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
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
                    is_public BOOLEAN DEFAULT FALSE,
                    used_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # جدول شرکت‌کنندگان آزمون
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_participants (
                    id SERIAL PRIMARY KEY,
                    quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(quiz_id, user_id)
                )
            ''')
            
            # جدول گزارش‌ها
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    quiz_id INTEGER REFERENCES quizzes(id) ON DELETE SET NULL,
                    question_id INTEGER REFERENCES question_bank(id) ON DELETE SET NULL,
                    report_type TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            connection.commit()
            logger.info("Database tables created successfully")
            
            # ایجاد مباحث پیش‌فرض
            DatabaseManager.create_default_topics()
            
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            if DatabaseManager.get_connection():
                DatabaseManager.get_connection().rollback()
    
    @staticmethod
    def create_default_topics():
        """ایجاد مباحث پیش‌فرض"""
        default_topics = [
            ("ریاضی", "سوالات ریاضی و محاسبات", "#e74c3c"),
            ("فیزیک", "سوالات فیزیک و علوم تجربی", "#3498db"),
            ("شیمی", "سوالات شیمی و ترکیبات", "#9b59b6"),
            ("ادبیات", "سوالات ادبیات و زبان فارسی", "#e67e22"),
            ("عربی", "سوالات زبان عربی", "#f1c40f"),
            ("دینی", "سوالات معارف اسلامی", "#1abc9c"),
            ("زبان انگلیسی", "سوالات زبان انگلیسی", "#e91e63"),
            ("زیست شناسی", "سوالات زیست شناسی", "#2ecc71"),
            ("هندسه", "سوالات هندسه و اشکال", "#34495e"),
            ("جبر", "سوالات جبر و معادلات", "#8e44ad")
        ]
        
        for name, description, color in default_topics:
            DatabaseManager.execute_query(
                "INSERT INTO topics (name, description, color) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
                (name, description, color)
            )

# توابع کاربران
class UserManager:
    @staticmethod
    def get_user(user_id: int):
        return DatabaseManager.execute_query("SELECT * FROM users WHERE user_id = %s", (user_id,))
    
    @staticmethod
    def add_user(user_id: int, phone_number: str, username: str, full_name: str):
        return DatabaseManager.execute_query('''
            INSERT INTO users (user_id, phone_number, username, full_name) 
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET 
            phone_number = EXCLUDED.phone_number,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name
        ''', (user_id, phone_number, username, full_name))
    
    @staticmethod
    def update_user_stats(user_id: int, correct_answers: int, wrong_answers: int):
        return DatabaseManager.execute_query('''
            UPDATE users 
            SET total_quizzes = total_quizzes + 1,
                total_correct_answers = total_correct_answers + %s,
                total_wrong_answers = total_wrong_answers + %s
            WHERE user_id = %s
        ''', (correct_answers, wrong_answers, user_id))
    
    @staticmethod
    def get_user_rankings():
        return DatabaseManager.execute_query('''
            SELECT user_id, full_name, total_correct_answers, total_quizzes,
                   (total_correct_answers::FLOAT / GREATEST(total_quizzes * 20, 1)) * 100 as success_rate
            FROM users 
            WHERE total_quizzes > 0
            ORDER BY success_rate DESC, total_correct_answers DESC
            LIMIT 50
        ''')

# توابع مباحث
class TopicManager:
    @staticmethod
    def get_all_topics():
        return DatabaseManager.execute_query("SELECT id, name, description, color FROM topics WHERE is_active = TRUE ORDER BY name")
    
    @staticmethod
    def get_topic(topic_id: int):
        return DatabaseManager.execute_query("SELECT id, name, description FROM topics WHERE id = %s AND is_active = TRUE", (topic_id,))
    
    @staticmethod
    def get_topic_by_name(name: str):
        return DatabaseManager.execute_query("SELECT id, name, description FROM topics WHERE name = %s AND is_active = TRUE", (name,))
    
    @staticmethod
    def add_topic(name: str, description: str = "", color: str = "#3498db"):
        return DatabaseManager.execute_query(
            "INSERT INTO topics (name, description, color) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING RETURNING id",
            (name, description, color), return_id=True
        )
    
    @staticmethod
    def update_topic(topic_id: int, name: str, description: str, color: str):
        return DatabaseManager.execute_query(
            "UPDATE topics SET name = %s, description = %s, color = %s WHERE id = %s",
            (name, description, color, topic_id)
        )
    
    @staticmethod
    def delete_topic(topic_id: int):
        return DatabaseManager.execute_query("UPDATE topics SET is_active = FALSE WHERE id = %s", (topic_id,))

# توابع بانک سوالات
class QuestionBankManager:
    @staticmethod
    def add_question(topic_id: int, question_image: str, correct_answer: int, explanation: str = ""):
        return DatabaseManager.execute_query('''
            INSERT INTO question_bank (topic_id, question_image, correct_answer, explanation)
            VALUES (%s, %s, %s, %s) RETURNING id
        ''', (topic_id, question_image, correct_answer, explanation), return_id=True)
    
    @staticmethod
    def get_questions_by_topics(topic_ids: List[int], difficulty: str = 'all', limit: int = 20):
        if not topic_ids:
            return []
        
        if difficulty == 'all':
            query = """
                SELECT id, question_image, correct_answer, auto_difficulty_score, explanation
                FROM question_bank 
                WHERE topic_id = ANY(%s) AND is_active = TRUE
                ORDER BY RANDOM() 
                LIMIT %s
            """
            return DatabaseManager.execute_query(query, (topic_ids, limit))
        else:
            # تعیین ترتیب بر اساس سطح سختی
            order_direction = "DESC" if difficulty == 'hard' else "ASC"
            query = f"""
                SELECT id, question_image, correct_answer, auto_difficulty_score, explanation
                FROM question_bank 
                WHERE topic_id = ANY(%s) AND is_active = TRUE
                ORDER BY auto_difficulty_score {order_direction}
                LIMIT %s
            """
            return DatabaseManager.execute_query(query, (topic_ids, limit))
    
    @staticmethod
    def get_question_count_by_topic(topic_id: int):
        result = DatabaseManager.execute_query(
            "SELECT COUNT(*) FROM question_bank WHERE topic_id = %s AND is_active = TRUE",
            (topic_id,)
        )
        return result[0][0] if result else 0
    
    @staticmethod
    def search_questions(search_term: str, topic_id: int = None):
        if topic_id:
            query = """
                SELECT id, question_image, correct_answer 
                FROM question_bank 
                WHERE (question_image LIKE %s OR explanation LIKE %s) 
                AND topic_id = %s AND is_active = TRUE
                LIMIT 20
            """
            return DatabaseManager.execute_query(query, (f"%{search_term}%", f"%{search_term}%", topic_id))
        else:
            query = """
                SELECT id, question_image, correct_answer 
                FROM question_bank 
                WHERE question_image LIKE %s OR explanation LIKE %s
                AND is_active = TRUE
                LIMIT 20
            """
            return DatabaseManager.execute_query(query, (f"%{search_term}%", f"%{search_term}%"))

# توابع آزمون‌ها
class QuizManager:
    @staticmethod
    def get_active_quizzes():
        return DatabaseManager.execute_query(
            "SELECT id, title, description, time_limit, created_by_admin FROM quizzes WHERE is_active = TRUE ORDER BY created_at DESC"
        )
    
    @staticmethod
    def create_quiz(title: str, description: str, time_limit: int, by_admin: bool = True, max_participants: int = 0):
        result = DatabaseManager.execute_query('''
            INSERT INTO quizzes (title, description, time_limit, is_active, created_by_admin, max_participants) 
            VALUES (%s, %s, %s, TRUE, %s, %s) RETURNING id
        ''', (title, description, time_limit, by_admin, max_participants), return_id=True)
        return result[0][0] if result else None
    
    @staticmethod
    def get_quiz_info(quiz_id: int):
        result = DatabaseManager.execute_query(
            "SELECT id, title, description, time_limit, is_active, created_by_admin, max_participants FROM quizzes WHERE id = %s", 
            (quiz_id,)
        )
        return result[0] if result else None
    
    @staticmethod
    def get_quiz_questions(quiz_id: int):
        return DatabaseManager.execute_query(
            "SELECT id, question_image, correct_answer, explanation FROM questions WHERE quiz_id = %s ORDER BY question_order, id", 
            (quiz_id,)
        )
    
    @staticmethod
    def add_question_to_quiz(quiz_id: int, question_image: str, correct_answer: int, question_order: int, explanation: str = ""):
        return DatabaseManager.execute_query('''
            INSERT INTO questions (quiz_id, question_image, correct_answer, question_order, explanation)
            VALUES (%s, %s, %s, %s, %s)
        ''', (quiz_id, question_image, correct_answer, question_order, explanation))
    
    @staticmethod
    def toggle_quiz_status(quiz_id: int):
        return DatabaseManager.execute_query('''
            UPDATE quizzes 
            SET is_active = NOT is_active 
            WHERE id = %s
        ''', (quiz_id,))
    
    @staticmethod
    def delete_quiz(quiz_id: int):
        return DatabaseManager.execute_query("DELETE FROM quizzes WHERE id = %s", (quiz_id,))
    
    @staticmethod
    def get_quiz_participants(quiz_id: int):
        return DatabaseManager.execute_query('''
            SELECT u.user_id, u.full_name, u.username, qp.joined_at
            FROM quiz_participants qp
            JOIN users u ON qp.user_id = u.user_id
            WHERE qp.quiz_id = %s
            ORDER BY qp.joined_at
        ''', (quiz_id,))

# توابع قالب‌های آزمون
class TemplateManager:
    @staticmethod
    def save_template(user_id: int, name: str, topics: List[int], question_count: int, time_limit: int, difficulty: str, is_public: bool = False):
        return DatabaseManager.execute_query('''
            INSERT INTO quiz_templates (user_id, name, topics, question_count, time_limit, difficulty_level, is_public)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        ''', (user_id, name, topics, question_count, time_limit, difficulty, is_public), return_id=True)
    
    @staticmethod
    def get_user_templates(user_id: int):
        return DatabaseManager.execute_query(
            "SELECT id, name, topics, question_count, time_limit, difficulty_level, is_public, used_count FROM quiz_templates WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,)
        )
    
    @staticmethod
    def get_public_templates():
        return DatabaseManager.execute_query(
            "SELECT id, name, topics, question_count, time_limit, difficulty_level, used_count FROM quiz_templates WHERE is_public = TRUE ORDER BY used_count DESC"
        )
    
    @staticmethod
    def increment_template_usage(template_id: int):
        return DatabaseManager.execute_query(
            "UPDATE quiz_templates SET used_count = used_count + 1 WHERE id = %s",
            (template_id,)
        )

# توابع نتایج و رتبه‌بندی
class ResultsManager:
    @staticmethod
    def save_user_answer(user_id: int, quiz_id: int, question_id: int, answer: int, time_spent: float = 0):
        return DatabaseManager.execute_query('''
            INSERT INTO user_answers (user_id, quiz_id, question_id, selected_answer, time_spent) 
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, quiz_id, question_id) 
            DO UPDATE SET selected_answer = EXCLUDED.selected_answer, time_spent = EXCLUDED.time_spent, answered_at = CURRENT_TIMESTAMP
        ''', (user_id, quiz_id, question_id, answer, time_spent))
    
    @staticmethod
    def get_user_answers(user_id: int, quiz_id: int):
        return DatabaseManager.execute_query(
            "SELECT question_id, selected_answer, time_spent FROM user_answers WHERE user_id = %s AND quiz_id = %s",
            (user_id, quiz_id)
        )
    
    @staticmethod
    def clear_user_answers(user_id: int, quiz_id: int):
        return DatabaseManager.execute_query(
            "DELETE FROM user_answers WHERE user_id = %s AND quiz_id = %s",
            (user_id, quiz_id)
        )
    
    @staticmethod
    def save_result(user_id: int, quiz_id: int, score: float, total_time: int, correct_answers: int, wrong_answers: int, unanswered_questions: int):
        # محاسبه درصد
        total_questions = correct_answers + wrong_answers + unanswered_questions
        percentage = (score / total_questions) * 100 if total_questions > 0 else 0
        
        # ذخیره نتیجه
        result = DatabaseManager.execute_query('''
            INSERT INTO results (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions, percentage) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        ''', (user_id, quiz_id, score, total_time, correct_answers, wrong_answers, unanswered_questions, percentage), return_id=True)
        
        if result:
            # به‌روزرسانی رتبه‌ها
            ResultsManager.update_ranks_for_quiz(quiz_id)
            # به‌روزرسانی آمار کاربر
            UserManager.update_user_stats(user_id, correct_answers, wrong_answers)
        
        return result
    
    @staticmethod
    def update_ranks_for_quiz(quiz_id: int):
        """به‌روزرسانی رتبه‌های یک آزمون"""
        DatabaseManager.execute_query('''
            WITH ranked_results AS (
                SELECT id,
                       ROW_NUMBER() OVER (ORDER BY percentage DESC, total_time ASC) as new_rank
                FROM results 
                WHERE quiz_id = %s
            )
            UPDATE results 
            SET user_rank = ranked_results.new_rank
            FROM ranked_results
            WHERE results.id = ranked_results.id
        ''', (quiz_id,))
    
    @staticmethod
    def get_quiz_rankings(quiz_id: int):
        """دریافت رتبه‌بندی کامل یک آزمون"""
        return DatabaseManager.execute_query('''
            SELECT u.full_name, r.percentage, r.correct_answers, r.total_time, r.user_rank
            FROM results r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.quiz_id = %s
            ORDER BY r.user_rank
            LIMIT 100
        ''', (quiz_id,))
    
    @staticmethod
    def get_user_rank(user_id: int, quiz_id: int):
        """دریافت رتبه کاربر در یک آزمون"""
        result = DatabaseManager.execute_query(
            "SELECT user_rank FROM results WHERE user_id = %s AND quiz_id = %s",
            (user_id, quiz_id)
        )
        return result[0][0] if result else None
    
    @staticmethod
    def get_user_results(user_id: int, limit: int = 10):
        return DatabaseManager.execute_query('''
            SELECT q.title, r.percentage, r.correct_answers, r.wrong_answers, r.unanswered_questions, 
                   r.total_time, r.completed_at, r.user_rank, q.created_by_admin
            FROM results r
            JOIN quizzes q ON r.quiz_id = q.id
            WHERE r.user_id = %s
            ORDER BY r.completed_at DESC
            LIMIT %s
        ''', (user_id, limit))
    
    @staticmethod
    def get_all_results():
        return DatabaseManager.execute_query('''
            SELECT u.full_name, q.title, r.percentage, r.total_time, r.completed_at 
            FROM results r
            JOIN users u ON r.user_id = u.user_id
            JOIN quizzes q ON r.quiz_id = q.id
            ORDER BY r.completed_at DESC
            LIMIT 100
        ''')

# تحلیل‌گر سطح سختی
class DifficultyAnalyzer:
    @staticmethod
    def update_question_difficulty(question_id: int, is_correct: bool, time_spent: float):
        """به‌روزرسانی سطح سختی سوال بر اساس پاسخ کاربر"""
        # دریافت داده‌های فعلی
        current_data = DatabaseManager.execute_query(
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
        
        # تعیین سطح سختی بر اساس امتیاز
        if difficulty_score < 0.3:
            level = 'easy'
        elif difficulty_score < 0.7:
            level = 'medium'
        else:
            level = 'hard'
        
        # ذخیره در دیتابیس
        DatabaseManager.execute_query('''
            UPDATE question_bank 
            SET total_attempts = %s, correct_attempts = %s, average_time = %s, 
                auto_difficulty_score = %s, difficulty_level = %s
            WHERE id = %s
        ''', (new_total, new_correct, new_avg_time, difficulty_score, level, question_id))
    
    @staticmethod
    def calculate_difficulty_score(success_rate: float, avg_time: float) -> float:
        """محاسبه امتیاز سختی سوال"""
        # نرمال‌سازی زمان (فرض: زمان ایده‌آل 30 ثانیه)
        time_factor = min(avg_time / 60.0, 1.0)  # نرمال‌سازی به دقیقه
        
        # ترکیب نرخ موفقیت و زمان
        difficulty = (1 - success_rate) * 0.7 + time_factor * 0.3
        return max(0.0, min(1.0, difficulty))

# سیستم گزارش‌دهی
class ReportManager:
    @staticmethod
    def create_report(user_id: int, report_type: str, description: str, quiz_id: int = None, question_id: int = None):
        return DatabaseManager.execute_query('''
            INSERT INTO reports (user_id, quiz_id, question_id, report_type, description)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        ''', (user_id, quiz_id, question_id, report_type, description), return_id=True)
    
    @staticmethod
    def get_pending_reports():
        return DatabaseManager.execute_query('''
            SELECT r.id, u.full_name, r.report_type, r.description, r.created_at
            FROM reports r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        ''')
    
    @staticmethod
    def update_report_status(report_id: int, status: str):
        return DatabaseManager.execute_query(
            "UPDATE reports SET status = %s WHERE id = %s",
            (status, report_id)
        )

# توابع اصلی ربات
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    user_data = UserManager.get_user(user_id)
    if not user_data:
        UserManager.add_user(user_id, "", user.username, user.full_name)
        
        admin_message = (
            "👤 کاربر جدید ثبت نام کرد:\n"
            f"🆔 آیدی: {user.id}\n"
            f"👤 نام: {user.full_name}\n"
            f"🔗 یوزرنیم: @{user.username if user.username else 'ندارد'}\n"
            f"📅 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        try:
            await context.bot.send_message(ADMIN_ID, admin_message)
        except Exception as e:
            logger.error(f"Error sending message to admin: {e}")
    
    has_start_param = context.args and len(context.args) > 0
    
    if has_start_param:
        welcome_message = (
            "🎯 قبل از آزمون اصلی، در محیطی رقابتی سطح خودت رو بسنج!\n\n"
            "✨ **ویژگی‌های جدید ربات:**\n"
            "• 🎯 ساخت آزمون سفارشی\n" 
            "• 📚 بانک سوالات هوشمند\n"
            "• 🏆 سیستم رتبه‌بندی\n"
            "• 📊 تحلیل پیشرفت\n"
            "• 🔍 جستجوی پیشرفته\n\n"
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
        await update.message.reply_text("🤖 به ربات آزمون پیشرفته خوش آمدید!")

    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 شرکت در آزمون", callback_data="take_quiz")],
        [InlineKeyboardButton("🎯 ساخت آزمون سفارشی", callback_data="create_custom_quiz")],
        [InlineKeyboardButton("📊 نتایج و آمار", callback_data="my_results")],
        [InlineKeyboardButton("🏆 رتبه‌بندی جهانی", callback_data="global_rankings")],
        [InlineKeyboardButton("📚 بانک سوالات", callback_data="question_bank")],
        [InlineKeyboardButton("ℹ️ راهنما و پشتیبانی", callback_data="help")]
    ]
    
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🔧 پنل ادمین", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🎯 **منوی اصلی ربات آزمون**\n\n"
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🎯 **منوی اصلی ربات آزمون**\n\n"
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # هندلرهای اصلی
    if data == "take_quiz":
        await show_quiz_list(update, context)
    elif data == "create_custom_quiz":
        await start_custom_quiz_creation(update, context)
    elif data == "my_results":
        await show_my_results(update, context)
    elif data == "global_rankings":
        await show_global_rankings(update, context)
    elif data == "question_bank":
        await show_question_bank(update, context)
    elif data == "help":
        await show_help(update, context)
    elif data == "admin_panel":
        await show_admin_panel(update, context)
    
    # هندلرهای آزمون
    elif data.startswith("quiz_"):
        quiz_id = int(data.split("_")[1])
        await start_quiz(update, context, quiz_id)
    elif data.startswith("ans_"):
        parts = data.split("_")
        quiz_id = int(parts[1])
        question_index = int(parts[2])
        answer = int(parts[3])
        await handle_answer(update, context, quiz_id, question_index, answer)
    elif data.startswith("nav_"):
        new_index = int(data.split("_")[1])
        await navigate_to_question(update, context, new_index)
    elif data.startswith("submit_"):
        quiz_id = int(data.split("_")[1])
        await submit_quiz(update, context, quiz_id)
    elif data == "main_menu":
        await show_main_menu(update, context)
    
    # هندلرهای ادمین
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
    elif data == "admin_reports":
        await admin_reports(update, context)
    elif data == "admin_broadcast":
        await admin_broadcast_message(update, context)
    elif data.startswith("admin_quiz_"):
        parts = data.split("_")
        action = parts[2]
        quiz_id = int(parts[3])
        if action == "toggle":
            await admin_toggle_quiz(update, context, quiz_id)
        elif action == "delete":
            await admin_delete_quiz(update, context, quiz_id)
        elif action == "ranking":
            await show_quiz_rankings(update, context, quiz_id)
        elif action == "participants":
            await show_quiz_participants(update, context, quiz_id)
    
    # هندلرهای قالب‌های آزمون
    elif data.startswith("template_"):
        parts = data.split("_")
        action = parts[1]
        if action == "create":
            await create_quiz_from_template(update, context, int(parts[2]))
        elif action == "public":
            await show_public_templates(update, context)
    
    # هندلرهای بانک سوالات
    elif data.startswith("bank_"):
        parts = data.split("_")
        action = parts[1]
        if action == "search":
            await search_question_bank(update, context)
        elif action == "report":
            await report_question(update, context, int(parts[2]))
    
    # هندلرهای مباحث
    elif data.startswith("topic_"):
        parts = data.split("_")
        action = parts[1]
        if action == "select":
            await handle_topic_selection(update, context, int(parts[2]))
        elif action == "done":
            await finish_topic_selection(update, context)
    
    # هندلرهای ساخت آزمون سفارشی
    elif data.startswith("custom_"):
        parts = data.split("_")
        action = parts[1]
        if action == "type":
            await select_custom_quiz_type(update, context, parts[2])
        elif action == "difficulty":
            await select_custom_quiz_difficulty(update, context, parts[2])
        elif action == "count":
            await select_custom_quiz_count(update, context, int(parts[2]))
        elif action == "time":
            await select_custom_quiz_time(update, context, int(parts[2]))
        elif action == "start":
            await start_custom_quiz(update, context)
        elif action == "save":
            await save_custom_template(update, context)

# سیستم ساخت آزمون سفارشی
async def start_custom_quiz_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ساخت آزمون سفارشی"""
    user_id = update.effective_user.id
    
    context.user_data['custom_quiz'] = {
        'step': 'type',
        'topics': [],
        'question_count': 20,
        'time_limit': 30,
        'difficulty': 'all',
        'type': 'instant'
    }
    
    keyboard = [
        [InlineKeyboardButton("🎯 آزمون فوری", callback_data="custom_type_instant")],
        [InlineKeyboardButton("💾 ذخیره قالب", callback_data="custom_type_template")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎯 **ساخت آزمون سفارشی**\n\n"
        "لطفاً نوع آزمون را انتخاب کنید:\n\n"
        "• 🎯 **آزمون فوری**: شروع سریع آزمون\n"
        "• 💾 **ذخیره قالب**: ساخت و ذخیره قالب برای استفاده مجدد\n",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_custom_quiz_type(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_type: str):
    """انتخاب نوع آزمون سفارشی"""
    context.user_data['custom_quiz']['type'] = quiz_type
    context.user_data['custom_quiz']['step'] = 'topics'
    
    # نمایش لیست مباحث برای انتخاب
    topics = TopicManager.get_all_topics()
    
    if not topics:
        await update.callback_query.edit_message_text(
            "⚠️ هیچ مبحثی تعریف نشده است. لطفاً با ادمین تماس بگیرید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )
        return
    
    keyboard = []
    for topic in topics:
        topic_id, name, description, color = topic
        question_count = QuestionBankManager.get_question_count_by_topic(topic_id)
        keyboard.append([InlineKeyboardButton(
            f"📚 {name} ({question_count} سوال)", 
            callback_data=f"topic_select_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("✅ اتمام انتخاب", callback_data="topic_done")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚 **انتخاب مباحث**\n\n"
        "لطفاً مباحث مورد نظر خود را انتخاب کنید:\n\n"
        "💡 می‌توانید چند مبحث را انتخاب کنید",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: int):
    """مدیریت انتخاب مباحث"""
    custom_quiz = context.user_data.get('custom_quiz', {})
    topics = custom_quiz.get('topics', [])
    
    if topic_id in topics:
        topics.remove(topic_id)
        await update.callback_query.answer("❌ مبحث حذف شد")
    else:
        topics.append(topic_id)
        await update.callback_query.answer("✅ مبحث اضافه شد")
    
    custom_quiz['topics'] = topics
    context.user_data['custom_quiz'] = custom_quiz
    
    # به‌روزرسانی پیام با تعداد انتخاب‌شده
    topics_list = TopicManager.get_all_topics()
    selected_count = len(topics)
    
    keyboard = []
    for topic in topics_list:
        topic_id, name, description, color = topic
        question_count = QuestionBankManager.get_question_count_by_topic(topic_id)
        is_selected = topic_id in topics
        icon = "✅" if is_selected else "📚"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {name} ({question_count} سوال)", 
            callback_data=f"topic_select_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("✅ اتمام انتخاب", callback_data="topic_done")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📚 **انتخاب مباحث**\n\n"
        f"✅ **{selected_count} مبحث انتخاب شده**\n\n"
        f"لطفاً مباحث مورد نظر خود را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def finish_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اتمام انتخاب مباحث و رفتن به مرحله بعد"""
    custom_quiz = context.user_data.get('custom_quiz', {})
    topics = custom_quiz.get('topics', [])
    
    if not topics:
        await update.callback_query.answer("⚠️ لطفاً حداقل یک مبحث انتخاب کنید")
        return
    
    context.user_data['custom_quiz']['step'] = 'difficulty'
    
    keyboard = [
        [InlineKeyboardButton("🟢 آسان", callback_data="custom_difficulty_easy")],
        [InlineKeyboardButton("🟡 متوسط", callback_data="custom_difficulty_medium")],
        [InlineKeyboardButton("🔴 سخت", callback_data="custom_difficulty_hard")],
        [InlineKeyboardButton("🌈 ترکیبی", callback_data="custom_difficulty_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # نمایش مباحث انتخاب شده
    selected_topics_text = ""
    for topic_id in topics:
        topic = TopicManager.get_topic(topic_id)
        if topic:
            selected_topics_text += f"• {topic[0][1]}\n"
    
    await update.callback_query.edit_message_text(
        f"📚 **مباحث انتخاب شده:**\n{selected_topics_text}\n"
        "🎯 **سطح سختی سوالات**\n\n"
        "لطفاً سطح سختی سوالات را انتخاب کنید:\n\n"
        "• 🟢 آسان: سوالات با نرخ موفقیت بالا\n"
        "• 🟡 متوسط: ترکیبی از سوالات\n" 
        "• 🔴 سخت: سوالات چالشی\n"
        "• 🌈 ترکیبی: همه سطوح\n",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_custom_quiz_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE, difficulty: str):
    """انتخاب سطح سختی آزمون سفارشی"""
    context.user_data['custom_quiz']['difficulty'] = difficulty
    context.user_data['custom_quiz']['step'] = 'count'
    
    difficulty_names = {
        'easy': 'آسان 🟢',
        'medium': 'متوسط 🟡', 
        'hard': 'سخت 🔴',
        'all': 'ترکیبی 🌈'
    }
    
    keyboard = [
        [InlineKeyboardButton("10 سوال", callback_data="custom_count_10")],
        [InlineKeyboardButton("20 سوال", callback_data="custom_count_20")],
        [InlineKeyboardButton("30 سوال", callback_data="custom_count_30")],
        [InlineKeyboardButton("40 سوال", callback_data="custom_count_40")],
        [InlineKeyboardButton("50 سوال", callback_data="custom_count_50")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="topic_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"🎯 **سطح سختی:** {difficulty_names[difficulty]}\n\n"
        "📊 **تعداد سوالات**\n\n"
        "لطفاً تعداد سوالات آزمون را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_custom_quiz_count(update: Update, context: ContextTypes.DEFAULT_TYPE, count: int):
    """انتخاب تعداد سوالات آزمون سفارشی"""
    context.user_data['custom_quiz']['question_count'] = count
    context.user_data['custom_quiz']['step'] = 'time'
    
    keyboard = [
        [InlineKeyboardButton("15 دقیقه", callback_data="custom_time_15")],
        [InlineKeyboardButton("30 دقیقه", callback_data="custom_time_30")],
        [InlineKeyboardButton("45 دقیقه", callback_data="custom_time_45")],
        [InlineKeyboardButton("60 دقیقه", callback_data="custom_time_60")],
        [InlineKeyboardButton("90 دقیقه", callback_data="custom_time_90")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="custom_type_instant")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📊 **تعداد سوالات:** {count} سوال\n\n"
        "⏱ **زمان آزمون**\n\n"
        "لطفاً زمان آزمون را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def select_custom_quiz_time(update: Update, context: ContextTypes.DEFAULT_TYPE, time_limit: int):
    """انتخاب زمان آزمون سفارشی"""
    context.user_data['custom_quiz']['time_limit'] = time_limit
    context.user_data['custom_quiz']['step'] = 'preview'
    
    await show_custom_quiz_preview(update, context)

async def show_custom_quiz_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پیش‌نمایش آزمون سفارشی"""
    custom_quiz = context.user_data.get('custom_quiz', {})
    
    # محاسبه تعداد کل سوالات قابل دسترس
    total_available_questions = 0
    for topic_id in custom_quiz['topics']:
        total_available_questions += QuestionBankManager.get_question_count_by_topic(topic_id)
    
    # نمایش اطلاعات آزمون
    topics_text = ""
    for topic_id in custom_quiz['topics']:
        topic = TopicManager.get_topic(topic_id)
        if topic:
            topic_name = topic[0][1]
            topic_count = QuestionBankManager.get_question_count_by_topic(topic_id)
            topics_text += f"• {topic_name} ({topic_count} سوال)\n"
    
    difficulty_names = {
        'easy': 'آسان 🟢',
        'medium': 'متوسط 🟡',
        'hard': 'سخت 🔴', 
        'all': 'ترکیبی 🌈'
    }
    
    preview_text = (
        f"🎯 **پیش‌نمایش آزمون سفارشی**\n\n"
        f"📚 **مباحث:**\n{topics_text}\n"
        f"🎯 **سطح سختی:** {difficulty_names[custom_quiz['difficulty']]}\n"
        f"📊 **تعداد سوالات:** {custom_quiz['question_count']} سوال\n"
        f"⏱ **زمان آزمون:** {custom_quiz['time_limit']} دقیقه\n"
        f"📈 **سوالات موجود:** {total_available_questions} سوال\n\n"
    )
    
    if total_available_questions < custom_quiz['question_count']:
        preview_text += f"⚠️ **توجه:** تعداد سوالات درخواستی بیشتر از سوالات موجود است!\n\n"
    
    keyboard = []
    
    if custom_quiz['type'] == 'instant':
        keyboard.append([InlineKeyboardButton("🚀 شروع آزمون", callback_data="custom_start")])
    else:
        preview_text += "💾 این آزمون به عنوان قالب ذخیره خواهد شد."
        keyboard.append([InlineKeyboardButton("💾 ذخیره قالب و شروع", callback_data="custom_save")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="custom_count_20")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        preview_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def start_custom_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع آزمون سفارشی"""
    user_id = update.effective_user.id
    custom_quiz = context.user_data.get('custom_quiz', {})
    
    # انتخاب سوالات از بانک سوالات
    questions = QuestionBankManager.get_questions_by_topics(
        custom_quiz['topics'],
        custom_quiz['difficulty'],
        custom_quiz['question_count']
    )
    
    if not questions:
        await update.callback_query.edit_message_text(
            "❌ هیچ سوالی برای معیارهای انتخاب شده یافت نشد!\n\n"
            "لطفاً مباحث یا سطح سختی دیگری انتخاب کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="create_custom_quiz")]])
        )
        return
    
    # ایجاد آزمون موقت
    quiz_title = f"آزمون سفارشی - {datetime.now().strftime('%Y/%m/%d %H:%M')}"
    quiz_id = QuizManager.create_quiz(
        quiz_title,
        "آزمون سفارشی ایجاد شده توسط کاربر",
        custom_quiz['time_limit'],
        by_admin=False
    )
    
    if not quiz_id:
        await update.callback_query.edit_message_text(
            "❌ خطا در ایجاد آزمون!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )
        return
    
    # افزودن سوالات به آزمون
    for i, question in enumerate(questions):
        question_id, question_image, correct_answer, difficulty_score, explanation = question
        QuizManager.add_question_to_quiz(
            quiz_id,
            question_image,
            correct_answer,
            i + 1,
            explanation
        )
    
    # شروع آزمون
    await start_quiz(update, context, quiz_id)

async def save_custom_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره قالب آزمون سفارشی"""
    user_id = update.effective_user.id
    custom_quiz = context.user_data.get('custom_quiz', {})
    
    # درخواست نام برای قالب
    context.user_data['template_step'] = 'name'
    
    await update.callback_query.edit_message_text(
        "💾 **ذخیره قالب آزمون**\n\n"
        "لطفاً یک نام برای قالب آزمون خود وارد کنید:\n\n"
        "مثال: آزمون ریاضی پیشرفته",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="custom_start")]])
    )

# سیستم رتبه‌بندی و نتایج
async def show_my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش نتایج و آمار کاربر"""
    user_id = update.effective_user.id
    
    results = ResultsManager.get_user_results(user_id, 10)
    
    if not results:
        await update.callback_query.edit_message_text(
            "📭 شما هنوز در هیچ آزمونی شرکت نکرده‌اید!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )
        return
    
    result_text = "📋 **نتایج آزمون‌های شما**\n\n"
    
    for i, result in enumerate(results, 1):
        title, percentage, correct, wrong, unanswered, total_time, completed_at, rank, by_admin = result
        
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        completed_date = completed_at.strftime("%Y/%m/%d %H:%M")
        
        result_text += f"**{i}. {title}**\n"
        result_text += f"✅ {correct} | ❌ {wrong} | ⏸️ {unanswered}\n"
        result_text += f"📈 {percentage:.1f}% | ⏱ {time_str}\n"
        
        if by_admin and rank:
            result_text += f"🏆 رتبه: {rank}\n"
        
        result_text += f"📅 {completed_date}\n\n"
    
    # آمار کلی کاربر
    user_data = UserManager.get_user(user_id)
    if user_data and user_data[0][5] > 0:  # total_quizzes > 0
        user_stats = user_data[0]
        total_quizzes = user_stats[5]
        total_correct = user_stats[6]
        total_wrong = user_stats[7]
        total_answered = total_correct + total_wrong
        success_rate = (total_correct / total_answered * 100) if total_answered > 0 else 0
        
        result_text += f"📊 **آمار کلی شما:**\n"
        result_text += f"• 📝 تعداد آزمون‌ها: {total_quizzes}\n"
        result_text += f"• ✅ پاسخ‌های صحیح: {total_correct}\n"
        result_text += f"• ❌ پاسخ‌های غلط: {total_wrong}\n"
        result_text += f"• 📈 نرخ موفقیت: {success_rate:.1f}%\n"
    
    keyboard = [
        [InlineKeyboardButton("📈 نمودار پیشرفت", callback_data="progress_chart")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_global_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش رتبه‌بندی جهانی کاربران"""
    rankings = UserManager.get_user_rankings()
    
    if not rankings:
        await update.callback_query.edit_message_text(
            "📊 هنوز هیچ کاربری در آزمون‌ها شرکت نکرده است!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )
        return
    
    rankings_text = "🏆 **رتبه‌بندی جهانی**\n\n"
    
    for i, ranking in enumerate(rankings[:20], 1):
        user_id, full_name, total_correct, total_quizzes, success_rate = ranking
        
        medal = ""
        if i == 1: medal = "🥇 "
        elif i == 2: medal = "🥈 " 
        elif i == 3: medal = "🥉 "
        
        rankings_text += f"{medal}**{i}. {full_name}**\n"
        rankings_text += f"   ✅ {total_correct} پاسخ صحیح | 📈 {success_rate:.1f}%\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        rankings_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_quiz_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int = None):
    """نمایش رتبه‌بندی یک آزمون خاص (فقط برای ادمین)"""
    if not quiz_id:
        # نمایش لیست آزمون‌ها برای انتخاب
        quizzes = QuizManager.get_active_quizzes()
        
        if not quizzes:
            await update.callback_query.edit_message_text(
                "⚠️ هیچ آزمون فعالی وجود ندارد!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]])
            )
            return
        
        keyboard = []
        for quiz in quizzes:
            quiz_id, title, description, time_limit, by_admin = quiz
            if by_admin:  # فقط آزمون‌های ادمین
                keyboard.append([InlineKeyboardButton(
                    f"📊 {title}", 
                    callback_data=f"admin_quiz_ranking_{quiz_id}"
                )])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "📊 **مشاهده رتبه‌بندی آزمون**\n\n"
            "لطفاً آزمون مورد نظر را انتخاب کنید:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # نمایش رتبه‌بندی آزمون انتخاب شده
    rankings = ResultsManager.get_quiz_rankings(quiz_id)
    quiz_info = QuizManager.get_quiz_info(quiz_id)
    
    if not rankings:
        await update.callback_query.edit_message_text(
            "📭 هیچ نتیجه‌ای برای این آزمون ثبت نشده است!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_quiz_rankings")]])
        )
        return
    
    quiz_title = quiz_info[1] if quiz_info else "آزمون"
    rankings_text = f"🏆 **رتبه‌بندی: {quiz_title}**\n\n"
    
    for i, ranking in enumerate(rankings[:50], 1):
        full_name, percentage, correct_answers, total_time, rank = ranking
        
        time_str = f"{total_time // 60}:{total_time % 60:02d}"
        
        medal = ""
        if i == 1: medal = "🥇 "
        elif i == 2: medal = "🥈 "
        elif i == 3: medal = "🥉 "
        
        rankings_text += f"{medal}**{i}. {full_name}**\n"
        rankings_text += f"   📈 {percentage:.1f}% | ✅ {correct_answers} | ⏱ {time_str}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_quiz_rankings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        rankings_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# سیستم بانک سوالات
async def show_question_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی بانک سوالات"""
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی سوالات", callback_data="bank_search")],
        [InlineKeyboardButton("📚 بر اساس مبحث", callback_data="bank_by_topic")],
        [InlineKeyboardButton("📊 آمار بانک سوالات", callback_data="bank_stats")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "📚 **بانک سوالات**\n\n"
        "امکانات بانک سوالات هوشمند:\n\n"
        "• 🔍 جستجوی پیشرفته در سوالات\n"
        "• 📚 فیلتر بر اساس مبحث\n" 
        "• 📊 مشاهده آمار و تحلیل‌ها\n"
        "• 🎯 سوالات با سطح سختی خودکار\n",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def search_question_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع جستجو در بانک سوالات"""
    context.user_data['bank_action'] = 'searching'
    
    await update.callback_query.edit_message_text(
        "🔍 **جستجو در بانک سوالات**\n\n"
        "لطفاً کلیدواژه مورد نظر خود را ارسال کنید:\n\n"
        "💡 می‌توانید در متن سوالات یا توضیحات جستجو کنید.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="question_bank")]])
    )

# پنل ادمین گسترش یافته
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پنل ادمین پیشرفته"""
    if update.effective_user.id != ADMIN_ID:
        await update.callback_query.edit_message_text("دسترسی denied!")
        return
    
    # آمار سریع
    total_users = len(DatabaseManager.execute_query("SELECT user_id FROM users"))
    total_quizzes = len(DatabaseManager.execute_query("SELECT id FROM quizzes"))
    total_questions = len(DatabaseManager.execute_query("SELECT id FROM question_bank"))
    active_quizzes = len(DatabaseManager.execute_query("SELECT id FROM quizzes WHERE is_active = TRUE"))
    
    stats_text = (
        f"📊 **آمار سریع سیستم:**\n\n"
        f"• 👥 کاربران: {total_users} نفر\n"
        f"• 📝 آزمون‌ها: {total_quizzes} آزمون\n"
        f"• 🎯 سوالات بانک: {total_questions} سوال\n"
        f"• 🔥 آزمون‌های فعال: {active_quizzes} آزمون\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ ایجاد آزمون", callback_data="admin_create_quiz")],
        [InlineKeyboardButton("📋 مدیریت آزمون‌ها", callback_data="admin_manage_quizzes")],
        [InlineKeyboardButton("📊 رتبه‌بندی آزمون‌ها", callback_data="admin_quiz_rankings")],
        [InlineKeyboardButton("📚 مدیریت مباحث", callback_data="admin_manage_topics")],
        [InlineKeyboardButton("❓ افزودن سوال", callback_data="admin_add_question")],
        [InlineKeyboardButton("👥 مشاهده کاربران", callback_data="admin_view_users")],
        [InlineKeyboardButton("📈 مشاهده نتایج", callback_data="admin_view_results")],
        [InlineKeyboardButton("⚠️ گزارش‌ها", callback_data="admin_reports")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"🔧 **پنل مدیریت پیشرفته**\n\n{stats_text}",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_manage_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت مباحث توسط ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    topics = TopicManager.get_all_topics()
    
    if not topics:
        keyboard = [
            [InlineKeyboardButton("➕ افزودن مبحث", callback_data="admin_add_topic")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "📚 **مدیریت مباحث**\n\n"
            "هیچ مبحثی تعریف نشده است.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    topics_text = "📚 **لیست مباحث:**\n\n"
    keyboard = []
    
    for topic in topics:
        topic_id, name, description, color = topic
        question_count = QuestionBankManager.get_question_count_by_topic(topic_id)
        topics_text += f"• **{name}** ({question_count} سوال)\n   {description}\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"✏️ ویرایش {name}", 
            callback_data=f"admin_edit_topic_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("➕ افزودن مبحث جدید", callback_data="admin_add_topic")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        topics_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن سوال به بانک سوالات توسط ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'adding_question'
    context.user_data['question_data'] = {'step': 'topic'}
    
    # نمایش لیست مباحث برای انتخاب
    topics = TopicManager.get_all_topics()
    
    if not topics:
        await update.callback_query.edit_message_text(
            "❌ ابتدا باید مباحث را تعریف کنید!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]])
        )
        return
    
    keyboard = []
    for topic in topics:
        topic_id, name, description, color = topic
        keyboard.append([InlineKeyboardButton(
            f"📚 {name}", 
            callback_data=f"admin_select_topic_{topic_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "❓ **افزودن سوال به بانک**\n\n"
        "لطفاً مبحث سوال را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت گزارش‌های کاربران"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    reports = ReportManager.get_pending_reports()
    
    if not reports:
        await update.callback_query.edit_message_text(
            "✅ هیچ گزارش در حال انتظاری وجود ندارد!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]])
        )
        return
    
    reports_text = "⚠️ **گزارش‌های در حال انتظار:**\n\n"
    keyboard = []
    
    for i, report in enumerate(reports, 1):
        report_id, full_name, report_type, description, created_at = report
        reports_text += f"**{i}. {full_name}** - {report_type}\n"
        reports_text += f"📝 {description}\n"
        reports_text += f"📅 {created_at.strftime('%Y/%m/%d %H:%M')}\n\n"
        
        keyboard.append([
            InlineKeyboardButton("✅ تایید", callback_data=f"admin_approve_report_{report_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"admin_reject_report_{report_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        reports_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ادامه توابع اصلی آزمون (با بهبود سیستم رتبه‌بندی)
async def submit_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
    """ثبت نهایی پاسخ‌ها با سیستم رتبه‌بندی پیشرفته"""
    user_id = update.effective_user.id
    quiz_data = context.user_data.get('current_quiz')
    
    if not quiz_data or quiz_data['quiz_id'] != quiz_id:
        await update.callback_query.answer("خطا! لطفاً آزمون را دوباره شروع کنید.")
        return
    
    # محاسبه زمان صرف شده
    total_time = (datetime.now() - quiz_data['start_time']).seconds
    
    # محاسبه امتیاز با نمره منفی
    user_answers = ResultsManager.get_user_answers(user_id, quiz_id)
    user_answers_dict = {q_id: (ans, time) for q_id, ans, time in user_answers}
    
    score = 0
    total_questions = len(quiz_data['questions'])
    correct_answers = 0
    wrong_answers = 0
    unanswered_questions = 0
    
    correct_questions = []
    wrong_questions = []
    unanswered_questions_list = []
    
    # تحلیل سوالات و به‌روزرسانی سطح سختی
    for i, question in enumerate(quiz_data['questions']):
        question_id, question_image, correct_answer, explanation = question
        user_answer_data = user_answers_dict.get(question_id)
        
        if user_answer_data is None:
            unanswered_questions += 1
            unanswered_questions_list.append(i + 1)
        else:
            user_answer, time_spent = user_answer_data
            if user_answer == correct_answer:
                score += 1
                correct_answers += 1
                correct_questions.append(i + 1)
                # به‌روزرسانی سطح سختی برای سوالات بانک
                DifficultyAnalyzer.update_question_difficulty(question_id, True, time_spent)
            else:
                wrong_answers += 1
                wrong_questions.append(i + 1)
                DifficultyAnalyzer.update_question_difficulty(question_id, False, time_spent)
    
    # محاسبه نمره با نمره منفی
    raw_score = correct_answers
    penalty = wrong_answers / 3.0
    final_score = max(0, raw_score - penalty)
    final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0
    
    # ذخیره نتیجه با سیستم رتبه‌بندی
    result_id = ResultsManager.save_result(
        user_id, quiz_id, final_score, total_time, 
        correct_answers, wrong_answers, unanswered_questions
    )
    
    # دریافت اطلاعات کاربر و آزمون
    user_info = UserManager.get_user(user_id)
    quiz_info = QuizManager.get_quiz_info(quiz_id)
    
    user_data = user_info[0] if user_info else (user_id, "نامشخص", "نامشخص", "نامشخص")
    quiz_title = quiz_info[1] if quiz_info else "نامشخص"
    is_admin_quiz = quiz_info[5] if quiz_info else False
    
    # دریافت رتبه کاربر
    user_rank = ResultsManager.get_user_rank(user_id, quiz_id)
    
    # پیام به کاربر
    user_message = (
        f"✅ **آزمون شما با موفقیت ثبت شد!**\n\n"
        f"📊 **نتایج:**\n"
        f"✅ صحیح: {correct_answers} از {total_questions}\n"
        f"❌ غلط: {wrong_answers} از {total_questions}\n"
        f"⏸️ بی‌پاسخ: {unanswered_questions} از {total_questions}\n"
        f"📈 درصد نهایی: {final_percentage:.2f}%\n"
        f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n"
    )
    
    if is_admin_quiz and user_rank:
        user_message += f"🏆 **رتبه شما: {user_rank}**\n\n"
    else:
        user_message += "\n"
    
    # اضافه کردن شماره سوالات
    if correct_questions:
        user_message += f"🔢 **سوالات صحیح:** {', '.join(map(str, correct_questions))}\n"
    if wrong_questions:
        user_message += f"🔢 **سوالات غلط:** {', '.join(map(str, wrong_questions))}\n"
    if unanswered_questions_list:
        user_message += f"🔢 **سوالات بی‌پاسخ:** {', '.join(map(str, unanswered_questions_list))}\n"
    
    user_message += f"\n💡 **نکته:** هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد."
    
    keyboard = [
        [InlineKeyboardButton("📊 مشاهده جزییات", callback_data=f"quiz_details_{quiz_id}")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
    ]
    
    if is_admin_quiz:
        keyboard[0].append(InlineKeyboardButton("🏆 رتبه‌بندی", callback_data=f"quiz_ranking_{quiz_id}"))
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.callback_query.edit_message_text(
            user_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.callback_query.message.reply_text(
            user_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ارسال نتایج کامل به ادمین (برای آزمون‌های ادمین)
    if is_admin_quiz:
        admin_result_text = (
            "🎯 **نتایج آزمون جدید:**\n\n"
            f"👤 **کاربر:** {user_data[3]} (@{user_data[2] if user_data[2] else 'ندارد'})\n"
            f"📞 **شماره:** {user_data[1]}\n"
            f"🆔 **آیدی:** {user_id}\n\n"
            f"📚 **آزمون:** {quiz_title}\n"
            f"📝 **تعداد کل سوالات:** {total_questions}\n"
            f"✅ **پاسخ‌های صحیح:** {correct_answers}\n"
            f"❌ **پاسخ‌های غلط:** {wrong_answers}\n"
            f"⏸️ **بی‌پاسخ:** {unanswered_questions}\n"
            f"📈 **درصد نهایی:** {final_percentage:.2f}%\n"
            f"⏱ **زمان:** {total_time // 60}:{total_time % 60:02d}\n"
            f"🏆 **رتبه:** {user_rank}\n\n"
        )
        
        try:
            await context.bot.send_message(ADMIN_ID, admin_result_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error sending results to admin: {e}")
    
    # پاک کردن داده‌های موقت
    if 'current_quiz' in context.user_data:
        del context.user_data['current_quiz']
    if 'marked_questions' in context.user_data:
        del context.user_data['marked_questions']

# هندلرهای پیام‌های متنی برای ویژگی‌های جدید
async def handle_admin_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های متنی ادمین برای ویژگی‌های جدید"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    text = update.message.text
    
    if 'admin_action' not in context.user_data:
        return
    
    action = context.user_data['admin_action']
    
    if action == 'adding_topic':
        # پردازش افزودن مبحث جدید
        if 'topic_data' not in context.user_data:
            context.user_data['topic_data'] = {'name': text, 'step': 'description'}
            
            await update.message.reply_text(
                "✅ نام مبحث ذخیره شد.\n\n"
                "لطفاً توضیحات مبحث را ارسال کنید:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="admin_manage_topics")]])
            )
        else:
            topic_data = context.user_data['topic_data']
            if topic_data['step'] == 'description':
                topic_data['description'] = text
                
                # ذخیره مبحث در دیتابیس
                result = TopicManager.add_topic(topic_data['name'], text)
                
                if result:
                    await update.message.reply_text(
                        f"✅ مبحث '{topic_data['name']}' با موفقیت افزوده شد!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت مباحث", callback_data="admin_manage_topics")]])
                    )
                else:
                    await update.message.reply_text(
                        "❌ خطا در افزودن مبحث!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت مباحث", callback_data="admin_manage_topics")]])
                    )
                
                # پاک کردن داده‌های موقت
                del context.user_data['admin_action']
                del context.user_data['topic_data']

async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش جستجوی اینلاین"""
    query = update.inline_query.query
    
    if not query:
        return
    
    # جستجو در مباحث
    topics = DatabaseManager.execute_query(
        "SELECT id, name, description FROM topics WHERE name ILIKE %s AND is_active = TRUE LIMIT 10",
        (f"%{query}%",)
    )
    
    results = []
    
    for topic in topics:
        topic_id, name, description = topic
        question_count = QuestionBankManager.get_question_count_by_topic(topic_id)
        
        result = InlineQueryResultArticle(
            id=str(topic_id),
            title=f"📚 {name}",
            description=f"{description} ({question_count} سوال)",
            input_message_content=InputTextMessageContent(
                f"📚 مبحث: {name}\n\n{description}\n\n✅ {question_count} سوال موجود"
            )
        )
        results.append(result)
    
    await update.inline_query.answer(results, cache_time=1)

# تابع اصلی اجرای ربات
def main():
    """تابع اصلی اجرای ربات"""
    # راه‌اندازی دیتابیس
    DatabaseManager.init_database()
    
    # ساخت اپلیکیشن
    application = Application.builder().token(BOT_TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.PHOTO, handle_admin_photos))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(InlineQueryHandler(handle_inline_query))
    application.add_handler(ChosenInlineResultHandler(lambda update, context: None))
    
    # اجرای ربات
    print("🤖 ربات آزمون پیشرفته در حال اجرا است...")
    print("✅ سیستم بانک سوالات فعال")
    print("✅ سیستم رتبه‌بندی هوشمند فعال") 
    print("✅ ساخت آزمون سفارشی فعال")
    print("✅ تحلیل خودکار سطح سختی فعال")
    
    application.run_polling()

if __name__ == "__main__":
    main()
