import asyncio
import logging
import sqlite3
import html
import os
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, URLInputFile
from aiogram.exceptions import TelegramConflictError

# --- KONFIGURATSIYA ---
API_TOKEN = "8674788956:AAH3-YFi8yNlpJwqjQsTQaqYN-MrxDNj-xI"
ADMIN_ID = 7957774091
LOG_GROUP_ID = -1003718123385 

# Google Drive videoni to'g'ridan-to'g'ri yuklab olish havolasi (uc?export=download)
VIDEO_URL = "https://drive.google.com/uc?export=download&id=1xIr9s1K6Bq3H5Gpt6P5bG8kQb7lrMuF3"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- BAZA BILAN ISHLASH ---
conn = sqlite3.connect("open_budget_pro.db", check_same_thread=False)
cursor = conn.cursor()

def db_setup():
    # Eski bazani buzmaslik uchun balance va boshqa ustunlarni qoldiramiz, lekin ishlatmaymiz
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, phone TEXT,
        balance INTEGER DEFAULT 0, votes INTEGER DEFAULT 0,
        withdrawn INTEGER DEFAULT 0, referrer_id INTEGER, ref_paid INTEGER DEFAULT 0)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, title TEXT, url TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS used_phones (phone TEXT PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS vote_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, phone TEXT, time TEXT)''')

    # --- FAQAT 1 TA KANAL QOLDIRISH ---
    cursor.execute("DELETE FROM channels")  # eski kanallarni o‘chiramiz
    cursor.execute("""
        INSERT INTO channels (channel_id, title, url)
        VALUES ('-1003718123385', 'Open Budget Isbot', 'https://t.me/openbudgetIsbo')
    """)

    default_start = (
        "<b>BOT AKTIV ISHLAMOQDA ✅</b>\n\n"
        "⁉️ BOT ORQALI QANDAY QILIB OVOZ BERISH VIDEODA KO'RSATILGAN.\n\n"
        "🥳 Aziz {name}! 🗳 Ovoz berish tugmasini bosib, ovoz bering!"
    )

    sets = [
        ('vote_link', 'https://t.me/ochiqbudjetbot?start=053465392013'),
        ('start_text', default_start),
        ('video_file_id', '')
    ]

    for k, v in sets:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()

db_setup()

# --- YORDAMCHI FUNKSIYALAR ---
def get_config(key):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = cursor.fetchone()
    return res[0] if res else ""

def set_config(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()

async def check_sub(user_id):
    cursor.execute("SELECT channel_id FROM channels")
    rows = cursor.fetchall()
    for (ch_id,) in rows:
        try:
            m = await bot.get_chat_member(ch_id, user_id)
            if m.status in ['left', 'kicked', 'member_not_found']: return False
        except: return False
    return True

async def send_log(text):
    try:
        await bot.send_message(LOG_GROUP_ID, text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Guruhga yozishda xato: {e}")

# --- FSM STATES ---
class UserStates(StatesGroup):
    get_phone_for_vote = State()
    waiting_for_screenshot = State()

class AdminState(StatesGroup):
    broadcast_text = State()
    change_vote_link = State()

# --- KLAVIATURALAR ---
def main_menu(user_id):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🗳 Ovoz berish")
    kb.button(text="🏆 Yutuqlar")
    if user_id == ADMIN_ID: kb.row(types.KeyboardButton(text="⚙️ Admin Panel"))
    return kb.as_markup(resize_keyboard=True)

def admin_panel_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="✉️ Xabar yuborish"), types.KeyboardButton(text="🔗 Ovoz linkini sozlash"))
    kb.row(types.KeyboardButton(text="📊 Statistika"), types.KeyboardButton(text="🕒 Ovozlar tarixi"))
    kb.row(types.KeyboardButton(text="🏠 Orqaga"))
    return kb.as_markup(resize_keyboard=True)

# --- ADMIN VIDEO SOZLAMASI ---
@dp.message(F.video, F.from_user.id == ADMIN_ID)
async def save_video_id(message: types.Message):
    file_id = message.video.file_id
    set_config('video_file_id', file_id)
    await message.answer(f"✅ <b>Video muvaffaqiyatli saqlandi!</b>\nEndi URL emas, ushbu video ko'rinadi.\n\nID: <code>{file_id}</code>", parse_mode="HTML")

# --- ASOSIY HANDLERLAR ---
@dp.message(F.text == "🏠 Orqaga")
async def back_main_handler(message: types.Message, state: FSMContext):
    await state.clear()
    u_id = message.from_user.id
    start_msg = get_config('start_text').replace("{name}", html.escape(message.from_user.full_name))
    await message.answer(start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    u_id = message.from_user.id
    name = message.from_user.full_name
    username = message.from_user.username or "yo'q"
    
    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (u_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, username, name) VALUES (?, ?, ?)", (u_id, username, name))
        conn.commit()

    if not await check_sub(u_id):
        kb = InlineKeyboardBuilder()
        cursor.execute("SELECT title, url FROM channels")
        for t, u in cursor.fetchall(): kb.button(text=t, url=u)
        kb.button(text="✅ Tasdiqlash", callback_data="recheck")
        return await message.answer("❌ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:</b>", reply_markup=kb.adjust(1).as_markup(), parse_mode="HTML")

    start_msg = get_config('start_text').replace("{name}", html.escape(name))
    vid_id = get_config('video_file_id')
    
    try:
        if vid_id and vid_id.strip():
            await message.answer_video(video=vid_id, caption=start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
        else:
            video_file = URLInputFile(VIDEO_URL, filename="instruction.mp4")
            await message.answer_video(video=video_file, caption=start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Video yuborishda xato: {e}")
        await message.answer(start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")

@dp.callback_query(F.data == "recheck")
async def recheck_sub(call: types.CallbackQuery, state: FSMContext):
    if await check_sub(call.from_user.id):
        await call.message.delete()
        await cmd_start(call.message, state)
    else: await call.answer("❌ Hali obuna bo'lmagansiz!", show_alert=True)

# --- OVOZ BERISH JARYONI ---
@dp.message(F.text == "🗳 Ovoz berish")
async def vote_step_1(message: types.Message, state: FSMContext):
    await message.answer("📞 Ovoz berish uchun telefon raqamingizni kiriting\n(Masalan: 901234567):",
                         reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(UserStates.get_phone_for_vote)

@dp.message(UserStates.get_phone_for_vote)
async def vote_step_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    phone = message.text.strip().replace("+", "").replace(" ", "")
    if phone.isdigit() and len(phone) == 9: phone = "998" + phone
    if not (phone.isdigit() and len(phone) == 12):
        return await message.answer("❌ Noto'g'ri raqam formati.")

    cursor.execute("SELECT phone FROM used_phones WHERE phone=?", (phone,))
    if cursor.fetchone(): return await message.answer("❌ Bu raqam ishlatilgan.")

    await state.update_data(vote_phone=phone)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Ovoz berish (Saytga o'tish)", url=get_config('vote_link'))
    kb.button(text="✅ Ovoz berdim", callback_data="voted_done")
    await message.answer(f"✅ Raqam qabul qilindi: {phone}\nOvoz berib skrinshot yuboring.", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data == "voted_done")
async def vote_step_3(call: types.CallbackQuery, state: FSMContext):
    await call.message.delete()
    await call.message.answer("📸 Skrinshotni yuboring:", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(UserStates.waiting_for_screenshot)

@dp.message(UserStates.waiting_for_screenshot, F.photo)
async def vote_step_4(message: types.Message, state: FSMContext):
    data = await state.get_data()
    phone, user_id = data.get('vote_phone'), message.from_user.id
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"approve_{user_id}_{phone}")
    kb.button(text="❌ Rad etish", callback_data=f"reject_{user_id}")
    
    admin_msg = f"🗳 <b>Yangi ovoz!</b>\n👤 {html.escape(message.from_user.full_name)}\n🆔 {user_id}\n📞 {phone}\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, parse_mode="HTML", reply_markup=kb.adjust(2).as_markup())
    
    group_msg = f"🗳 <b>Yangi ovoz so'rovi!</b>\n👤 Foydalanuvchi: {html.escape(message.from_user.full_name)}\n📞 Raqam: {phone}\n⏳ Admin tasdiqlashi kutilmoqda..."
    await send_log(group_msg)

    await message.answer("✅ Qabul qilindi, admin tasdiqlashini kuting.", reply_markup=main_menu(user_id))
    await state.clear()

# --- ADMIN TASDIQLASH (OVOZ) ---
@dp.callback_query(F.data.startswith("approve_"))
async def approve_vote(call: types.CallbackQuery):
    _, uid, ph = call.data.split("_")
    uid = int(uid)
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    
    cursor.execute("UPDATE users SET votes = votes + 1 WHERE user_id = ?", (uid,))
    cursor.execute("INSERT OR IGNORE INTO used_phones (phone) VALUES (?)", (ph,))
    cursor.execute("INSERT INTO vote_history (user_id, phone, time) VALUES (?, ?, ?)", (uid, ph, now_str))
    conn.commit()
    
    # Foydalanuvchiga xabar
    try: await bot.send_message(uid, "✅ Ovozingiz muvaffaqiyatli tasdiqlandi! Rahmat.")
    except: pass
    
    # Guruhga hisobot
    cursor.execute("SELECT name FROM users WHERE user_id=?", (uid,))
    user_name = cursor.fetchone()[0]
    await send_log(f"✅ <b>Ovoz Tasdiqlandi!</b>\n👤 Foydalanuvchi: {user_name}\n📞 Raqam: {ph}\n⏰ Vaqt: {now_str}")
    
    # Admindagi xabarni o'zgartirish
    caption = call.message.caption or ""
    await call.message.edit_caption(caption=caption + "\n\n✅ <b>TASDIQLANDI</b>", parse_mode="HTML", reply_markup=None)

@dp.callback_query(F.data.startswith("reject_"))
async def reject_vote(call: types.CallbackQuery):
    uid = int(call.data.split("_")[1])
    try: await bot.send_message(uid, "❌ Yuborgan skrinshotingiz admin tomonidan rad etildi.")
    except: pass
    
    caption = call.message.caption or ""
    await call.message.edit_caption(caption=caption + "\n\n❌ <b>RAD ETILDI</b>", parse_mode="HTML", reply_markup=None)

# --- QOLGAN MENYULAR ---
@dp.message(F.text == "🏆 Yutuqlar")
async def leaderboard_handler(message: types.Message):
    cursor.execute("SELECT name, votes FROM users ORDER BY votes DESC LIMIT 10")
    text = "🏆 <b>Eng ko'p ovoz berganlar:</b>\n\n"
    for i, r in enumerate(cursor.fetchall(), 1): text += f"{i}. {html.escape(r[0])} - {r[1]} ta\n"
    await message.answer(text, parse_mode="HTML")

# --- ADMIN PANEL FUNKSIYALARI ---
@dp.message(F.text == "⚙️ Admin Panel")
async def admin_panel_handler(message: types.Message):
    if message.from_user.id == ADMIN_ID: await message.answer("Boshqaruv paneli:", reply_markup=admin_panel_kb())

@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*), SUM(votes) FROM users")
    s = cursor.fetchone()
    await message.answer(f"📊 <b>Bot Statistikasi:</b>\n\n👤 Jami foydalanuvchilar: {s[0]}\n🗳 Jami ovozlar: {s[1] or 0}", parse_mode="HTML")

@dp.message(F.text == "🕒 Ovozlar tarixi")
async def vote_history_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute('''SELECT v.time, u.name, v.phone FROM vote_history v JOIN users u ON v.user_id = u.user_id ORDER BY v.id DESC LIMIT 20''')
    rows = cursor.fetchall()
    if not rows: return await message.answer("Hali ovozlar tarixi mavjud emas.")
    text = "🕒 <b>Oxirgi 20 ta tasdiqlangan ovoz:</b>\n\n"
    for t, n, p in rows: text += f"📅 {t}\n👤 {html.escape(n[:15])}... | 📞 {p}\n------------------------\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "✉️ Xabar yuborish")
async def broadcast_step_1(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Yubormoqchi bo'lgan xabaringizni yozing, rasm yuboring yoki forward qiling:", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
        await state.set_state(AdminState.broadcast_text)

@dp.message(AdminState.broadcast_text)
async def broadcast_step_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await admin_panel_handler(message)
    
    await message.answer("⏳ Xabarlar yuborilmoqda, iltimos kuting...")
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    count = 0
    for (u_id,) in users:
        try: 
            await bot.copy_message(chat_id=u_id, from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    
    await message.answer(f"✅ Xabar muvaffaqiyatli {count} ta foydalanuvchiga yuborildi.", reply_markup=admin_panel_kb())
    await state.clear()

@dp.message(F.text == "🔗 Ovoz linkini sozlash")
async def change_link_step_1(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        current = get_config('vote_link')
        await message.answer(f"🔗 <b>Hozirgi havola:</b>\n{current}\n\n<i>Yangi havolani yuboring:</i>", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True), parse_mode="HTML")
        await state.set_state(AdminState.change_vote_link)

@dp.message(AdminState.change_vote_link)
async def change_link_step_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await admin_panel_handler(message)
    
    new_link = message.text.strip()
    if not new_link.startswith("http"):
        return await message.answer("❌ Noto'g'ri format. Havola http yoki https bilan boshlanishi kerak.")
        
    set_config('vote_link', new_link)
    await message.answer("✅ Ovoz berish havolasi muvaffaqiyatli o'zgartirildi!", reply_markup=admin_panel_kb())
    await state.clear()

# --- MAIN ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(1)
    try: await dp.start_polling(bot, skip_updates=True)
    except TelegramConflictError: print("XATOLIK: Bot boshqa joyda ishlamoqda!")

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass
