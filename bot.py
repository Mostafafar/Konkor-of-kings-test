import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta, time
import jdatetime
import pytz

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توکن ربات
TOKEN = "7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ"

# آیدی ادمین (را با آیدی تلگرام خود جایگزین کنید)
ADMIN_ID = 6680287530  # 👈 آیدی عددی تلگرام خود را اینجا قرار دهید

# تنظیمات دیتابیس
DB_CONFIG = {
    'dbname': 'exam_bot',
    'user': 'bot_user',
    'password': 'bot_password',
    'host': 'localhost',
    'port': '5432'
}

# منطقه زمانی تهران
TEHRAN_TZ = pytz.timezone('Asia/Tehran')

# تنظیمات پیجینیشن
QUESTIONS_PER_PAGE = 10

def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

# ایجاد جدول در دیتابیس
def init_db():
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("Failed to connect to database for initialization")
            return False
            
        cur = conn.cursor()
        
        # ایجاد جدول آزمون‌ها
        cur.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                course_name TEXT,
                topic_name TEXT,
                start_question INTEGER,
                end_question INTEGER,
                total_questions INTEGER,
                exam_duration INTEGER DEFAULT 0,
                elapsed_time REAL DEFAULT 0,
                answers TEXT,
                correct_answers TEXT,
                score REAL DEFAULT 0,
                wrong_questions TEXT,
                unanswered_questions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                jalali_date TEXT,
                tehran_time TEXT,
                question_pattern TEXT DEFAULT 'all'
            )
        ''')
        
        # ایجاد جدول کاربران
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                jalali_date TEXT,
                tehran_time TEXT
            )
        ''')
        
        # بررسی و اضافه کردن ستون‌های جدید اگر وجود ندارند
        columns_to_add = [
            ('course_name', 'TEXT'),
            ('topic_name', 'TEXT'),
            ('jalali_date', 'TEXT'),
            ('tehran_time', 'TEXT'),
            ('exam_duration', 'INTEGER DEFAULT 0'),
            ('elapsed_time', 'REAL DEFAULT 0'),
            ('question_pattern', 'TEXT DEFAULT \'all\'')
        ]
        
        for column_name, column_type in columns_to_add:
            try:
                cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='exams' AND column_name='{column_name}'
                """)
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE exams ADD COLUMN {column_name} {column_type}")
                    logger.info(f"Added missing column: {column_name}")
            except Exception as e:
                logger.error(f"Error checking/adding column {column_name}: {e}")
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False

# دریافت تاریخ و زمان تهران
def get_tehran_datetime():
    """دریافت تاریخ و زمان فعلی تهران"""
    tehran_now = datetime.now(TEHRAN_TZ)
    return tehran_now

def get_jalali_date():
    """دریافت تاریخ شمسی"""
    tehran_now = get_tehran_datetime()
    jalali_date = jdatetime.datetime.fromgregorian(datetime=tehran_now)
    return jalali_date.strftime('%Y/%m/%d')

def get_tehran_time():
    """دریافت زمان تهران"""
    tehran_now = get_tehran_datetime()
    return tehran_now.strftime('%H:%M:%S')

# محاسبه سوالات بر اساس الگوی انتخاب شده
def calculate_questions_by_pattern(start_question, end_question, pattern):
    """محاسبه سوالات بر اساس الگوی انتخاب شده"""
    all_questions = list(range(start_question, end_question + 1))
    
    if pattern == 'all':
        return all_questions
    elif pattern == 'alternate':
        # یکی در میان - بر اساس زوج/فرد بودن اولین سوال
        if start_question % 2 == 0:  # اگر اولین سوال زوج باشد
            return [q for q in all_questions if q % 2 == 0]  # سوالات زوج
        else:  # اگر اولین سوال فرد باشد
            return [q for q in all_questions if q % 2 == 1]  # سوالات فرد
    elif pattern == 'every_two':
        # دو تا در میان (هر سومین سوال)
        return [q for i, q in enumerate(all_questions, 1) if i % 3 == 1]
    elif pattern == 'every_three':
        # سه تا در میان (هر چهارمین سوال)
        return [q for i, q in enumerate(all_questions, 1) if i % 4 == 1]
    else:
        return all_questions

# دریافت نام الگو
def get_pattern_name(pattern):
    pattern_names = {
        'all': 'همه سوالات (پشت سر هم)',
        'alternate': 'یکی در میان (زوج/فرد)',
        'every_two': 'دو تا در میان',
        'every_three': 'سه تا در میان'
    }
    return pattern_names.get(pattern, 'نامعلوم')

# ذخیره اطلاعات کاربر در دیتابیس
async def save_user_info(user):
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            
            jalali_date = get_jalali_date()
            tehran_time = get_tehran_time()
            
            cur.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, jalali_date, tehran_time)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (
                user.id,
                user.username or '',
                user.first_name or '',
                user.last_name or '',
                jalali_date,
                tehran_time
            ))
            
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        logger.error(f"Error saving user info: {e}")
    return False

# ارسال اطلاعات کاربر جدید به ادمین
async def notify_admin_new_user(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        jalali_date = get_jalali_date()
        tehran_time = get_tehran_time()
        
        user_info = f"""
🆕 کاربر جدید وارد ربات شد!

👤 نام: {user.first_name or ''} {user.last_name or ''}
🆔 یوزرنیم: @{user.username if user.username else 'ندارد'}
🔢 آیدی: {user.id}
📅 تاریخ: {jalali_date}
⏰ ساعت: {tehran_time}
"""
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=user_info
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")

# ایجاد کیبورد اصلی
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📝 ساخت آزمون جدید"), KeyboardButton("📊 مشاهده نتایج")],
        [KeyboardButton("📚 راهنما"), KeyboardButton("ℹ️ درباره ربات")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# مدیریت دستور start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # ذخیره اطلاعات کاربر
    is_new_user = await save_user_info(user)
    
    # اگر کاربر جدید است، به ادمین اطلاع بده
    if is_new_user:
        await notify_admin_new_user(context, user)
    
    welcome_text = f"""
