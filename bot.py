import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
import jdatetime  # برای تاریخ شمسی
import pytz  # برای منطقه زمانی
import requests
import json

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توکن ربات
TOKEN = "7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ"

# تنظیمات Hugging Face API
HF_API_TOKEN = os.environ.get('HF_API_TOKEN', '')

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
QUESTIONS_PER_PAGE = 10  # حداکثر ۱۰ سوال در هر صفحه

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
        
        # ایجاد جدول اگر وجود ندارد
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

# تحلیل نتایج با هوش مصنوعی
async def analyze_results_with_ai(exam_data):
    """تحلیل نتایج آزمون با Hugging Face API"""
    try:
        if not HF_API_TOKEN:
            return "❌ توکن API تنظیم نشده است. امکان تحلیل هوشمند وجود ندارد."
        
        course_name = exam_data.get('course_name', 'نامعلوم')
        topic_name = exam_data.get('topic_name', 'نامعلوم')
        total_questions = exam_data.get('total_questions', 0)
        correct_count = len(exam_data.get('correct_questions', []))
        wrong_count = len(exam_data.get('wrong_questions', []))
        unanswered_count = len(exam_data.get('unanswered_questions', []))
        score = exam_data.get('score', 0)
        elapsed_time = exam_data.get('elapsed_time', 0)
        question_pattern = exam_data.get('question_pattern', 'all')
        
        # ایجاد prompt برای تحلیل
        prompt = f"""
        شما یک معلم باتجربه هستید. لطفاً نتایج این آزمون را تحلیل و راهنمایی‌های مفید ارائه دهید:

        اطلاعات آزمون:
        - درس: {course_name}
        - مبحث: {topic_name}
        - الگوی سوالات: {get_pattern_name(question_pattern)}
        - تعداد کل سوالات: {total_questions}
        - تعداد پاسخ‌های صحیح: {correct_count}
        - تعداد پاسخ‌های اشتباه: {wrong_count}
        - تعداد سوالات بی‌پاسخ: {unanswered_count}
        - نمره نهایی: {score:.2f}%
        - زمان صرف شده: {elapsed_time:.2f} دقیقه

        لطفاً تحلیل خود را به زبان فارسی و در قالب زیر ارائه دهید:
        1. ارزیابی کلی عملکرد
        2. نقاط قوت و ضعف
        3. پیشنهادات برای بهبود
        4. راهکارهای کاهش اشتباهات
        5. مدیریت زمان (اگر زمان محدود بوده)

        تحلیل خود را مختصر و مفید (حداکثر 300 کلمه) ارائه دهید.
        """
        
        api_url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.1"
        
        headers = {
            "Authorization": f"Bearer {HF_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 500,
                "temperature": 0.7,
                "do_sample": True,
                "return_full_text": False
            }
        }
        
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                analysis = result[0].get('generated_text', '').strip()
                # پاک‌سازی متن
                if prompt.strip() in analysis:
                    analysis = analysis.replace(prompt.strip(), "").strip()
                return analysis if analysis else "🤖 تحلیل هوشمند در دسترس نیست. لطفاً نتایج را خودتان بررسی کنید."
        else:
            return f"❌ خطا در تحلیل هوشمند: {response.status_code}"
            
    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        return f"❌ خطا در تحلیل هوشمند: {str(e)}"
    
    return "🤖 تحلیل هوشمند در دسترس نیست. لطفاً نتایج را خودتان بررسی کنید."

