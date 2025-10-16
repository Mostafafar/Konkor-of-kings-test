import os
import logging
import psycopg2
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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
ADMIN_ID = 6680287530  # آیدی عددی ادمین
PHOTOS_DIR = "photos"

# ایجاد دایرکتوری عکس‌ها
os.makedirs(PHOTOS_DIR, exist_ok=True)

# تنظیم لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.connection = None
        self.connect()
        self.init_database()
    
    def connect(self):
        """اتصال به دیتابیس PostgreSQL"""
        try:
            self.connection = psycopg2.connect(**DB_CONFIG)
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
    
    def init_database(self):
        """ایجاد جداول دیتابیس"""
        try:
            cursor = self.connection.cursor()
            
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
                    question_text TEXT,
                    question_image TEXT,
                    option1 TEXT,
                    option2 TEXT,
                    option3 TEXT,
                    option4 TEXT,
                    correct_answer INTEGER,
                    points INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            
            self.connection.commit()
            logger.info("Database tables created successfully")
            
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            self.connection.rollback()

    def execute_query(self, query: str, params: tuple = None, return_id: bool = False):
        """اجرای کوئری و بازگشت نتیجه"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params or ())
            
            if query.strip().upper().startswith('SELECT') or return_id:
                result = cursor.fetchall()
                self.connection.commit()
                return result
            else:
                self.connection.commit()
                return cursor.rowcount
                
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            self.connection.rollback()
            return None

    def get_user(self, user_id: int):
        """دریافت اطلاعات کاربر"""
        return self.execute_query(
            "SELECT * FROM users WHERE user_id = %s", 
            (user_id,)
        )

    def add_user(self, user_id: int, phone_number: str, username: str, full_name: str):
        """افزودن کاربر جدید"""
        return self.execute_query('''
            INSERT INTO users (user_id, phone_number, username, full_name) 
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET 
            phone_number = EXCLUDED.phone_number,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name
        ''', (user_id, phone_number, username, full_name))

    def get_active_quizzes(self):
        """دریافت آزمون‌های فعال"""
        return self.execute_query(
            "SELECT id, title, description, time_limit FROM quizzes WHERE is_active = TRUE ORDER BY id"
        )

    def get_quiz_questions(self, quiz_id: int):
        """دریافت سوالات یک آزمون"""
        return self.execute_query(
            "SELECT id, question_text, question_image, option1, option2, option3, option4, correct_answer FROM questions WHERE quiz_id = %s ORDER BY id",
            (quiz_id,)
        )

    def get_correct_answer(self, question_id: int):
        """دریافت پاسخ صحیح سوال"""
        result = self.execute_query(
            "SELECT correct_answer, points FROM questions WHERE id = %s",
            (question_id,)
        )
        return result[0] if result else None

    def save_result(self, user_id: int, quiz_id: int, score: int, total_time: int):
        """ذخیره نتیجه آزمون"""
        return self.execute_query('''
            INSERT INTO results (user_id, quiz_id, score, total_time) 
            VALUES (%s, %s, %s, %s)
        ''', (user_id, quiz_id, score, total_time))

    def get_leaderboard(self, limit: int = 10):
        """دریافت جدول رتبه‌بندی"""
        return self.execute_query('''
            SELECT u.full_name, r.score, r.total_time, q.title
            FROM results r
            JOIN users u ON r.user_id = u.user_id
            JOIN quizzes q ON r.quiz_id = q.id
            ORDER BY r.score DESC, r.total_time ASC
            LIMIT %s
        ''', (limit,))

    def create_quiz(self, title: str, description: str, time_limit: int):
        """ایجاد آزمون جدید"""
        result = self.execute_query('''
            INSERT INTO quizzes (title, description, time_limit, is_active) 
            VALUES (%s, %s, %s, TRUE) 
            RETURNING id
        ''', (title, description, time_limit), return_id=True)
        
        if result and len(result) > 0:
            return result[0][0]  # بازگشت اولین ستون از اولین ردیف
        return None

    def add_question(self, quiz_id: int, question_text: str, question_image: str, 
                    option1: str, option2: str, option3: str, option4: str, correct_answer: int):
        """افزودن سوال به آزمون"""
        return self.execute_query('''
            INSERT INTO questions 
            (quiz_id, question_text, question_image, option1, option2, option3, option4, correct_answer)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (quiz_id, question_text, question_image, option1, option2, option3, option4, correct_answer))


class QuizBot:
    def __init__(self):
        self.db = Database()
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شروع ربات و دریافت شماره تلفن"""
        user = update.effective_user
        user_id = user.id
        
        # بررسی ثبت نام کاربر
        user_data = self.db.get_user(user_id)
        
        if user_data:
            await self.show_main_menu(update, context)
        else:
            # استفاده از KeyboardButton برای دکمه ارسال شماره
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
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش شماره تلفن دریافتی"""
        contact = update.message.contact
        user = update.effective_user
        
        if contact.user_id != user.id:
            await update.message.reply_text("لطفاً شماره تلفن خودتان را ارسال کنید.")
            return
        
        # ذخیره اطلاعات کاربر
        self.db.add_user(
            user.id, 
            contact.phone_number, 
            user.username, 
            user.full_name
        )
        
        # اطلاع به ادمین
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
        
        await self.show_main_menu(update, context)
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌ها"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "take_quiz":
            await self.show_quiz_list(update, context)
        elif data == "help":
            await self.show_help(update, context)
        elif data == "admin_panel":
            await self.show_admin_panel(update, context)
        elif data.startswith("quiz_"):
            quiz_id = int(data.split("_")[1])
            await self.start_quiz(update, context, quiz_id)
        elif data.startswith("answer_"):
            parts = data.split("_")
            quiz_id = int(parts[1])
            question_index = int(parts[2])
            answer = int(parts[3])
            await self.handle_answer(update, context, quiz_id, question_index, answer)
        elif data.startswith("mark_"):
            parts = data.split("_")
            quiz_id = int(parts[1])
            question_index = int(parts[2])
            await self.toggle_mark_question(update, context, quiz_id, question_index)
        elif data.startswith("submit_marked_"):
            quiz_id = int(data.split("_")[2])
            await self.submit_marked_questions(update, context, quiz_id)
        elif data == "main_menu":
            await self.show_main_menu(update, context)
        elif data == "admin_create_quiz":
            await self.admin_create_quiz(update, context)
        elif data == "admin_manage_quizzes":
            await self.admin_manage_quizzes(update, context)
        elif data == "admin_view_users":
            await self.admin_view_users(update, context)
        elif data == "admin_view_results":
            await self.admin_view_results(update, context)
        elif data == "confirm_add_questions":
            await self.start_adding_questions(update, context)
        elif data == "add_another_question":
            await self.start_adding_questions(update, context)
        elif data == "finish_adding_questions":
            await self.finish_adding_questions(update, context)
        elif data.startswith("toggle_quiz_"):
            quiz_id = int(data.split("_")[2])
            await self.toggle_quiz_status(update, context, quiz_id)
    
    async def show_quiz_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش لیست آزمون‌های فعال"""
        # فقط آزمون‌های فعال را دریافت کن
        quizzes = self.db.execute_query(
            "SELECT id, title, description, time_limit FROM quizzes WHERE is_active = TRUE ORDER BY id"
        )
        
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
    
    async def start_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
        """شروع آزمون"""
        user_id = update.effective_user.id
        
        # دریافت اطلاعات آزمون با بررسی وضعیت فعال بودن
        quizzes = self.db.execute_query(
            "SELECT title, time_limit, is_active FROM quizzes WHERE id = %s", 
            (quiz_id,)
        )
        
        if not quizzes:
            await update.callback_query.edit_message_text("آزمون یافت نشد!")
            return
        
        title, time_limit, is_active = quizzes[0]
        
        # بررسی اینکه آزمون فعال است یا نه
        if not is_active:
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به لیست آزمون‌ها", callback_data="take_quiz")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.edit_message_text(
                "❌ این آزمون در حال حاضر غیرفعال است و نمی‌توانید در آن شرکت کنید.",
                reply_markup=reply_markup
            )
            return
        
        # دریافت سوالات
        questions = self.db.get_quiz_questions(quiz_id)
        
        if not questions:
            await update.callback_query.edit_message_text("هیچ سوالی برای این آزمون تعریف نشده!")
            return
        
        # ذخیره اطلاعات آزمون در context
        context.user_data['current_quiz'] = {
            'quiz_id': quiz_id,
            'questions': questions,
            'current_question': 0,
            'answers': [],
            'marked_questions': set(),  # سوالات علامت‌گذاری شده
            'start_time': datetime.now(),
            'time_limit': time_limit
        }
        
        # شروع تایمر
        context.job_queue.run_once(
            self.quiz_timeout, 
            time_limit * 60, 
            user_id=user_id, 
            data=quiz_id
        )
        
        await self.show_question(update, context, 0)
    
    async def show_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, question_index: int):
        """نمایش سوال جاری با ۵ دکمه (۴ گزینه + علامت‌گذاری)"""
        quiz_data = context.user_data['current_quiz']
        question = quiz_data['questions'][question_index]
        
        question_id, question_text, question_image, opt1, opt2, opt3, opt4, correct_answer = question
        
        # بررسی آیا سوال علامت‌گذاری شده است
        is_marked = question_index in quiz_data['marked_questions']
        mark_text = "❌ برداشتن علامت" if is_marked else "✅ علامت گذاری"
        
        keyboard = [
            [InlineKeyboardButton(f"1️⃣ {opt1}", callback_data=f"answer_{quiz_data['quiz_id']}_{question_index}_1")],
            [InlineKeyboardButton(f"2️⃣ {opt2}", callback_data=f"answer_{quiz_data['quiz_id']}_{question_index}_2")],
            [InlineKeyboardButton(f"3️⃣ {opt3}", callback_data=f"answer_{quiz_data['quiz_id']}_{question_index}_3")],
            [InlineKeyboardButton(f"4️⃣ {opt4}", callback_data=f"answer_{quiz_data['quiz_id']}_{question_index}_4")],
            [InlineKeyboardButton(mark_text, callback_data=f"mark_{quiz_data['quiz_id']}_{question_index}")]
        ]
        
        # اگر آخرین سوال است، دکمه ارسال سوالات علامت‌گذاری شده اضافه شود
        if question_index == len(quiz_data['questions']) - 1 and quiz_data['marked_questions']:
            keyboard.append([InlineKeyboardButton(
                "📤 ارسال سوالات علامت‌گذاری شده", 
                callback_data=f"submit_marked_{quiz_data['quiz_id']}"
            )])
        
        # دکمه‌های ناوبری
        nav_buttons = []
        if question_index > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"nav_{quiz_data['quiz_id']}_{question_index-1}"))
        if question_index < len(quiz_data['questions']) - 1:
            nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"nav_{quiz_data['quiz_id']}_{question_index+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = f"📝 سوال {question_index + 1} از {len(quiz_data['questions'])}:\n\n{question_text}"
        
        # نمایش وضعیت علامت‌گذاری
        if quiz_data['marked_questions']:
            message_text += f"\n\n📌 سوالات علامت‌گذاری شده: {len(quiz_data['marked_questions'])}"
        
        try:
            if question_image and os.path.exists(question_image):
                with open(question_image, 'rb') as photo:
                    if hasattr(update.callback_query, 'edit_message_media'):
                        await update.callback_query.edit_message_media(
                            media=InputMediaPhoto(photo, caption=message_text),
                            reply_markup=reply_markup
                        )
                    else:
                        await update.callback_query.message.reply_photo(
                            photo=photo,
                            caption=message_text,
                            reply_markup=reply_markup
                        )
            else:
                await update.callback_query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Error showing question: {e}")
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=reply_markup
            )
    
    async def toggle_mark_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int, question_index: int):
        """علامت‌گذاری یا برداشتن علامت سوال"""
        quiz_data = context.user_data['current_quiz']
        
        if question_index in quiz_data['marked_questions']:
            quiz_data['marked_questions'].remove(question_index)
        else:
            quiz_data['marked_questions'].add(question_index)
        
        # نمایش مجدد سوال با وضعیت به‌روز شده
        await self.show_question(update, context, question_index)
    
    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                          quiz_id: int, question_index: int, answer: int):
        """پردازش پاسخ کاربر"""
        quiz_data = context.user_data['current_quiz']
        
        # ذخیره پاسخ
        existing_answer_index = None
        for i, ans in enumerate(quiz_data['answers']):
            if ans['question_index'] == question_index:
                existing_answer_index = i
                break
        
        if existing_answer_index is not None:
            quiz_data['answers'][existing_answer_index]['answer'] = answer
            quiz_data['answers'][existing_answer_index]['time'] = datetime.now()
        else:
            quiz_data['answers'].append({
                'question_index': question_index,
                'answer': answer,
                'time': datetime.now()
            })
        
        # نمایش سوال بعدی اگر آخرین سوال نباشد
        if question_index < len(quiz_data['questions']) - 1:
            await self.show_question(update, context, question_index + 1)
        else:
            # اگر آخرین سوال است، کاربر را در همان سوال نگه دار
            await self.show_question(update, context, question_index)
    
    async def submit_marked_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
        """ارسال سوالات علامت‌گذاری شده"""
        quiz_data = context.user_data['current_quiz']
        
        if not quiz_data['marked_questions']:
            await update.callback_query.answer("هیچ سوالی علامت‌گذاری نشده است!", show_alert=True)
            return
        
        await self.finish_quiz(update, context)
    
    async def quiz_timeout(self, context: ContextTypes.DEFAULT_TYPE):
        """اتمام زمان آزمون"""
        job = context.job
        user_id = job.user_id
        
        try:
            if 'current_quiz' in context.user_data:
                await context.bot.send_message(
                    user_id,
                    "⏰ زمان آزمون به پایان رسید! نتایج برای ادمین ارسال شد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                    ])
                )
                
                await self.calculate_results(context, user_id, True)
        except Exception as e:
            logger.error(f"Error in quiz timeout: {e}")
    
    async def finish_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پایان آزمون و محاسبه نتایج"""
        user_id = update.effective_user.id
        await self.calculate_results(context, user_id)
        
        # حذف job تایمر
        current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
        for job in current_jobs:
            job.schedule_removal()
    
    async def calculate_results(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, timeout=False):
        """محاسبه نتایج آزمون و ارسال به ادمین"""
        if 'current_quiz' not in context.user_data:
            return
        
        quiz_data = context.user_data['current_quiz']
        quiz_id = quiz_data['quiz_id']
        
        # محاسبه امتیاز
        score = 0
        correct_answers = 0
        total_questions = len(quiz_data['questions'])
        
        result_details = "📊 جزئیات پاسخ‌ها:\n\n"
        
        for i, answer_data in enumerate(quiz_data['answers']):
            question_index = answer_data['question_index']
            user_answer = answer_data['answer']
            
            question_id = quiz_data['questions'][question_index][0]
            correct_data = self.db.get_correct_answer(question_id)
            
            question_text = quiz_data['questions'][question_index][1]
            is_correct = correct_data and correct_data[0] == user_answer
            
            if is_correct:
                score += correct_data[1]
                correct_answers += 1
                result_details += f"✅ سوال {question_index+1}: صحیح\n"
            else:
                result_details += f"❌ سوال {question_index+1}: غلط (پاسخ شما: {user_answer}, پاسخ صحیح: {correct_data[0] if correct_data else '?'})\n"
        
        # محاسبه زمان
        total_time = (datetime.now() - quiz_data['start_time']).seconds
        
        # ذخیره نتیجه
        self.db.save_result(user_id, quiz_id, score, total_time)
        
        # دریافت اطلاعات کاربر و آزمون
        user_info = self.db.get_user(user_id)
        quiz_info = self.db.execute_query(
            "SELECT title FROM quizzes WHERE id = %s", 
            (quiz_id,)
        )
        
        user_data = user_info[0] if user_info else (user_id, "نامشخص", "نامشخص", "نامشخص")
        quiz_title = quiz_info[0][0] if quiz_info else "نامشخص"
        
        # ارسال نتایج کامل به ادمین
        admin_result_text = (
            "🎯 نتایج آزمون جدید:\n\n"
            f"👤 کاربر: {user_data[3]} (@{user_data[2] if user_data[2] else 'ندارد'})\n"
            f"📞 شماره: {user_data[1]}\n"
            f"🆔 آیدی: {user_id}\n\n"
            f"📚 آزمون: {quiz_title}\n"
            f"✅ امتیاز: {score} از {total_questions}\n"
            f"📈 صحیح: {correct_answers} از {total_questions}\n"
            f"⏱ زمان: {total_time // 60}:{total_time % 60:02d}\n"
            f"🕒 وضعیت: {'⏰ timeout' if timeout else '✅正常'}\n\n"
            f"{result_details}"
        )
        
        try:
            await context.bot.send_message(ADMIN_ID, admin_result_text)
        except Exception as e:
            logger.error(f"Error sending results to admin: {e}")
        
        # پیام ساده به کاربر
        user_message = "✅ آزمون شما با موفقیت ثبت شد. نتایج برای مدیران ارسال گردید."
        
        try:
            await context.bot.send_message(
                user_id,
                user_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"Error sending message to user: {e}")
        
        # پاک کردن داده‌های موقت
        if 'current_quiz' in context.user_data:
            del context.user_data['current_quiz']
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش راهنما"""
        help_text = (
            "📖 راهنمای ربات آزمون:\n\n"
            "1. 📝 شرکت در آزمون: از بین آزمون‌های فعال یکی را انتخاب کنید\n"
            "2. ⏱ زمان‌بندی: هر آزمون زمان محدودی دارد\n"
            "3. ✅ علامت‌گذاری: می‌توانید سوالات را علامت‌گذاری کنید\n"
            "4. 📤 ارسال: در آخرین سوال می‌توانید فقط سوالات علامت‌گذاری شده را ارسال کنید\n"
            "5. 📊 نتایج: نتایج برای مدیران ارسال می‌شود\n\n"
            "موفق باشید! 🎯"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            help_text,
            reply_markup=reply_markup
        )
    
    # بخش مدیریت ادمین
    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    async def admin_create_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    async def admin_manage_quizzes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت آزمون‌ها"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        quizzes = self.db.execute_query("SELECT id, title, is_active FROM quizzes ORDER BY created_at DESC")
        
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
    
    async def toggle_quiz_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_id: int):
        """تغییر وضعیت فعال/غیرفعال آزمون"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        # دریافت وضعیت فعلی آزمون
        quiz_info = self.db.execute_query(
            "SELECT title, is_active FROM quizzes WHERE id = %s", 
            (quiz_id,)
        )
        
        if not quiz_info:
            await update.callback_query.edit_message_text("آزمون یافت نشد!")
            return
        
        title, current_status = quiz_info[0]
        new_status = not current_status
        
        # به روزرسانی وضعیت آزمون
        result = self.db.execute_query(
            "UPDATE quizzes SET is_active = %s WHERE id = %s",
            (new_status, quiz_id)
        )
        
        if result is not None:
            status_text = "فعال" if new_status else "غیرفعال"
            await update.callback_query.edit_message_text(
                f"✅ وضعیت آزمون '{title}' به {status_text} تغییر یافت."
            )
            
            # بازگشت به لیست آزمون‌ها
            await asyncio.sleep(2)
            await self.admin_manage_quizzes(update, context)
        else:
            await update.callback_query.edit_message_text(
                "❌ خطا در تغییر وضعیت آزمون! لطفاً دوباره تلاش کنید."
            )
    
    async def admin_view_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مشاهده کاربران"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        users = self.db.execute_query(
            "SELECT user_id, full_name, username, phone_number, registered_at FROM users ORDER BY registered_at DESC LIMIT 50"
        )
        
        text = "👥 کاربران ثبت‌نام شده:\n\n"
        
        for user_id, full_name, username, phone_number, registered_at in users:
            text += f"👤 {full_name}\n"
            text += f"📞 {phone_number}\n"
            text += f"🔗 @{username if username else 'ندارد'}\n"
            text += f"🆔 {user_id}\n"
            text += f"📅 {registered_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    
    async def admin_view_results(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مشاهده نتایج"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        results = self.db.execute_query('''
            SELECT u.full_name, q.title, r.score, r.total_time, r.completed_at 
            FROM results r
            JOIN users u ON r.user_id = u.user_id
            JOIN quizzes q ON r.quiz_id = q.id
            ORDER BY r.completed_at DESC LIMIT 20
        ''')
        
        text = "📊 آخرین نتایج:\n\n"
        
        for full_name, quiz_title, score, total_time, completed_at in results:
            time_str = f"{total_time // 60}:{total_time % 60:02d}"
            text += f"👤 {full_name}\n"
            text += f"📚 {quiz_title}\n"
            text += f"✅ امتیاز: {score}\n"
            text += f"⏱ زمان: {time_str}\n"
            text += f"📅 {completed_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    
    async def handle_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش پیام‌های ادمین برای ایجاد آزمون"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        if 'admin_action' not in context.user_data:
            return
        
        action = context.user_data['admin_action']
        message_text = update.message.text
        
        if action == 'creating_quiz':
            await self.process_quiz_creation(update, context, message_text)
        elif action == 'adding_questions':
            await self.process_question_addition(update, context, message_text)
    
    async def process_quiz_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """پردازش مراحل ایجاد آزمون"""
        quiz_data = context.user_data['quiz_data']
        current_step = quiz_data['current_step']
        
        if current_step == 'title':
            quiz_data['title'] = message_text
            quiz_data['current_step'] = 'description'
            
            await update.message.reply_text(
                "📝 توضیحات آزمون را ارسال کنید:"
            )
        
        elif current_step == 'description':
            quiz_data['description'] = message_text
            quiz_data['current_step'] = 'time_limit'
            
            await update.message.reply_text(
                "⏱ زمان آزمون را به دقیقه ارسال کنید (مثلاً 60):"
            )
        
        elif current_step == 'time_limit':
            try:
                time_limit = int(message_text)
                quiz_data['time_limit'] = time_limit
                
                # ایجاد آزمون در دیتابیس
                quiz_id = self.db.create_quiz(
                    quiz_data['title'],
                    quiz_data['description'],
                    quiz_data['time_limit']
                )
                
                if quiz_id:
                    quiz_data['quiz_id'] = quiz_id
                    context.user_data['admin_action'] = 'adding_questions'
                    quiz_data['current_step'] = 'waiting_for_photo'
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ بله، افزودن سوال", callback_data="confirm_add_questions")],
                        [InlineKeyboardButton("❌ خیر، بعداً", callback_data="admin_panel")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        f"✅ آزمون '{quiz_data['title']}' با موفقیت ایجاد شد!\n\n"
                        f"آیا می‌خواهید اکنون سوالات را اضافه کنید؟",
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_text(
                        "❌ خطا در ایجاد آزمون! لطفاً دوباره تلاش کنید."
                    )
                    context.user_data.clear()
            
            except ValueError:
                await update.message.reply_text(
                    "❌ لطفاً یک عدد صحیح برای زمان آزمون ارسال کنید:"
                )
    
    async def start_adding_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شروع فرآیند افزودن سوالات"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        context.user_data['admin_action'] = 'adding_questions'
        context.user_data['quiz_data']['current_step'] = 'waiting_for_photo'
        
        await update.callback_query.edit_message_text(
            "📸 لطفاً عکس سوال را ارسال کنید (یا برای ادامه بدون عکس /skip ارسال کنید):"
        )
    
    async def handle_admin_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش عکس ارسالی ادمین برای سوال"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        if ('admin_action' not in context.user_data or 
            context.user_data['admin_action'] != 'adding_questions'):
            return
        
        quiz_data = context.user_data['quiz_data']
        
        if quiz_data['current_step'] == 'waiting_for_photo':
            # ذخیره عکس
            photo_file = await update.message.photo[-1].get_file()
            photo_path = os.path.join(PHOTOS_DIR, f"question_{quiz_data['quiz_id']}_{len(quiz_data['questions']) + 1}.jpg")
            await photo_file.download_to_drive(photo_path)
            
            quiz_data['current_question_image'] = photo_path
            quiz_data['current_step'] = 'question_text'
            
            await update.message.reply_text(
                "📝 متن سوال را ارسال کنید:"
            )
    
    async def process_question_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """پردازش افزودن سوال"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        quiz_data = context.user_data['quiz_data']
        current_step = quiz_data['current_step']
        
        if message_text == '/skip' and current_step == 'waiting_for_photo':
            quiz_data['current_question_image'] = None
            quiz_data['current_step'] = 'question_text'
            await update.message.reply_text("📝 متن سوال را ارسال کنید:")
            return
        
        if current_step == 'question_text':
            quiz_data['current_question_text'] = message_text
            quiz_data['current_step'] = 'option1'
            
            await update.message.reply_text("1️⃣ گزینه اول را ارسال کنید:")
        
        elif current_step == 'option1':
            quiz_data['current_option1'] = message_text
            quiz_data['current_step'] = 'option2'
            
            await update.message.reply_text("2️⃣ گزینه دوم را ارسال کنید:")
        
        elif current_step == 'option2':
            quiz_data['current_option2'] = message_text
            quiz_data['current_step'] = 'option3'
            
            await update.message.reply_text("3️⃣ گزینه سوم را ارسال کنید:")
        
        elif current_step == 'option3':
            quiz_data['current_option3'] = message_text
            quiz_data['current_step'] = 'option4'
            
            await update.message.reply_text("4️⃣ گزینه چهارم را ارسال کنید:")
        
        elif current_step == 'option4':
            quiz_data['current_option4'] = message_text
            quiz_data['current_step'] = 'correct_answer'
            
            keyboard = [
                [InlineKeyboardButton("1️⃣ گزینه 1", callback_data="correct_1")],
                [InlineKeyboardButton("2️⃣ گزینه 2", callback_data="correct_2")],
                [InlineKeyboardButton("3️⃣ گزینه 3", callback_data="correct_3")],
                [InlineKeyboardButton("4️⃣ گزینه 4", callback_data="correct_4")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ گزینه صحیح را انتخاب کنید:",
                reply_markup=reply_markup
            )
    
    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش انتخاب گزینه صحیح"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        query = update.callback_query
        await query.answer()
        
        correct_answer = int(query.data.split("_")[1])
        quiz_data = context.user_data['quiz_data']
        
        # ذخیره سوال در دیتابیس
        question_id = self.db.add_question(
            quiz_data['quiz_id'],
            quiz_data['current_question_text'],
            quiz_data['current_question_image'],
            quiz_data['current_option1'],
            quiz_data['current_option2'],
            quiz_data['current_option3'],
            quiz_data['current_option4'],
            correct_answer
        )
        
        if question_id:
            # ذخیره سوال در لیست موقت
            quiz_data['questions'].append({
                'text': quiz_data['current_question_text'],
                'image': quiz_data['current_question_image']
            })
            
            keyboard = [
                [InlineKeyboardButton("➕ افزودن سوال دیگر", callback_data="add_another_question")],
                [InlineKeyboardButton("✅ اتمام افزودن سوالات", callback_data="finish_adding_questions")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ سوال با موفقیت اضافه شد!\n\n"
                f"تعداد سوالات اضافه شده: {len(quiz_data['questions'])}\n\n"
                f"چه کاری می‌خواهید انجام دهید؟",
                reply_markup=reply_markup
            )
            
            # بازنشانی برای سوال بعدی
            quiz_data['current_step'] = 'waiting_for_photo'
            quiz_data['current_question_image'] = None
            quiz_data['current_question_text'] = None
            quiz_data['current_option1'] = None
            quiz_data['current_option2'] = None
            quiz_data['current_option3'] = None
            quiz_data['current_option4'] = None
    
    async def finish_adding_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پایان افزودن سوالات"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        quiz_data = context.user_data['quiz_data']
        
        await update.callback_query.edit_message_text(
            f"✅ فرآیند ایجاد آزمون کامل شد!\n\n"
            f"📚 آزمون: {quiz_data['title']}\n"
            f"📝 تعداد سوالات: {len(quiz_data['questions'])}\n"
            f"⏱ زمان: {quiz_data['time_limit']} دقیقه\n\n"
            f"آزمون اکنون آماده استفاده است."
        )
        
        # پاک کردن داده‌های موقت
        context.user_data.clear()
        
        await asyncio.sleep(3)
        await self.show_admin_panel(update, context)
    
    async def handle_skip_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پردازش دستور /skip برای رد شدن از ارسال عکس"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        if ('admin_action' in context.user_data and 
            context.user_data['admin_action'] == 'adding_questions'):
            
            quiz_data = context.user_data['quiz_data']
            if quiz_data['current_step'] == 'waiting_for_photo':
                quiz_data['current_question_image'] = None
                quiz_data['current_step'] = 'question_text'
                
                await update.message.reply_text("📝 متن سوال را ارسال کنید:")

    def run(self):
        """اجرای ربات"""
        application = Application.builder().token(BOT_TOKEN).build()
        
        # handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("skip", self.handle_skip_photo))
        application.add_handler(MessageHandler(filters.CONTACT, self.handle_contact))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_message))
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_admin_photo))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # اجرای ربات
        logger.info("Bot is running...")
        application.run_polling()

if __name__ == "__main__":
    bot = QuizBot()
    bot.run()