🎓 سلام {user.first_name} عزیز!

به ربات آزمون‌ساز هوشمند خوش آمدید! 🤖

✨ با این ربات می‌توانید:

📝 آزمون‌های تستی ایجاد کنید
⏱️ زمان‌بندی دقیق داشته باشید
📊 نتایج دقیق و تحلیلی دریافت کنید
📈 پیشرفت خود را پیگیری کنید

💡 برای شروع، از دکمه‌های زیر استفاده کنید:
"""
    
    # ایجاد کیبورد اینلاین برای شروع
    keyboard = [
        [InlineKeyboardButton("🚀 شروع آزمون", callback_data="new_exam")],
        [InlineKeyboardButton("📊 نتایج من", callback_data="results")],
        [InlineKeyboardButton("📚 راهنمای استفاده", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )
    
    # نمایش کیبورد اصلی
    await update.message.reply_text(
        "از منوی زیر هم می‌توانید استفاده کنید:",
        reply_markup=get_main_keyboard()
    )

# نمایش راهنما
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 راهنمای استفاده از ربات

🔹 ساخت آزمون:
1️⃣ نام درس را وارد کنید
2️⃣ نام مبحث را مشخص کنید
3️⃣ شماره اولین و آخرین سوال را بنویسید
4️⃣ الگوی سوالات را انتخاب کنید
5️⃣ مدت زمان آزمون را تعیین کنید (0 برای نامحدود)
6️⃣ به سوالات پاسخ دهید
7️⃣ پاسخ‌های صحیح را وارد کنید
8️⃣ نتیجه خود را مشاهده کنید

🔹 الگوهای سوالات:
• همه سوالات (پشت سر هم)
• یکی در میان (زوج/فرد)
• دو تا در میان
• سه تا در میان

🔹 ویژگی‌ها:
⏱️ تایمر زنده با نوار پیشرفت
📄 صفحه‌بندی سوالات (10 سوال در هر صفحه)
✅ امکان تغییر پاسخ‌ها
📊 محاسبه نمره با و بدون منفی
📈 ذخیره تاریخچه آزمون‌ها

💡 نکته مهم: هر 3 پاسخ اشتباه، معادل 1 پاسخ صحیح نمره منفی دارد.
"""
    
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text)
    else:
        await update.message.reply_text(help_text)

# درباره ربات
async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = """
ℹ️ درباره ربات آزمون‌ساز

🤖 نسخه: 2.1
👨‍💻 توسعه‌دهنده: تیم توسعه
📅 آخرین بروزرسانی: 1404

🌟 ویژگی‌های نسخه جدید:
• رابط کاربری زیبا و حرفه‌ای
• کیبورد فارسی
• اعلان‌های ادمین
• گزارش‌گیری روزانه
• تایمر پیشرفته
• صفحه‌بندی هوشمند
• الگوهای متنوع سوالات

📧 برای پشتیبانی با ادمین در ارتباط باشید.
"""
    
    await update.message.reply_text(about_text)

# مدیریت callback query برای دکمه‌ها
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "new_exam":
        await new_exam(update, context)
    elif query.data == "results":
        await show_results(update, context)
    elif query.data == "help":
        await show_help(update, context)

# مدیریت پیام‌های متنی از کیبورد
async def handle_keyboard_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "📝 ساخت آزمون جدید":
        await new_exam_from_message(update, context)
    elif text == "📊 مشاهده نتایج":
        await show_results(update, context)
    elif text == "📚 راهنما":
        await show_help(update, context)
    elif text == "ℹ️ درباره ربات":
        await show_about(update, context)
    else:
        # مدیریت مراحل ایجاد آزمون
        await handle_message(update, context)

# ایجاد آزمون جدید از طریق کیبورد
async def new_exam_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.pop('exam_setup', None)
    context.user_data['exam_setup'] = {'step': 'course_name'}
    
    await update.message.reply_text(
        "📚 لطفاً نام درس را وارد کنید:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ لغو")]], resize_keyboard=True)
    )

# ایجاد آزمون جدید
async def new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.pop('exam_setup', None)
    context.user_data['exam_setup'] = {'step': 'course_name'}
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "📚 لطفاً نام درس را وارد کنید:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ لغو")]], resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            "📚 لطفاً نام درس را وارد کنید:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ لغو")]], resize_keyboard=True)
        )