# تحلیل پیشرفته نتایج
def advanced_analysis(exam_data):
    """تحلیل پیشرفته نتایج بدون نیاز به API"""
    course_name = exam_data.get('course_name', 'نامعلوم')
    topic_name = exam_data.get('topic_name', 'نامعلوم')
    total_questions = exam_data.get('total_questions', 0)
    correct_count = len(exam_data.get('correct_questions', []))
    wrong_count = len(exam_data.get('wrong_questions', []))
    unanswered_count = len(exam_data.get('unanswered_questions', []))
    score = exam_data.get('score', 0)
    elapsed_time = exam_data.get('elapsed_time', 0)
    question_pattern = exam_data.get('question_pattern', 'all')
    
    # محاسبات آماری
    accuracy_rate = (correct_count / total_questions) * 100 if total_questions > 0 else 0
    completion_rate = ((correct_count + wrong_count) / total_questions) * 100 if total_questions > 0 else 0
    time_per_question = elapsed_time / total_questions if total_questions > 0 else 0
    
    analysis = "📊 **تحلیل پیشرفته نتایج:**\n\n"
    
    # ارزیابی کلی
    if score >= 80:
        analysis += "🎉 **عملکرد عالی!** شما تسلط خوبی روی این مبحث دارید.\n"
    elif score >= 60:
        analysis += "👍 **عملکرد قابل قبول!** نیاز به تمرین بیشتر دارید.\n"
    elif score >= 40:
        analysis += "⚠️ **نیاز به بهبود!** باید روی این مبحث بیشتر کار کنید.\n"
    else:
        analysis += "🔴 **نیاز به بازآموزی!** بهتر است این مبحث را از ابتدا مطالعه کنید.\n"
    
    analysis += f"\n📈 **آمار دقیق:**\n"
    analysis += f"• دقت پاسخ‌ها: {accuracy_rate:.1f}%\n"
    analysis += f"• میزان تکمیل آزمون: {completion_rate:.1f}%\n"
    analysis += f"• زمان متوسط هر سوال: {time_per_question:.1f} دقیقه\n"
    
    # تحلیل الگوی اشتباهات
    if wrong_count > 0:
        wrong_percentage = (wrong_count / total_questions) * 100
        analysis += f"\n❌ **تحلیل اشتباهات:**\n"
        analysis += f"• {wrong_percentage:.1f}% سوالات اشتباه پاسخ داده شده\n"
        
        if wrong_percentage > 30:
            analysis += "• **هشدار:** تعداد اشتباهات بالا است! احتمالاً در فهم مفاهیم مشکل دارید.\n"
        elif wrong_percentage > 15:
            analysis += "• **توجه:** نیاز به دقت بیشتر در خواندن سوالات دارید.\n"
    
    # تحلیل سوالات بی‌پاسخ
    if unanswered_count > 0:
        unanswered_percentage = (unanswered_count / total_questions) * 100
        analysis += f"\n⏸️ **تحلیل بی‌پاسخ‌ها:**\n"
        analysis += f"• {unanswered_percentage:.1f}% سوالات بی‌پاسخ مانده\n"
        
        if unanswered_percentage > 50:
            analysis += "• **هشدار:** زمان‌بندی مناسب نیست! باید سرعت خود را افزایش دهید.\n"
        elif unanswered_percentage > 20:
            analysis += "• **توجه:** نیاز به مدیریت بهتر زمان دارید.\n"
    
    # پیشنهادات
    analysis += f"\n💡 **پیشنهادات بهبود:**\n"
    
    if accuracy_rate < 70:
        analysis += "• مفاهیم اصلی را مجدداً مطالعه کنید\n"
        analysis += "• روی سوالات تشریحی بیشتر تمرین کنید\n"
    
    if time_per_question > 2:
        analysis += "• تکنیک‌های تست‌زنی سریع را یاد بگیرید\n"
        analysis += "• زمان‌بندی را در آزمون‌های بعدی بهبود دهید\n"
    
    if wrong_count > correct_count / 2:
        analysis += "• قبل از پاسخ دادن، سوالات را با دقت بیشتری بخوانید\n"
        analysis += "• از روش حذف گزینه‌های غلط استفاده کنید\n"
    
    analysis += "• آزمون‌های مشابه بیشتری تمرین کنید\n"
    analysis += "• نقاط ضعف خود را شناسایی و برطرف کنید\n"
    
    return analysis

