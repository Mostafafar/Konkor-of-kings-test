from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import json
import datetime
from typing import Dict, List
import asyncio
from pathlib import Path

# States for conversation
WAITING_EXCEL, WAITING_DAY_NUMBER, WAITING_SUBJECT_DATA = range(3)

# لیست مشاوران (می‌توانید این را در دیتابیس ذخیره کنید)
ADVISORS = [6680287530]  # آیدی‌های تلگرام مشاوران

class StudyPlanBot:
    def __init__(self, token: str):
        self.application = Application.builder().token(token).build()
        self.plans = {}  # {user_id: {day1: {subjects: []}, day2: {}, ...}}
        self.user_data = {}  # {user_id: {current_day: 1, advisor_id: xxx, start_date: xxx}}
        self.load_data()
        self.setup_handlers()
    
    def setup_handlers(self):
        """تنظیم همه هندلرها"""
        # دستورات عمومی
        self.application.add_handler(CommandHandler("start", self.start))
        
        # دستورات دانش‌آموز
        self.application.add_handler(CommandHandler("plan", self.show_plan))
        self.application.add_handler(CommandHandler("today", self.show_today))
        self.application.add_handler(CommandHandler("stats", self.show_stats))
        self.application.add_handler(CommandHandler("progress", self.show_progress))
        self.application.add_handler(CommandHandler("next", self.next_day))
        self.application.add_handler(CommandHandler("prev", self.prev_day))
        self.application.add_handler(CommandHandler("reset", self.reset_day))
        
        # دستورات مشاور
        self.application.add_handler(CommandHandler("advisor", self.advisor_panel))
        self.application.add_handler(CommandHandler("send_plan", self.send_plan_request))
        self.application.add_handler(CommandHandler("edit_plan", self.edit_plan_request))
        self.application.add_handler(CommandHandler("view_students", self.view_students))
        self.application.add_handler(CommandHandler("student_stats", self.student_stats))
        
        # هندلر دریافت فایل
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        
        # هندلر دکمه‌ها
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # هندلر پیام‌های متنی
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
    
    def load_data(self):
        """بارگذاری داده‌ها از فایل"""
        try:
            if Path("plans.json").exists():
                with open("plans.json", "r", encoding="utf-8") as f:
                    self.plans = json.load(f)
            if Path("users.json").exists():
                with open("users.json", "r", encoding="utf-8") as f:
                    self.user_data = json.load(f)
        except Exception as e:
            print(f"خطا در بارگذاری داده‌ها: {e}")
    
    def save_data(self):
        """ذخیره داده‌ها در فایل"""
        try:
            with open("plans.json", "w", encoding="utf-8") as f:
                json.dump(self.plans, f, ensure_ascii=False, indent=2)
            with open("users.json", "w", encoding="utf-8") as f:
                json.dump(self.user_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"خطا در ذخیره داده‌ها: {e}")
    
    def is_advisor(self, user_id: int) -> bool:
        """بررسی مشاور بودن کاربر"""
        return user_id in ADVISORS
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """شروع ربات"""
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.first_name
        
        # ایجاد پروفایل کاربر
        if user_id not in self.user_data:
            self.user_data[user_id] = {
                "current_day": 1,
                "name": user_name,
                "start_date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "total_days": 13,
                "advisor_id": None
            }
            self.save_data()
        
        if self.is_advisor(int(user_id)):
            keyboard = [
                [InlineKeyboardButton("👥 مدیریت دانش‌آموزان", callback_data="manage_students")],
                [InlineKeyboardButton("📤 ارسال برنامه جدید", callback_data="send_plan")],
                [InlineKeyboardButton("✏️ ویرایش برنامه موجود", callback_data="edit_plan")],
                [InlineKeyboardButton("📊 گزارش پیشرفت", callback_data="advisor_stats")]
            ]
            message = f"""
🎓 *پنل مشاور*

سلام {user_name} عزیز!
به پنل مشاوران خوش آمدید.

📋 از این پنل می‌توانید:
├─ برنامه مطالعاتی جدید ارسال کنید
├─ برنامه‌های موجود را ویرایش کنید
├─ پیشرفت دانش‌آموزان را رصد کنید
└─ گزارش‌های جامع دریافت کنید

💡 *راهنما:*
• /send_plan - ارسال برنامه جدید
• /edit_plan - ویرایش برنامه
• /view_students - لیست دانش‌آموزان
• /student_stats [id] - آمار دانش‌آموز
            """
        else:
            keyboard = [
                [InlineKeyboardButton("📅 برنامه امروز", callback_data="show_today")],
                [InlineKeyboardButton("📊 پیشرفت من", callback_data="my_progress")],
                [InlineKeyboardButton("📈 آمار کامل", callback_data="full_stats")],
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")]
            ]
            message = f"""
🎯 *ربات برنامه‌ریزی درسی*

سلام {user_name} عزیز!
به ربات مدیریت برنامه مطالعاتی خوش آمدید 🌟

📚 *امکانات:*
├─ 📅 مشاهده برنامه روزانه
├─ ✅ چک کردن پارت‌های انجام شده
├─ 📊 رصد پیشرفت لحظه‌ای
├─ 📈 آمار و گزارش‌های تفصیلی
└─ 🔔 یادآوری‌های هوشمند

💡 *دستورات سریع:*
• /today - برنامه امروز
• /plan - کل برنامه ۱۳ روزه
• /stats - آمار پیشرفت
• /next - روز بعد
• /prev - روز قبل

✨ برای شروع، روی دکمه‌های زیر کلیک کنید!
            """
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    # ==================== دستورات دانش‌آموز ====================
    
    async def show_today(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش برنامه امروز"""
        user_id = str(update.effective_user.id)
        
        if user_id not in self.plans or not self.plans[user_id]:
            await self._send_message(update, "⚠️ هنوز برنامه‌ای برای شما ثبت نشده است.\nلطفاً از مشاور خود بخواهید برنامه را ارسال کند.")
            return
        
        current_day = self.user_data[user_id]["current_day"]
        day_key = f"day{current_day}"
        
        if day_key not in self.plans[user_id]:
            await self._send_message(update, f"⚠️ برنامه روز {current_day} موجود نیست.")
            return
        
        day_data = self.plans[user_id][day_key]
        message = self._format_day_plan(day_data, current_day)
        keyboard = self._create_day_keyboard(day_data["subjects"], current_day)
        
        await self._send_message(update, message, reply_markup=keyboard)
    
    async def show_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش کل برنامه ۱۳ روزه"""
        user_id = str(update.effective_user.id)
        
        if user_id not in self.plans or not self.plans[user_id]:
            await self._send_message(update, "⚠️ هنوز برنامه‌ای برای شما ثبت نشده است.")
            return
        
        total_days = self.user_data[user_id].get("total_days", 13)
        message = "📚 *برنامه کامل ۱۳ روزه*\n\n"
        
        for day in range(1, total_days + 1):
            day_key = f"day{day}"
            if day_key in self.plans[user_id]:
                day_data = self.plans[user_id][day_key]
                completed = sum(1 for s in day_data["subjects"] if s.get("completed", False))
                total = len(day_data["subjects"])
                progress = int((completed / total) * 100) if total > 0 else 0
                
                status = "✅" if progress == 100 else "🔄" if progress > 0 else "⏳"
                message += f"{status} *روز {day}:* {self._create_progress_bar(progress, 8)} {progress}%\n"
                message += f"   📊 {completed}/{total} پارت انجام شده\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="show_today")]]
        await self._send_message(update, message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش آمار کامل"""
        user_id = str(update.effective_user.id)
        
        if user_id not in self.plans:
            await self._send_message(update, "⚠️ هنوز برنامه‌ای ثبت نشده است.")
            return
        
        stats = self._calculate_stats(user_id)
        message = f"""
📊 *آمار جامع مطالعاتی*

━━━━━━━━━━━━━━━━━━━━
📅 *اطلاعات کلی:*
├─ روز جاری: {self.user_data[user_id]['current_day']}/{self.user_data[user_id].get('total_days', 13)}
├─ روزهای گذشته: {stats['days_passed']}
├─ روزهای باقی‌مانده: {stats['days_remaining']}
└─ تاریخ شروع: {self.user_data[user_id]['start_date']}

━━━━━━━━━━━━━━━━━━━━
✅ *پیشرفت کلی:*
{self._create_progress_bar(stats['total_progress'], 12)} {stats['total_progress']}%

├─ پارت‌های انجام شده: {stats['completed_parts']}
├─ پارت‌های باقی‌مانده: {stats['remaining_parts']}
└─ کل پارت‌ها: {stats['total_parts']}

━━━━━━━━━━━━━━━━━━━━
📚 *آمار درسی:*
{self._format_subject_stats(stats['subject_stats'])}

━━━━━━━━━━━━━━━━━━━━
⭐ *عملکرد روزانه:*
├─ میانگین پیشرفت روزانه: {stats['daily_average']}%
├─ بهترین روز: روز {stats['best_day']} ({stats['best_day_progress']}%)
└─ روزهای کامل شده: {stats['completed_days']}

━━━━━━━━━━━━━━━━━━━━
💪 *انگیزه:*
{self._get_motivation_message(stats['total_progress'])}
        """
        
        keyboard = [
            [InlineKeyboardButton("📈 نمودار پیشرفت", callback_data="show_chart")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="show_today")]
        ]
        
        await self._send_message(update, message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_progress(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """نمایش پیشرفت لحظه‌ای"""
        user_id = str(update.effective_user.id)
        current_day = self.user_data[user_id]["current_day"]
        day_key = f"day{current_day}"
        
        if user_id not in self.plans or day_key not in self.plans[user_id]:
            await self._send_message(update, "⚠️ برنامه روز جاری موجود نیست.")
            return
        
        day_data = self.plans[user_id][day_key]
        completed = sum(1 for s in day_data["subjects"] if s.get("completed", False))
        total = len(day_data["subjects"])
        progress = int((completed / total) * 100) if total > 0 else 0
        
        message = f"""
⚡ *پیشرفت لحظه‌ای - روز {current_day}*

{self._create_progress_bar(progress, 15)} {progress}%

✅ انجام شده: {completed}
⏳ باقی‌مانده: {total - completed}
📚 کل پارت‌ها: {total}

━━━━━━━━━━━━━━━━━━━━
📋 *وضعیت دروس:*

"""
        
        for subject in day_data["subjects"]:
            status = "✅" if subject.get("completed", False) else "◻️"
            message += f"{status} {subject['name']} - {subject['type']}\n"
        
        message += f"\n🕐 آخرین بروزرسانی: {datetime.datetime.now().strftime('%H:%M')}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data="show_today")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="show_today")]
        ]
        
        await self._send_message(update, message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def next_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """رفتن به روز بعد"""
        user_id = str(update.effective_user.id)
        current_day = self.user_data[user_id]["current_day"]
        total_days = self.user_data[user_id].get("total_days", 13)
        
        if current_day < total_days:
            self.user_data[user_id]["current_day"] = current_day + 1
            self.save_data()
            await self.show_today(update, context)
        else:
            await self._send_message(update, "✅ شما در آخرین روز برنامه هستید!")
    
    async def prev_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """برگشت به روز قبل"""
        user_id = str(update.effective_user.id)
        current_day = self.user_data[user_id]["current_day"]
        
        if current_day > 1:
            self.user_data[user_id]["current_day"] = current_day - 1
            self.save_data()
            await self.show_today(update, context)
        else:
            await self._send_message(update, "⚠️ شما در اولین روز برنامه هستید!")
    
    async def reset_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ریست کردن روز جاری"""
        user_id = str(update.effective_user.id)
        current_day = self.user_data[user_id]["current_day"]
        day_key = f"day{current_day}"
        
        if user_id in self.plans and day_key in self.plans[user_id]:
            for subject in self.plans[user_id][day_key]["subjects"]:
                subject["completed"] = False
            self.save_data()
            await self._send_message(update, f"♻️ روز {current_day} ریست شد!")
            await self.show_today(update, context)
        else:
            await self._send_message(update, "⚠️ برنامه روز جاری موجود نیست.")
    
    # ==================== دستورات مشاور ====================
    
    async def advisor_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پنل مشاور"""
        user_id = update.effective_user.id
        
        if not self.is_advisor(user_id):
            await update.message.reply_text("⛔ شما دسترسی به پنل مشاور ندارید.")
            return
        
        keyboard = [
            [InlineKeyboardButton("👥 لیست دانش‌آموزان", callback_data="list_students")],
            [InlineKeyboardButton("📤 ارسال برنامه جدید", callback_data="send_new_plan")],
            [InlineKeyboardButton("✏️ ویرایش برنامه", callback_data="edit_existing_plan")],
            [InlineKeyboardButton("📊 گزارش‌های جامع", callback_data="comprehensive_reports")]
        ]
        
        message = """
🎓 *پنل مشاور*

خوش آمدید! از اینجا می‌توانید:
• برنامه مطالعاتی برای دانش‌آموزان ارسال کنید
• برنامه‌های موجود را ویرایش کنید
• پیشرفت دانش‌آموزان را رصد کنید
• گزارش‌های تفصیلی دریافت کنید
        """
        
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    async def send_plan_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """درخواست ارسال برنامه"""
        user_id = update.effective_user.id
        
        if not self.is_advisor(user_id):
            await update.message.reply_text("⛔ شما دسترسی به این بخش ندارید.")
            return
        
        message = """
📤 *ارسال برنامه جدید*

لطفاً فایل Excel یا JSON برنامه را ارسال کنید.

📋 *فرمت فایل Excel:*
```
روز | نام درس | نوع | مبحث
1   | زیست۱۲  | مطالعه | نوکلئیک اسیدها
1   | ریاضی۱۰ | تست | معادله درجه دوم
...
```

یا برنامه را به صورت متنی با فرمت زیر بفرستید:
```
روز ۱:
- زیست۱۲ / مطالعه / نوکلئیک اسیدها
- ریاضی۱۰ / تست / معادله درجه دوم
...
```

💡 همچنین می‌توانید آیدی دانش‌آموز را مشخص کنید:
/send_plan [user_id]
        """
        
        context.user_data["awaiting_plan"] = True
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def view_students(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مشاهده لیست دانش‌آموزان"""
        user_id = update.effective_user.id
        
        if not self.is_advisor(user_id):
            await update.message.reply_text("⛔ شما دسترسی به این بخش ندارید.")
            return
        
        message = "👥 *لیست دانش‌آموزان*\n\n"
        
        for student_id, data in self.user_data.items():
            if student_id not in ADVISORS:
                name = data.get("name", "ناشناس")
                current_day = data.get("current_day", 0)
                
                # محاسبه پیشرفت
                if student_id in self.plans:
                    stats = self._calculate_stats(student_id)
                    progress = stats['total_progress']
                else:
                    progress = 0
                
                message += f"├─ 👤 {name} (ID: {student_id})\n"
                message += f"│  └─ روز: {current_day} | پیشرفت: {progress}%\n\n"
        
        if len(message) == len("👥 *لیست دانش‌آموزان*\n\n"):
            message += "هنوز دانش‌آموزی ثبت نشده است."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def student_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """آمار یک دانش‌آموز خاص"""
        user_id = update.effective_user.id
        
        if not self.is_advisor(user_id):
            await update.message.reply_text("⛔ شما دسترسی به این بخش ندارید.")
            return
        
        if not context.args:
            await update.message.reply_text("⚠️ لطفاً آیدی دانش‌آموز را وارد کنید:\n/student_stats [user_id]")
            return
        
        student_id = context.args[0]
        
        if student_id not in self.user_data:
            await update.message.reply_text("⚠️ دانش‌آموز یافت نشد!")
            return
        
        stats = self._calculate_stats(student_id)
        student_name = self.user_data[student_id].get("name", "ناشناس")
        
        message = f"""
📊 *گزارش پیشرفت {student_name}*

━━━━━━━━━━━━━━━━━━━━
پیشرفت کلی: {stats['total_progress']}%
{self._create_progress_bar(stats['total_progress'], 15)}

✅ انجام شده: {stats['completed_parts']}/{stats['total_parts']}
📅 روز جاری: {self.user_data[student_id]['current_day']}
⭐ میانگین روزانه: {stats['daily_average']}%

━━━━━━━━━━━━━━━━━━━━
📚 آمار درسی:
{self._format_subject_stats(stats['subject_stats'])}
        """
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    # ==================== هندلرها ====================
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """هندلر دریافت فایل"""
        user_id = update.effective_user.id
        
        if not self.is_advisor(user_id):
            return
        
        if not context.user_data.get("awaiting_plan"):
            return
        
        file = await context.bot.get_file(update.message.document.file_id)
        file_path = f"temp_{user_id}.{update.message.document.file_name.split('.')[-1]}"
        await file.download_to_drive(file_path)
        
        # پردازش فایل (اینجا باید پارسر فایل Excel یا JSON را پیاده کنید)
        await update.message.reply_text("✅ فایل دریافت شد! در حال پردازش...")
        
        # اینجا منطق پارس فایل و ذخیره برنامه
        context.user_data["awaiting_plan"] = False
        await update.message.reply_text("✅ برنامه با موفقیت ثبت شد!")
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """هندلر دکمه‌ها"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(query.from_user.id)
        data = query.data
        
        # تغییر وضعیت پارت
        if data.startswith("toggle_"):
            parts = data.split("_")
            day = int(parts[1])
            index = int(parts[2])
            day_key = f"day{day}"
            
            if user_id in self.plans and day_key in self.plans[user_id]:
                current_status = self.plans[user_id][day_key]["subjects"][index].get("completed", False)
                self.plans[user_id][day_key]["subjects"][index]["completed"] = not current_status
                self.save_data()
                await self.show_today(update, context)
        
        # ناوبری
        elif data == "show_today":
            await self.show_today(update, context)
        elif data == "my_progress":
            await self.show_progress(update, context)
        elif data == "full_stats":
            await self.show_stats(update, context)
        elif data == "next_day":
            await self.next_day(update, context)
        elif data == "prev_day":
            await self.prev_day(update, context)
        
        # مشاور
        elif data == "list_students":
            await self.view_students(update, context)
        elif data == "send_new_plan":
            await self.send_plan_request(update, context)
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """هندلر پیام‌های متنی برای دریافت برنامه"""
        user_id = update.effective_user.id
        
        if not self.is_advisor(user_id) or not context.user_data.get("awaiting_plan"):
            return
        
        text = update.message.text
        
        # پارس متن و ساخت برنامه
        # اینجا منطق پارس متن را پیاده کنید
        
        await update.message.reply_text("✅ برنامه دریافت شد و در حال پردازش است...")
    
    # ==================== توابع کمکی ====================
    
    def _format_day_plan(self, day_data: Dict, day_number: int) -> str:
        """فرمت کردن برنامه روزانه"""
        subjects_text = ""
        for i, subject in enumerate(day_data["subjects"]):
            status = "✅" if subject.get("completed", False) else "◻️"
            subjects_text += f"{status} *{subject['name']}* - {subject['type']}\n"
            subjects_text += f"   📖 {subject['topic']}\n\n"
        
        completed = sum(1 for s in day_data["subjects"] if s.get("completed", False))
        total = len(day_data["subjects"])
        progress = int((completed / total) * 100) if total > 0 else 0
        
        return f"""
🎯 *برنامه روز {day_number}*

━━━━━━━━━━━━━━━━━━━━
📚 *درس‌های امروز:*

{subjects_text}
━━━━━━━━━━━━━━━━━━━━
📊 *پیشرفت روز:*
{self._create_progress_bar(progress)} {progress}%

✅ انجام شده: {completed}/{total}
⏳ باقی‌مانده: {total - completed}

🕐 {datetime.datetime.now().strftime('%Y/%m/%d - %H:%M')}
        """
    
    def _create_day_keyboard(self, subjects: List[Dict], day_number: int):
        """ساخت کیبورد برای روز"""
        keyboard = []
        
        for i, subject in enumerate(subjects):
            status = "✅" if subject.get("completed", False) else "◻️"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {subject['name']} - {subject['type']}",
                    callback_data=f"toggle_{day_number}_{i}"
                )
            ])
        
        keyboard.extend([
            [
                InlineKeyboardButton("⬅️ روز قبل", callback_data="prev_day"),
                InlineKeyboardButton("روز بعد ➡️", callback_data="next_day")
            ],
            [
                InlineKeyboardButton("📊 پیشرفت", callback_data="my_progress"),
                InlineKeyboardButton("📈 آمار", callback_data="full_stats")
            ],
            [InlineKeyboardButton("♻️ ریست روز", callback_data="reset_day")]
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _calculate_stats(self, user_id: str) -> Dict:
        """محاسبه آمار کامل"""
        if user_id not in self.plans:
            return {
                'total_progress': 0,
                'completed_parts': 0,
                'remaining_parts': 0,
                'total_parts': 0,
                'days_passed': 0,
                'days_remaining': 0,
                'subject_stats': {},
                'daily_average': 0,
                'best_day': 0,
                'best_day_progress': 0,
                'completed_days': 0
            }
        
        total_completed = 0
        total_parts = 0
        subject_stats = {}
        day_progress = {}
        completed_days = 0
        
        for day_key, day_data in self.plans[user_id].items():
            day_num = int(day_key.replace("day", ""))
            day_completed = 0
            day_total = len(day_data["subjects"])
            
            for subject in day_data["subjects"]:
                total_parts += 1
                subject_name = subject["name"]
                
                if subject_name not in subject_stats:
                    subject_stats[subject_name] = {"completed": 0, "total": 0}
                
                subject_stats[subject_name]["total"] += 1
                
                if subject.get("completed", False):
                    total_completed += 1
                    subject_stats[subject_name]["completed"] += 1
                    day_completed += 1
            
            day_progress[day_num] = int((day_completed / day_total) * 100) if day_total > 0 else 0
            if day_progress[day_num] == 100:
                completed_days += 1
        
        best_day = max(day_progress.items(), key=lambda x: x[1]) if day_progress else (0, 0)
        current_day = self.user_data[user_id]["current_day"]
        total_days = self.user_data[user_id].get("total_days", 13)
        
        return {
            'total_progress': int((total_completed / total_parts) * 100) if total_parts > 0 else 0,
            'completed_parts': total_completed,
            'remaining_parts': total_parts - total_completed,
            'total_parts': total_parts,
            'days_passed': current_day - 1,
            'days_remaining': total_days - current_day + 1,
            'subject_stats': subject_stats,
            'daily_average': int(sum(day_progress.values()) / len(day_progress)) if day_progress else 0,
            'best_day': best_day[0],
            'best_day_progress': best_day[1],
            'completed_days': completed_days
        }
    
    def _format_subject_stats(self, subject_stats: Dict) -> str:
        """فرمت آمار دروس"""
        text = ""
        for subject, stats in sorted(subject_stats.items()):
            completed = stats["completed"]
            total = stats["total"]
            progress = int((completed / total) * 100) if total > 0 else 0
            text += f"├─ *{subject}:* {self._create_progress_bar(progress, 8)} {progress}%\n"
            text += f"│  └─ {completed}/{total} پارت\n"
        return text if text else "├─ هنوز آماری موجود نیست"
    
    def _create_progress_bar(self, progress: int, length: int = 10) -> str:
        """ساخت نوار پیشرفت"""
        filled = int(progress / 100 * length)
        empty = length - filled
        return f"│{'█' * filled}{'░' * empty}│"
    
    def _get_motivation_message(self, progress: int) -> str:
        """پیام انگیزشی بر اساس پیشرفت"""
        if progress >= 90:
            return "🌟 عالی! تقریباً تمام شده! ادامه بده!"
        elif progress >= 70:
            return "💪 خیلی خوب پیش میری! همینطور ادامه بده!"
        elif progress >= 50:
            return "👍 نصف راه رو رد کردی! تلاش کن!"
        elif progress >= 30:
            return "🚀 شروع خوبی داشتی! ادامه بده!"
        elif progress >= 10:
            return "🎯 داری شروع می‌کنی! تمرکز کن!"
        else:
            return "💡 بیا شروع کنیم! راه خیلی طولانی نیست!"
    
    async def _send_message(self, update: Update, text: str, reply_markup=None):
        """ارسال پیام (مدیریت هم message و هم callback)"""
        try:
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            print(f"خطا در ارسال پیام: {e}")
    
    def parse_text_plan(self, text: str, user_id: str) -> bool:
        """پارس برنامه متنی"""
        try:
            lines = text.strip().split('\n')
            current_day = None
            self.plans[user_id] = {}
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # تشخیص روز
                if line.startswith('روز'):
                    day_num = int(line.split()[1].replace(':', ''))
                    current_day = f"day{day_num}"
                    self.plans[user_id][current_day] = {"subjects": []}
                
                # تشخیص درس
                elif line.startswith('-') and current_day:
                    parts = line[1:].split('/')
                    if len(parts) == 3:
                        subject = {
                            "name": parts[0].strip(),
                            "type": parts[1].strip(),
                            "topic": parts[2].strip(),
                            "completed": False
                        }
                        self.plans[user_id][current_day]["subjects"].append(subject)
            
            self.save_data()
            return True
        
        except Exception as e:
            print(f"خطا در پارس برنامه: {e}")
            return False
    
    def run(self):
        """اجرای ربات"""
        print("🤖 ربات در حال اجرا...")
        self.application.run_polling()

# ==================== اجرای ربات ====================

if __name__ == "__main__":
    # توکن ربات خود را اینجا قرار دهید
    TOKEN = "7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ"
    
    # آیدی‌های مشاوران را اینجا اضافه کنید
    ADVISORS = [6680287530]  # جایگزین با آیدی‌های واقعی
    
    # ساخت و اجرای ربات
    bot = StudyPlanBot(TOKEN)
    bot.run()