# محاسبه تعداد صفحات
def calculate_total_pages(total_questions):
    return (total_questions + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE

# نمایش سوالات به صورت صفحه‌بندی شده
async def show_questions_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    exam_setup = context.user_data['exam_setup']
    user_answers = exam_setup.get('answers', {})
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    total_questions = exam_setup.get('total_questions')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    # دریافت لیست سوالات بر اساس الگو
    question_list = exam_setup.get('question_list', [])
    
    total_pages = calculate_total_pages(total_questions)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * QUESTIONS_PER_PAGE
    end_idx = min(start_idx + QUESTIONS_PER_PAGE, total_questions)
    
    message_text = f"📚 درس: {course_name}\n"
    message_text += f"📖 مبحث: {topic_name}\n"
    message_text += f"📄 صفحه {page} از {total_pages}\n"
    message_text += f"🔢 الگو: {get_pattern_name(question_pattern)}\n\n"
    message_text += "📝 لطفاً به سوالات پاسخ دهید:\n\n"
    
    keyboard = []
    
    for i in range(start_idx, end_idx):
        question_num = question_list[i]
        current_answer = user_answers.get(str(question_num))
        question_buttons = []
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
            if current_answer == option:
                button_text = f"{option} ✅"
            else:
                button_text = str(option)
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    navigation_buttons = []
    if total_pages > 1:
        if page > 1:
            navigation_buttons.append(InlineKeyboardButton("◀️ صفحه قبلی", callback_data=f"page_{page-1}"))
        if page < total_pages:
            navigation_buttons.append(InlineKeyboardButton("صفحه بعدی ▶️", callback_data=f"page_{page+1}"))
        
        if navigation_buttons:
            keyboard.append(navigation_buttons)
    
    keyboard.append([InlineKeyboardButton("🎯 اتمام آزمون و ارسال پاسخ‌ها", callback_data="finish_exam")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    exam_setup['current_page'] = page
    context.user_data['exam_setup'] = exam_setup
    
    if 'exam_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=exam_setup['exam_message_id'],
                text=message_text,
                reply_markup=reply_markup
            )
            return
        except Exception as e:
            logger.error(f"Error editing message: {e}")
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        reply_markup=reply_markup
    )
    exam_setup['exam_message_id'] = message.message_id
    context.user_data['exam_setup'] = exam_setup

# نمایش سوالات برای وارد کردن پاسخ‌های صحیح
async def show_correct_answers_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    exam_setup = context.user_data['exam_setup']
    correct_answers = exam_setup.get('correct_answers', {})
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    total_questions = exam_setup.get('total_questions')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    # دریافت لیست سوالات بر اساس الگو
    question_list = exam_setup.get('question_list', [])
    
    total_pages = calculate_total_pages(total_questions)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * QUESTIONS_PER_PAGE
    end_idx = min(start_idx + QUESTIONS_PER_PAGE, total_questions)
    
    answered_count = len(correct_answers)
    
    message_text = f"📚 درس: {course_name}\n"
    message_text += f"📖 مبحث: {topic_name}\n"
    message_text += f"📄 صفحه {page} از {total_pages}\n"
    message_text += f"🔢 الگو: {get_pattern_name(question_pattern)}\n"
    message_text += f"✅ پاسخ‌های وارد شده: {answered_count}/{total_questions}\n\n"
    message_text += "لطفاً پاسخ‌های صحیح را برای سوالات زیر انتخاب کنید:\n\n"
    
    keyboard = []
    
    for i in range(start_idx, end_idx):
        question_num = question_list[i]
        current_answer = correct_answers.get(str(question_num))
        question_buttons = []
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
            if current_answer == option:
                button_text = f"{option} ✅"
            else:
                button_text = str(option)
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"correct_ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    navigation_buttons = []
    if total_pages > 1:
        if page > 1:
            navigation_buttons.append(InlineKeyboardButton("◀️ صفحه قبلی", callback_data=f"correct_page_{page-1}"))
        if page < total_pages:
            navigation_buttons.append(InlineKeyboardButton("صفحه بعدی ▶️", callback_data=f"correct_page_{page+1}"))
        
        if navigation_buttons:
            keyboard.append(navigation_buttons)
    
    if answered_count == total_questions:
        keyboard.append([InlineKeyboardButton("✅ اتمام وارد کردن پاسخ‌های صحیح", callback_data="finish_correct_answers")])
    else:
        keyboard.append([InlineKeyboardButton("⏳ لطفاً برای همه سوالات پاسخ وارد کنید", callback_data="ignore")])
    
    keyboard.append([InlineKeyboardButton("🔢 وارد کردن پاسخ‌ها به صورت رشته عددی", callback_data="switch_to_text_input")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    exam_setup['correct_answers_page'] = page
    context.user_data['exam_setup'] = exam_setup
    
    if 'correct_answers_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=exam_setup['correct_answers_message_id'],
                text=message_text,
                reply_markup=reply_markup
            )
            return
        except Exception as e:
            logger.error(f"Error editing correct answers message: {e}")
    
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
    else:
        chat_id = update.effective_chat.id
        
    message = await context.bot.send_message(
        chat_id=chat_id,
        text=message_text,
        reply_markup=reply_markup
    )
    exam_setup['correct_answers_message_id'] = message.message_id
    context.user_data['exam_setup'] = exam_setup

# ایجاد نوار پیشرفت
def create_progress_bar(percentage):
    filled = min(10, int(percentage / 10))
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage:.1f}%"

# تایمر با پیام پین شده
async def show_pinned_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, exam_setup: dict):
    exam_duration = exam_setup.get('exam_duration', 0)
    start_time = exam_setup.get('start_time')
    
    if not exam_duration or not start_time:
        return
    
    elapsed_time = (datetime.now() - start_time).total_seconds()
    remaining_time = max(0, exam_duration * 60 - elapsed_time)
    minutes = int(remaining_time // 60)
    seconds = int(remaining_time % 60)
    
    progress_percent = (elapsed_time / (exam_duration * 60)) * 100
    progress_bar = create_progress_bar(progress_percent)
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    timer_text = f"📚 {course_name} - {topic_name}\n🔢 {get_pattern_name(question_pattern)}\n⏳ باقیمانده: {minutes:02d}:{seconds:02d}\n{progress_bar}"
    
    if 'timer_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=exam_setup['timer_message_id'],
                text=timer_text,
                parse_mode='Markdown'
            )
            try:
                await context.bot.pin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id'],
                    disable_notification=True
                )
            except:
                pass
        except Exception as e:
            logger.error(f"Error editing timer message: {e}")
    else:
        try:
            message = await context.bot.send_message(
                chat_id=user_id,
                text=timer_text,
                parse_mode='Markdown'
            )
            exam_setup['timer_message_id'] = message.message_id
            try:
                await context.bot.pin_chat_message(
                    chat_id=user_id,
                    message_id=message.message_id,
                    disable_notification=True
                )
            except:
                pass
            if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
                context.bot_data['user_exams'][user_id] = exam_setup
        except Exception as e:
            logger.error(f"Error sending timer message: {e}")