# نمایش نتایج با تحلیل پیشرفته
async def show_detailed_results(update: Update, context: ContextTypes.DEFAULT_TYPE, exam_data, exam_id=None):
    """نمایش نتایج با تحلیل پیشرفته"""
    user_id = update.effective_user.id
    
    course_name = exam_data.get('course_name', 'نامعلوم')
    topic_name = exam_data.get('topic_name', 'نامعلوم')
    total_questions = exam_data.get('total_questions', 0)
    correct_count = len(exam_data.get('correct_questions', []))
    wrong_count = len(exam_data.get('wrong_questions', []))
    unanswered_count = len(exam_data.get('unanswered_questions', []))
    score = exam_data.get('score', 0)
    elapsed_time = exam_data.get('elapsed_time', 0)
    question_pattern = exam_data.get('question_pattern', 'all')
    jalali_date = exam_data.get('jalali_date', '')
    tehran_time = exam_data.get('tehran_time', '')
    
    # متن اصلی نتایج
    result_text = f"""
📊 **نتایج آزمون شما:**

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

📈 درصد بدون نمره منفی: {(correct_count/total_questions)*100:.2f}%
📉 درصد با نمره منفی: {score:.2f}%

🔢 سوالات صحیح: {', '.join(map(str, exam_data.get('correct_questions', []))) if exam_data.get('correct_questions') else 'ندارد'}
🔢 سوالات غلط: {', '.join(map(str, exam_data.get('wrong_questions', []))) if exam_data.get('wrong_questions') else 'ندارد'}
🔢 سوالات بی‌پاسخ: {', '.join(map(str, exam_data.get('unanswered_questions', []))) if exam_data.get('unanswered_questions') else 'ندارد'}

💡 نکته: هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد.
"""
    
    # اضافه کردن تحلیل پیشرفته
    advanced_analysis_text = advanced_analysis(exam_data)
    result_text += f"\n{advanced_analysis_text}"
    
    # ایجاد دکمه‌های اینلاین برای تحلیل بیشتر
    keyboard = [
        [InlineKeyboardButton("🤖 تحلیل هوشمند با AI", callback_data=f"ai_analysis_{exam_id}")],
        [InlineKeyboardButton("📊 مقایسه با نتایج قبلی", callback_data=f"compare_results_{exam_id}")],
        [InlineKeyboardButton("💾 ذخیره نتایج", callback_data=f"save_results_{exam_id}")],
        [InlineKeyboardButton("🔄 آزمون جدید", callback_data="new_exam")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(result_text, reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(result_text, reply_markup=reply_markup)

# مدیریت callback query برای تحلیل‌های بیشتر
async def handle_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت callback query برای تحلیل‌های بیشتر"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data.startswith("ai_analysis_"):
        exam_id = data.split("_")[2]
        
        # دریافت داده‌های آزمون از دیتابیس
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM exams WHERE id = %s AND user_id = %s",
                    (exam_id, user_id)
                )
                exam_record = cur.fetchone()
                cur.close()
                conn.close()
                
                if exam_record:
                    # تبدیل داده‌های دیتابیس به فرمت مورد نیاز
                    exam_data = {
                        'course_name': exam_record[2],
                        'topic_name': exam_record[3],
                        'total_questions': exam_record[6],
                        'score': exam_record[11],
                        'elapsed_time': exam_record[8],
                        'question_pattern': exam_record[17],
                        'correct_questions': eval(exam_record[13]) if exam_record[13] else [],
                        'wrong_questions': eval(exam_record[12]) if exam_record[12] else [],
                        'unanswered_questions': eval(exam_record[14]) if exam_record[14] else []
                    }
                    
                    await query.edit_message_text("🤖 در حال تحلیل نتایج با هوش مصنوعی...")
                    
                    # تحلیل با هوش مصنوعی
                    ai_analysis = await analyze_results_with_ai(exam_data)
                    
                    analysis_text = f"""
🎯 **تحلیل هوشمند نتایج:**

{ai_analysis}

💡 **نکات کلیدی:**
• نقاط قوت خود را حفظ کنید
• روی نقاط ضعف تمرکز کنید
• مدیریت زمان را بهبود دهید
• آزمون‌های بیشتری تمرین کنید
"""
                    
                    keyboard = [
                        [InlineKeyboardButton("🔙 بازگشت به نتایج", callback_data=f"back_to_results_{exam_id}")],
                        [InlineKeyboardButton("🔄 آزمون جدید", callback_data="new_exam")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(analysis_text, reply_markup=reply_markup)
                    return
                    
        except Exception as e:
            logger.error(f"Error in AI analysis callback: {e}")
            await query.edit_message_text("❌ خطا در تحلیل هوشمند. لطفاً مجدداً تلاش کنید.")
    
    elif data.startswith("compare_results_"):
        exam_id = data.split("_")[2]
        await show_comparison(update, context, user_id, exam_id)
    
    elif data.startswith("save_results_"):
        exam_id = data.split("_")[2]
        await query.answer("✅ نتایج در پایگاه داده ذخیره شد!", show_alert=True)
    
    elif data.startswith("back_to_results_"):
        exam_id = data.split("_")[3]
        # بازگشت به صفحه نتایج (نیاز به پیاده‌سازی دارد)
        await query.answer("بازگشت به نتایج")
    
    elif data == "new_exam":
        await new_exam(update, context)

# نمایش مقایسه با نتایج قبلی
async def show_comparison(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, current_exam_id: int):
    """نمایش مقایسه با نتایج قبلی"""
    try:
        conn = get_db_connection()
        if not conn:
            await update.callback_query.answer("❌ خطا در اتصال به پایگاه داده.")
            return
            
        cur = conn.cursor()
        
        # دریافت نتایج قبلی
        cur.execute(
            """
            SELECT id, course_name, topic_name, score, total_questions, jalali_date
            FROM exams 
            WHERE user_id = %s AND id != %s
            ORDER BY created_at DESC 
            LIMIT 5
            """,
            (user_id, current_exam_id)
        )
        
        previous_results = cur.fetchall()
        
        # دریافت نتیجه فعلی
        cur.execute(
            "SELECT course_name, topic_name, score, total_questions FROM exams WHERE id = %s",
            (current_exam_id,)
        )
        current_result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not current_result:
            await update.callback_query.answer("❌ نتیجه فعلی یافت نشد.")
            return
        
        current_course, current_topic, current_score, current_total = current_result
        
        comparison_text = f"""
📊 **مقایسه با نتایج قبلی:**

📚 آزمون فعلی:
• درس: {current_course} - مبحث: {current_topic}
• نمره: {current_score:.2f}% - تعداد سوالات: {current_total}

"""
        
        if previous_results:
            comparison_text += "📈 نتایج قبلی:\n"
            for i, (exam_id, course, topic, score, total, date) in enumerate(previous_results, 1):
                trend = "📈" if score < current_score else "📉" if score > current_score else "➡️"
                comparison_text += f"{i}. {course} - {topic}\n"
                comparison_text += f"   نمره: {score:.2f}% {trend} - تاریخ: {date}\n\n"
            
            # تحلیل روند
            avg_previous = sum(score for _, _, _, score, _, _ in previous_results) / len(previous_results)
            if current_score > avg_previous:
                comparison_text += "🎉 **تبریک! پیشرفت داشته‌اید!**\n"
            elif current_score < avg_previous:
                comparison_text += "⚠️ **نیاز به تمرین بیشتر دارید!**\n"
            else:
                comparison_text += "➡️ **عملکرد شما پایدار است!**\n"
        else:
            comparison_text += "📭 هیچ نتیجه قبلی برای مقایسه یافت نشد.\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"back_to_results_{current_exam_id}")],
            [InlineKeyboardButton("🔄 آزمون جدید", callback_data="new_exam")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(comparison_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in comparison: {e}")
        await update.callback_query.answer("❌ خطا در مقایسه نتایج.")

# تابع کمکی برای دریافت نام الگو
def get_pattern_name(pattern):
    pattern_names = {
        'all': 'همه سوالات (پشت سر هم)',
        'alternate': 'یکی در میان (زوج/فرد)',
        'every_two': 'دو تا در میان',
        'every_three': 'سه تا در میان'
    }
    return pattern_names.get(pattern, 'نامعلوم')

# در تابع handle_callback_query اصلی، این قسمت را اضافه کنید:
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # ... کدهای موجود ...
    
    # اضافه کردن مدیریت تحلیل‌ها
    if (query.data.startswith("ai_analysis_") or 
        query.data.startswith("compare_results_") or 
        query.data.startswith("save_results_") or
        query.data.startswith("back_to_results_")):
        await handle_analysis_callback(update, context)
        return
    
    # ... بقیه کدهای موجود ...

# در تابع finish_correct_answers، جایگزین کردن نمایش نتایج ساده با نمایش پیشرفته:
# به جای این:
# await query.edit_message_text(result_text)

# از این استفاده کنید:
exam_data = {
    'course_name': exam_setup.get('course_name'),
    'topic_name': exam_setup.get('topic_name'),
    'total_questions': total_questions,
    'score': final_percentage,
    'elapsed_time': elapsed_time,
    'question_pattern': exam_setup.get('question_pattern', 'all'),
    'jalali_date': jalali_date,
    'tehran_time': tehran_time,
    'correct_questions': correct_questions,
    'wrong_questions': wrong_questions,
    'unanswered_questions': unanswered_questions
}

# ذخیره در دیتابیس و دریافت ID
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
            RETURNING id
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
        exam_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        # نمایش نتایج با تحلیل پیشرفته
        await show_detailed_results(update, context, exam_data, exam_id)
        
except Exception as e:
    logger.error(f"Error saving to database: {e}")
    # نمایش نتایج ساده در صورت خطا
    await query.edit_message_text(result_text)

# تابع اصلی
def main():
    # راه‌اندازی دیتابیس
    if not init_db():
        logger.error("Failed to initialize database. Exiting.")
        return
    
    # ایجاد اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # شروع ربات
    print("🤖 ربات در حال اجرا است...")
    application.run_polling()

if __name__ == "__main__":
    main()