# تایمر برای به روزرسانی زمان
async def update_timer(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.chat_id
    
    if 'user_exams' not in context.bot_data:
        return
    
    if user_id not in context.bot_data['user_exams']:
        return
    
    exam_setup = context.bot_data['user_exams'][user_id]
    
    if exam_setup.get('step') != 4:
        return
    
    exam_duration = exam_setup.get('exam_duration', 0)
    start_time = exam_setup.get('start_time')
    
    if not exam_duration or not start_time:
        return
    
    elapsed_time = (datetime.now() - start_time).total_seconds()
    remaining_time = max(0, exam_duration * 60 - elapsed_time)
    
    if remaining_time <= 0:
        await finish_exam_auto(context, user_id)
        return
    
    await show_pinned_timer(context, user_id, exam_setup)

# اتمام خودکار آزمون وقتی زمان تمام شد
async def finish_exam_auto(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if 'user_exams' not in context.bot_data or user_id not in context.bot_data['user_exams']:
        return
    
    exam_setup = context.bot_data['user_exams'][user_id]
    
    exam_setup['step'] = 'waiting_for_correct_answers_inline'
    exam_setup['correct_answers'] = {}
    context.bot_data['user_exams'][user_id] = exam_setup
    
    start_time = exam_setup.get('start_time')
    elapsed_time = calculate_elapsed_time(start_time)
    exam_setup['elapsed_time'] = elapsed_time
    
    job_name = f"timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    
    total_questions = exam_setup.get('total_questions')
    answered_count = len(exam_setup.get('answers', {}))
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    try:
        message = await context.bot.send_message(
            chat_id=user_id,
            text=f"📚 {course_name} - {topic_name}\n"
                 f"🔢 {get_pattern_name(question_pattern)}\n"
                 f"⏰ زمان آزمون به پایان رسید!\n"
                 f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
                 f"لطفاً پاسخ‌های صحیح را با استفاده از دکمه‌های زیر وارد کنید:"
        )
        
        await show_correct_answers_page(context, context, page=1)
        
        if 'timer_message_id' in exam_setup:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id']
                )
            except:
                pass
            
    except Exception as e:
        logger.error(f"Error sending auto-finish message: {e}")

# محاسبه زمان صرف شده
def calculate_elapsed_time(start_time):
    """محاسبه زمان سپری شده از شروع آزمون"""
    if not start_time:
        return 0
    elapsed = datetime.now() - start_time
    return round(elapsed.total_seconds() / 60, 2)  # بازگشت زمان بر حسب دقیقه

# پردازش مراحل ایجاد آزمون
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # بررسی لغو عملیات
    if text == "❌ لغو":
        context.user_data.pop('exam_setup', None)
        await update.message.reply_text(
            "✅ عملیات لغو شد.",
            reply_markup=get_main_keyboard()
        )
        return
    
    if 'exam_setup' not in context.user_data:
        await update.message.reply_text(
            "لطفا ابتدا با دکمه '📝 ساخت آزمون جدید' یک آزمون جدید شروع کنید.",
            reply_markup=get_main_keyboard()
        )
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') == 'course_name':
        if not text:
            await update.message.reply_text("❌ نام درس نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
            return
            
        exam_setup['course_name'] = text
        exam_setup['step'] = 'topic_name'
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text(
            "📖 لطفاً نام مبحث را وارد کنید:"
        )
    
    elif exam_setup.get('step') == 'topic_name':
        if not text:
            await update.message.reply_text("❌ نام مبحث نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
            return
            
        exam_setup['topic_name'] = text
        exam_setup['step'] = 1
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text(
            "🔢 لطفاً شماره اولین سوال را وارد کنید:"
        )
    
    elif exam_setup.get('step') == 1:
        try:
            start_question = int(text)
            if start_question <= 0:
                await update.message.reply_text("❌ شماره سوال باید بزرگتر از صفر باشد.")
                return
                
            exam_setup['start_question'] = start_question
            exam_setup['step'] = 2
            context.user_data['exam_setup'] = exam_setup
            await update.message.reply_text(
                "🔢 لطفاً شماره آخرین سوال را وارد کنید:"
            )
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 2:
        try:
            end_question = int(text)
            start_question = exam_setup.get('start_question')
            
            if end_question <= start_question:
                await update.message.reply_text("❌ شماره آخرین سوال باید بزرگتر از اولین سوال باشد.")
                return
            
            total_questions_original = end_question - start_question + 1
            if total_questions_original > 200:
                await update.message.reply_text("❌ حداکثر تعداد سوالات مجاز 200 عدد است.")
                return
                
            exam_setup['end_question'] = end_question
            exam_setup['total_questions_original'] = total_questions_original
            exam_setup['step'] = 'pattern_selection'
            context.user_data['exam_setup'] = exam_setup
            
            # نمایش دکمه‌های انتخاب الگو
            keyboard = [
                [InlineKeyboardButton("1️⃣ همه سوالات (پشت سر هم)", callback_data="pattern_all")],
                [InlineKeyboardButton("2️⃣ یکی در میان (زوج/فرد)", callback_data="pattern_alternate")],
                [InlineKeyboardButton("3️⃣ دو تا در میان", callback_data="pattern_every_two")],
                [InlineKeyboardButton("4️⃣ سه تا در میان", callback_data="pattern_every_three")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "🔢 لطفاً الگوی سوالات را انتخاب کنید:",
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 3:
        try:
            exam_duration = int(text)
            if exam_duration < 0:
                await update.message.reply_text("❌ زمان آزمون نمی‌تواند منفی باشد.")
                return
                
            exam_setup['exam_duration'] = exam_duration
            exam_setup['step'] = 4
            exam_setup['answers'] = {}
            exam_setup['start_time'] = datetime.now()
            context.user_data['exam_setup'] = exam_setup
            
            # ذخیره در bot_data برای دسترسی در jobها
            if 'user_exams' not in context.bot_data:
                context.bot_data['user_exams'] = {}
            context.bot_data['user_exams'][user_id] = exam_setup
            
            # شروع تایمر اگر زمان مشخص شده
            if exam_duration > 0:
                job_name = f"timer_{user_id}"
                # حذف jobهای قبلی
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                # ایجاد job جدید برای تایمر
                context.job_queue.run_repeating(
                    update_timer,
                    interval=5,  # به روزرسانی هر 5 ثانیه
                    first=1,
                    chat_id=user_id,
                    name=job_name
                )
            
            # نمایش اولین صفحه سوالات
            await show_questions_page(update, context, page=1)
            
            # نمایش تایمر پین شده
            await show_pinned_timer(context, user_id, exam_setup)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 'waiting_for_correct_answers':
        # این حالت برای پشتیبانی از حالت قدیمی (رشته عددی) نگه داشته شده است
        total_questions = exam_setup.get('total_questions')
        
        # حذف فاصله و کاراکترهای غیرعددی
        cleaned_text = ''.join(filter(str.isdigit, text))
        
        if len(cleaned_text) != total_questions:
            await update.message.reply_text(
                f"❌ رشته ارسالی باید شامل {total_questions} عدد باشد. شما {len(cleaned_text)} عدد وارد کردید. لطفاً مجدداً وارد کنید یا از دکمه‌های اینلاین استفاده کنید:"
            )
            return
        
        correct_answers = [int(char) for char in cleaned_text]
        user_answers = exam_setup.get('answers', {})
        correct_questions = []
        wrong_questions = []
        unanswered_questions = []
        
        # دریافت لیست سوالات بر اساس الگو
        question_list = exam_setup.get('question_list', [])
        
        for i, question_num in enumerate(question_list):
            user_answer = user_answers.get(str(question_num))
            correct_answer = correct_answers[i]
            
            if user_answer is None:
                unanswered_questions.append(question_num)
            elif user_answer == correct_answer:
                correct_questions.append(question_num)
            else:
                wrong_questions.append(question_num)
        
        # محاسبه نتایج
        correct_count = len(correct_questions)
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)

        # درصد بدون نمره منفی
        percentage_without_penalty = (correct_count / total_questions) * 100 if total_questions > 0 else 0

        # محاسبه نمره منفی
        raw_score = correct_count
        penalty = wrong_count / 3.0  # کسر ⅓ نمره به ازای هر پاسخ اشتباه
        final_score = max(0, raw_score - penalty)
        final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0

        # محاسبه زمان صرف شده
        elapsed_time = calculate_elapsed_time(exam_setup.get('start_time'))
        
        # دریافت تاریخ و زمان تهران
        jalali_date = get_jalali_date()
        tehran_time = get_tehran_time()
        
        # ذخیره نتایج در دیتابیس
        saved_to_db = False
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                
                cur.execute(
                    """
                    INSERT INTO exams 
                    (user_id, course_name, topic_name, start_question, end_question, total_questions, 
                     exam_duration, elapsed_time, answers, correct_answers, score, wrong_questions, 
                     unanswered_questions, jalali_date, tehran_time, question_pattern)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        exam_setup.get('course_name'),
                        exam_setup.get('topic_name'),
                        exam_setup.get('start_question'),
                        exam_setup.get('end_question'),
                        total_questions,
                        exam_setup.get('exam_duration'),
                        elapsed_time,
                        str(user_answers),
                        cleaned_text,
                        final_percentage,
                        str(wrong_questions),
                        str(unanswered_questions),
                        jalali_date,
                        tehran_time,
                        exam_setup.get('question_pattern', 'all')
                    )
                )
                conn.commit()
                cur.close()
                conn.close()
                saved_to_db = True
        except Exception as e:
            logger.error(f"Error saving to database: {e}")

        course_name = exam_setup.get('course_name', 'نامعلوم')
        topic_name = exam_setup.get('topic_name', 'نامعلوم')
        question_pattern = exam_setup.get('question_pattern', 'all')
        
        # ارسال نتایج
        result_text = f"""
📊 نتایج آزمون شما:

📚 درس: {course_name}
📖 مبحث: {topic_name}
🔢 الگو: {get_pattern_name(question_pattern)}
📅 تاریخ: {jalali_date}
⏰ زمان: {tehran_time}

✅ تعداد پاسخ صحیح: {correct_count}
❌ تعداد پاسخ اشتباه: {wrong_count}
⏸️ تعداد بی‌پاسخ: {unanswered_count}
📝 تعداد کل سوالات: {total_questions}
⏰ زمان صرف شده: {elapsed_time:.2f} دقیقه

📈 درصد بدون نمره منفی: {percentage_without_penalty:.2f}%
📉 درصد با نمره منفی: {final_percentage:.2f}%

🔢 سوالات صحیح: {', '.join(map(str, correct_questions)) if correct_questions else 'ندارد'}
🔢 سوالات غلط: {', '.join(map(str, wrong_questions)) if wrong_questions else 'ندارد'}
🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'ندارد'}

💡 نکته: هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد.
"""

        if not saved_to_db:
            result_text += "\n\n⚠️ نتایج در پایگاه داده ذخیره نشد (مشکل اتصال)."

        await update.message.reply_text(result_text, reply_markup=get_main_keyboard())
        
        # پاک کردن وضعیت آزمون و تایمر
        context.user_data.pop('exam_setup', None)
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            # آنپین کردن پیام تایمر
            exam_setup = context.bot_data['user_exams'][user_id]
            if 'timer_message_id' in exam_setup:
                try:
                    await context.bot.unpin_chat_message(
                        chat_id=user_id,
                        message_id=exam_setup['timer_message_id']
                    )
                except:
                    pass
            context.bot_data['user_exams'].pop(user_id, None)
        
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()

# مدیریت پاسخ‌های اینلاین

            # این حالت نباید اتفاق بیفتد چون د
# مدیریت پاسخ‌های اینلاین
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "ignore":
        return
    
    if 'exam_setup' not in context.user_data:
        await query.edit_message_text("⚠️ لطفا ابتدا یک آزمون جدید شروع کنید.")
        return
        
    exam_setup = context.user_data['exam_setup']
    
    # انتخاب الگوی سوالات
    if data.startswith("pattern_"):
        # نگاشت مستقیم callback data به pattern name
        pattern_map = {
            'pattern_all': 'all',
            'pattern_alternate': 'alternate', 
            'pattern_every_two': 'every_two',
            'pattern_every_three': 'every_three'
        }
        pattern = pattern_map.get(data, 'all')  # مقدار پیش‌فرض all

        exam_setup['question_pattern'] = pattern
        
        # محاسبه سوالات بر اساس الگو
        start_question = exam_setup.get('start_question')
        end_question = exam_setup.get('end_question')
        question_list = calculate_questions_by_pattern(start_question, end_question, pattern)
        total_questions = len(question_list)
        
        exam_setup['question_list'] = question_list
        exam_setup['total_questions'] = total_questions
        exam_setup['step'] = 3
        context.user_data['exam_setup'] = exam_setup
        
        # نمایش خلاصه و درخواست زمان
        course_name = exam_setup.get('course_name', 'نامعلوم')
        topic_name = exam_setup.get('topic_name', 'نامعلوم')
        
        summary_text = f"""
📋 خلاصه آزمون:

📚 درس: {course_name}
📖 مبحث: {topic_name}
🔢 محدوده سوالات: {start_question} تا {end_question}
🔢 الگو: {get_pattern_name(pattern)}
📝 تعداد سوالات: {total_questions}

⏰ لطفاً زمان آزمون را به دقیقه وارد کنید (اگر زمان محدود نمی‌خواهید، صفر وارد کنید):
"""
        await query.edit_message_text(summary_text)
        return
    
    elif data.startswith("ans_"):
        parts = data.split("_")
        question_num = int(parts[1])
        answer = int(parts[2])
        
        # بررسی آیا این گزینه قبلاً انتخاب شده است
        current_answer = exam_setup['answers'].get(str(question_num))
        
        if current_answer == answer:
            # اگر گزینه قبلاً انتخاب شده بود، آن را بردار (تیک را حذف کن)
            del exam_setup['answers'][str(question_num)]
        else:
            # اگر گزینه جدید است، آن را ثبت کن
            exam_setup['answers'][str(question_num)] = answer
        
        context.user_data['exam_setup'] = exam_setup
        
        # به روزرسانی در bot_data نیز
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        # نمایش مجدد صفحه فعلی با پاسخ به روز شده
        current_page = exam_setup.get('current_page', 1)
        await show_questions_page(update, context, current_page)
    
    elif data.startswith("correct_ans_"):
        parts = data.split("_")
        question_num = int(parts[2])
        answer = int(parts[3])
        
        # بررسی آیا این گزینه قبلاً انتخاب شده است
        current_answer = exam_setup['correct_answers'].get(str(question_num))
        
        if current_answer == answer:
            # اگر گزینه قبلاً انتخاب شده بود، آن را بردار (تیک را حذف کن)
            del exam_setup['correct_answers'][str(question_num)]
        else:
            # اگر گزینه جدید است، آن را ثبت کن
            exam_setup['correct_answers'][str(question_num)] = answer
        
        context.user_data['exam_setup'] = exam_setup
        
        # به روزرسانی در bot_data نیز
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        # نمایش مجدد صفحه فعلی پاسخ‌های صحیح
        current_page = exam_setup.get('correct_answers_page', 1)
        await show_correct_answers_page(update, context, current_page)
    
    elif data.startswith("page_"):
        # تغییر صفحه سوالات کاربر
        page = int(data.split("_")[1])
        await show_questions_page(update, context, page)
    
    elif data.startswith("correct_page_"):
        # تغییر صفحه پاسخ‌های صحیح
        page = int(data.split("_")[2])
        await show_correct_answers_page(update, context, page)
    
    elif data == "finish_exam":
        exam_setup['step'] = 'waiting_for_correct_answers_inline'
        exam_setup['correct_answers'] = {}
        context.user_data['exam_setup'] = exam_setup
        
        # محاسبه زمان صرف شده
        start_time = exam_setup.get('start_time')
        elapsed_time = calculate_elapsed_time(start_time)
        exam_setup['elapsed_time'] = elapsed_time
        
        # به روزرسانی در bot_data نیز
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        # حذف تایمر
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        # آنپین کردن پیام تایمر
        if 'timer_message_id' in exam_setup:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id']
                )
            except Exception as e:
                logger.error(f"Error unpinning timer message: {e}")
        
        total_questions = exam_setup.get('total_questions')
        answered_count = len(exam_setup.get('answers', {}))
        
        course_name = exam_setup.get('course_name', 'نامعلوم')
        topic_name = exam_setup.get('topic_name', 'نامعلوم')
        question_pattern = exam_setup.get('question_pattern', 'all')
        
        await query.edit_message_text(
            text=f"📚 {course_name} - {topic_name}\n"
                 f"🔢 {get_pattern_name(question_pattern)}\n"
                 f"📝 آزمون به پایان رسید.\n"
                 f"⏰ زمان صرف شده: {elapsed_time:.2f} دقیقه\n"
                 f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
                 f"لطفاً پاسخ‌های صحیح را با استفاده از دکمه‌های زیر وارد کنید:"
        )
        
        # نمایش اولین صفحه پاسخ‌های صحیح
        await show_correct_answers_page(update, context, page=1)
    
    elif data == "finish_correct_answers":
        total_questions = exam_setup.get('total_questions')
        correct_answers = exam_setup.get('correct_answers', {})
        
        if len(correct_answers) != total_questions:
            # این حالت نباید اتفاق بیفتد چون دکمه فقط زمانی فعال می‌شود که همه سوالات پاسخ داشته باشند
            await query.edit_message_text(
                text=f"❌ شما فقط برای {len(correct_answers)} سوال از {total_questions} سوال پاسخ صحیح وارد کرده‌اید.\n"
                     f"لطفاً پاسخ‌های صحیح باقی‌مانده را وارد کنید."
            )
            return
        
        user_answers = exam_setup.get('answers', {})
        correct_questions = []
        wrong_questions = []
        unanswered_questions = []
        
        # دریافت لیست سوالات بر اساس الگو
        question_list = exam_setup.get('question_list', [])
        
        # تبدیل پاسخ‌های صحیح به رشته برای ذخیره در دیتابیس
        correct_answers_list = []
        for question_num in question_list:
            str_question_num = str(question_num)
            correct_answer = correct_answers.get(str_question_num)
            if correct_answer is None:
                correct_answers_list.append('0')  # صفر برای سوالات بدون پاسخ صحیح
            else:
                correct_answers_list.append(str(correct_answer))
            
            user_answer = user_answers.get(str_question_num)
            if user_answer is None:
                unanswered_questions.append(question_num)
            elif user_answer == correct_answer:
                correct_questions.append(question_num)
            else:
                wrong_questions.append(question_num)
        
        correct_answers_str = ''.join(correct_answers_list)
        
        # محاسبه نتایج
        correct_count = len(correct_questions)
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)

        # درصد بدون نمره منفی
        percentage_without_penalty = (correct_count / total_questions) * 100 if total_questions > 0 else 0

        # محاسبه نمره منفی
        raw_score = correct_count
        penalty = wrong_count / 3.0  # کسر ⅓ نمره به ازای هر پاسخ اشتباه
        final_score = max(0, raw_score - penalty)
        final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0

        # محاسبه زمان صرف شده
        elapsed_time = exam_setup.get('elapsed_time', 0)
        
        # دریافت تاریخ و زمان تهران
        jalali_date = get_jalali_date()
        tehran_time = get_tehran_time()
        
        # ذخیره نتایج در دیتابیس
        saved_to_db = False
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                
                cur.execute(
                    """
                    INSERT INTO exams 
                    (user_id, course_name, topic_name, start_question, end_question, total_questions, 
                     exam_duration, elapsed_time, answers, correct_answers, score, wrong_questions, 
                     unanswered_questions, jalali_date, tehran_time, question_pattern)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        exam_setup.get('course_name'),
                        exam_setup.get('topic_name'),
                        exam_setup.get('start_question'),
                        exam_setup.get('end_question'),
                        total_questions,
                        exam_setup.get('exam_duration'),
                        elapsed_time,
                        str(user_answers),
                        correct_answers_str,
                        final_percentage,
                        str(wrong_questions),
                        str(unanswered_questions),
                        jalali_date,
                        tehran_time,
                        exam_setup.get('question_pattern', 'all')
                    )
                )
                conn.commit()
                cur.close()
                conn.close()
                saved_to_db = True
        except Exception as e:
            logger.error(f"Error saving to database: {e}")

        course_name = exam_setup.get('course_name', 'نامعلوم')
        topic_name = exam_setup.get('topic_name', 'نامعلوم')
        question_pattern = exam_setup.get('question_pattern', 'all')
        
        # ارسال نتایج
        result_text = f"""
📊 نتایج آزمون شما:

📚 درس: {course_name}
📖 مبحث: {topic_name}
🔢 الگو: {get_pattern_name(question_pattern)}
📅 تاریخ: {jalali_date}
⏰ زمان: {tehran_time}

✅ تعداد پاسخ صحیح: {correct_count}
❌ تعداد پاسخ اشتباه: {wrong_count}
⏸️ تعداد بی‌پاسخ: {unanswered_count}
📝 تعداد کل سوالات: {total_questions}
⏰ زمان صرف شده: {elapsed_time:.2f} دقیقه

📈 درصد بدون نمره منفی: {percentage_without_penalty:.2f}%
📉 درصد با نمره منفی: {final_percentage:.2f}%

🔢 سوالات صحیح: {', '.join(map(str, correct_questions)) if correct_questions else 'ندارد'}
🔢 سوالات غلط: {', '.join(map(str, wrong_questions)) if wrong_questions else 'ندارد'}
🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'ندارد'}

💡 نکته: هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد.
"""

        if not saved_to_db:
            result_text += "\n\n⚠️ نتایج در پایگاه داده ذخیره نشد (مشکل اتصال)."

        await query.edit_message_text(result_text)
        
        # پاک کردن وضعیت آزمون و تایمر
        context.user_data.pop('exam_setup', None)
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            # آنپین کردن پیام تایمر
            exam_setup = context.bot_data['user_exams'][user_id]
            if 'timer_message_id' in exam_setup:
                try:
                    await context.bot.unpin_chat_message(
                        chat_id=user_id,
                        message_id=exam_setup['timer_message_id']
                    )
                except:
                    pass
            context.bot_data['user_exams'].pop(user_id, None)
        
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
    
    elif data == "switch_to_text_input":
        # تغییر به حالت وارد کردن رشته عددی
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
        total_questions = exam_setup.get('total_questions')
        
        await query.edit_message_text(
            text=f"🔢 لطفاً پاسخ‌های صحیح را به صورت یک رشته عددی با {total_questions} رقم وارد کنید:\n\n"
                 f"📝 مثال: برای ۵ سوال: 12345\n"
                 f"💡 نکته: برای سوالات بی‌پاسخ از 0 استفاده کنید."
        )

# مشاهده نتایج قبلی
async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            if update.callback_query:
                await update.callback_query.message.reply_text("⚠️ در حال حاضر امکان دسترسی به تاریخچه نتایج وجود ندارد.")
            else:
                await update.message.reply_text("⚠️ در حال حاضر امکان دسترسی به تاریخچه نتایج وجود ندارد.")
            return
            
        cur = conn.cursor()
        
        cur.execute(
            "SELECT course_name, topic_name, created_at, score, start_question, end_question, exam_duration, elapsed_time, jalali_date, tehran_time, question_pattern FROM exams WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        )
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            result_text = "📋 آخرین نتایج آزمون‌های شما:\n\n"
            for i, result in enumerate(results, 1):
                try:
                    course_name, topic_name, date, score, start_q, end_q, duration, elapsed, jalali_date, tehran_time, question_pattern = result
                    
                    # بررسی مقادیر None
                    duration = duration or 0
                    elapsed = elapsed or 0
                    score = score or 0
                    start_q = start_q or 0
                    end_q = end_q or 0
                    course_name = course_name or 'نامعلوم'
                    topic_name = topic_name or 'نامعلوم'
                    jalali_date = jalali_date or 'نامعلوم'
                    tehran_time = tehran_time or 'نامعلوم'
                    question_pattern = question_pattern or 'all'
                    
                    time_text = f"{elapsed:.1f} دقیقه از {duration} دقیقه" if duration and duration > 0 else f"{elapsed:.1f} دقیقه"
                    pattern_name = get_pattern_name(question_pattern)
                    
                    result_text += f"{i}. {course_name} - {topic_name}\n"
                    result_text += f"   سوالات {start_q}-{end_q} - الگو: {pattern_name}\n"
                    result_text += f"   زمان: {time_text}\n"
                    result_text += f"   نمره: {score:.2f}% - تاریخ: {jalali_date} {tehran_time}\n\n"
                
                except Exception as e:
                    logger.error(f"Error processing result {i}: {e}")
                    result_text += f"{i}. خطا در پردازش نتیجه\n\n"
        else:
            result_text = "📭 هیچ نتیجه‌ای برای نمایش وجود ندارد."
            
    except Exception as e:
        logger.error(f"Error retrieving results: {e}")
        result_text = "⚠️ خطایی در دریافت نتایج رخ داد."
    
    if update.callback_query:
        await update.callback_query.message.reply_text(result_text)
    else:
        await update.message.reply_text(result_text)

# گزارش روزانه برای ادمین
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        if conn is None:
            return
            
        cur = conn.cursor()
        
        # تعداد کاربران جدید امروز
        today_jalali = get_jalali_date()
        cur.execute("SELECT COUNT(*) FROM users WHERE jalali_date = %s", (today_jalali,))
        new_users_today = cur.fetchone()[0]
        
        # تعداد کل کاربران
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        
        # تعداد آزمون‌های امروز
        cur.execute("SELECT COUNT(*) FROM exams WHERE jalali_date = %s", (today_jalali,))
        exams_today = cur.fetchone()[0]
        
        # تعداد کل آزمون‌ها
        cur.execute("SELECT COUNT(*) FROM exams")
        total_exams = cur.fetchone()[0]
        
        # آمار الگوهای استفاده شده
        cur.execute("SELECT question_pattern, COUNT(*) FROM exams WHERE jalali_date = %s GROUP BY question_pattern", (today_jalali,))
        pattern_stats = cur.fetchall()
        
        cur.close()
        conn.close()
        
        pattern_text = ""
        for pattern, count in pattern_stats:
            pattern_name = get_pattern_name(pattern)
            pattern_text += f"   • {pattern_name}: {count} آزمون\n"
        
        report_text = f"""
📊 گزارش روزانه ربات

📅 تاریخ: {today_jalali}
👥 کاربران جدید امروز: {new_users_today}
👤 تعداد کل کاربران: {total_users}
📝 آزمون‌های امروز: {exams_today}
📚 تعداد کل آزمون‌ها: {total_exams}

🔢 آمار الگوهای سوالات:
{pattern_text if pattern_text else "   • امروز هیچ آزمونی ثبت نشده"}

💫 ربات در حال فعالیت است...
"""
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=report_text
        )
        
    except Exception as e:
        logger.error(f"Error sending daily report: {e}")

# تابع اصلی
def main():
    if not init_db():
        logger.warning("Database initialization failed. The bot will work without database support.")
    
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CommandHandler("about", show_about))
    
    application.add_handler(CallbackQueryHandler(handle_button, pattern="^(new_exam|results|help)$"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern="^(pattern_|ans_|correct_ans_|page_|correct_page_|finish_exam|finish_correct_answers|switch_to_text_input|ignore)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_message))
    
    # تنظیم job برای گزارش روزانه (هر روز ساعت 8 صبح)
    job_queue = application.job_queue
    if job_queue:
        # زمان‌بندی برای ساعت 8 صبح تهران
        job_queue.run_daily(
            send_daily_report,
            time=time(hour=8, minute=0, second=0, tzinfo=TEHRAN_TZ),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="daily_report"
        )
    
    logger.info("Bot started with enhanced features and question patterns...")
    application.run_polling()

if __name__ == "__main__":
    main()
