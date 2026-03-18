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

    default_start = (
        "<b>BOT AKTIV ISHLAMOQDA ✅</b>\n\n"
        "⁉️ BOT ORQALI QANDAY QILIB OVOZ BERISH VIDEODA KO'RSATILGAN.\n\n"
        "🎉 To'g'ri ovoz berganlarga pul shu zahoti o'tkazilmoqda!\n\n"
        "🥳 Aziz {name}! 🗳 Ovoz berish tugmasini bosib, ovoz bering!"
    )

    sets = [
        ('vote_price', '5000'), 
        ('ref_price', '1000'), 
        ('min_withdraw', '15000'), 
        ('vote_link', 'https://t.me/ochiqbudjetbot?start=053465392013'),
        ('payment_channel', 'O\'rnatilmagan'),
        ('start_text', default_start),
        ('video_file_id', '') # Bu bo'sh bo'lsa VIDEO_URL ishlatiladi
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

def mask_card(card_number):
    card = re.sub(r'\D', '', card_number)
    if len(card) >= 16:
        return f"{card[:4]} **** **** {card[-4:]}"
    return card

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
    withdraw_method = State()
    withdraw_details = State()
    withdraw_amount = State()

class AdminState(StatesGroup):
    broadcast_text = State()
    change_vote_link = State()
    add_ch_title = State()
    add_ch_url = State()
    add_ch_id = State()

# --- KLAVIATURALAR ---
def main_menu(user_id):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🗳 Ovoz berish")
    kb.row(types.KeyboardButton(text="💰 Hisobim"), types.KeyboardButton(text="💸 Pul yechib olish"))
    kb.row(types.KeyboardButton(text="🔗 Referal"), types.KeyboardButton(text="🏆 Yutuqlar"))
    if user_id == ADMIN_ID: kb.row(types.KeyboardButton(text="⚙️ Admin Panel"))
    return kb.as_markup(resize_keyboard=True)

def admin_panel_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="✉️ Xabar yuborish"), types.KeyboardButton(text="🔗 Ovoz linkini sozlash"))
    kb.row(types.KeyboardButton(text="📄 Ulangan kanallar"), types.KeyboardButton(text="📢 Kanal ulash"))
    kb.row(types.KeyboardButton(text="📊 Statistika"), types.KeyboardButton(text="🕒 Ovozlar tarixi"))
    kb.row(types.KeyboardButton(text="🏠 Orqaga"))
    return kb.as_markup(resize_keyboard=True)

# --- ADMIN VIDEO SOZLAMASI ---
@dp.message(F.video, F.from_user.id == ADMIN_ID)
async def save_video_id(message: types.Message):
    """Admin video yuborganda uning ID sini bazaga saqlaydi (URL dan ustun turadi)"""
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
        ref_id = None
        parts = message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            p_ref = int(parts[1])
            if p_ref != u_id: 
                ref_id = p_ref
                ref_price = int(get_config('ref_price'))
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (ref_price, ref_id))
                try: await bot.send_message(ref_id, f"🎉 <b>Yangi referal qo'shildi!</b>\nSizga {ref_price} so'm bonus berildi.", parse_mode="HTML")
                except: pass
        cursor.execute("INSERT INTO users (user_id, username, name, referrer_id) VALUES (?, ?, ?, ?)", (u_id, username, name, ref_id))
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
            # Agar bazada file_id bo'lsa (admin yuborgan bo'lsa)
            await message.answer_video(video=vid_id, caption=start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
        else:
            # Agar file_id bo'lmasa, Google Drive URL ishlatiladi
            video_file = URLInputFile(VIDEO_URL, filename="instruction.mp4")
            await message.answer_video(video=video_file, caption=start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Video yuborishda xato: {e}")
        # Video yuborishda xato bo'lsa, xabarning o'zini yuboradi
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
    uid, pr = int(uid), int(get_config('vote_price'))
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    
    cursor.execute("UPDATE users SET balance = balance + ?, votes = votes + 1 WHERE user_id = ?", (pr, uid))
    cursor.execute("INSERT OR IGNORE INTO used_phones (phone) VALUES (?)", (ph,))
    cursor.execute("INSERT INTO vote_history (user_id, phone, time) VALUES (?, ?, ?)", (uid, ph, now_str))
    conn.commit()
    
    try: await bot.send_message(uid, f"✅ Ovozingiz tasdiqlandi! +{pr} so'm balansingizga qo'shildi.")
    except: pass
    
    cursor.execute("SELECT name FROM users WHERE user_id=?", (uid,))
    user_name = cursor.fetchone()[0]
    await send_log(f"✅ <b>Ovoz Tasdiqlandi!</b>\n👤 Foydalanuvchi: {user_name}\n📞 Raqam: {ph}\n💰 To'lov: {pr} so'm\n⏰ Vaqt: {now_str}")
    
    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ <b>TASDIQLANDI</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_vote(call: types.CallbackQuery):
    uid = int(call.data.split("_")[1])
    try: await bot.send_message(uid, "❌ Yuborgan skrinshotingiz admin tomonidan rad etildi.")
    except: pass
    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ <b>RAD ETILDI</b>", parse_mode="HTML")

# --- PUL YECHISH ---
@dp.message(F.text == "💰 Hisobim")
async def balance_handler(message: types.Message):
    cursor.execute("SELECT balance, votes, withdrawn FROM users WHERE user_id = ?", (message.from_user.id,))
    row = cursor.fetchone()
    await message.answer(f"👤 {html.escape(message.from_user.full_name)}\n💰 Balans: {row[0]} so'm\n🗳 Ovozlar: {row[1]} ta\n💸 Yechilgan: {row[2]} so'm", parse_mode="HTML")

@dp.message(F.text == "💸 Pul yechib olish")
async def withdraw_handler(message: types.Message, state: FSMContext):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,))
    balance = cursor.fetchone()[0]
    min_w = int(get_config('min_withdraw'))
    if balance < min_w: return await message.answer(f"❌ Kamida {min_w} so'm bo'lishi kerak.")
    kb = ReplyKeyboardBuilder().button(text="💳 Karta raqam").button(text="📱 Paynet (Telefon)").button(text="🏠 Orqaga")
    await message.answer("To'lov usulini tanlang:", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(UserStates.withdraw_method)

@dp.message(UserStates.withdraw_method)
async def withdraw_step_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    await state.update_data(method=message.text)
    await message.answer("Rekvizitni kiriting:", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(UserStates.withdraw_details)

@dp.message(UserStates.withdraw_details)
async def withdraw_step_3(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    await state.update_data(details=message.text)
    await message.answer("Yechmoqchi bo'lgan summani kiriting:")
    await state.set_state(UserStates.withdraw_amount)

@dp.message(UserStates.withdraw_amount)
async def withdraw_step_4(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("Faqat raqam kiriting.")
    amount, uid = int(message.text), message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (uid,))
    if amount > cursor.fetchone()[0]: return await message.answer("❌ Balansda mablag' yetarli emas.")
    
    data = await state.get_data()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, uid))
    conn.commit()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ To'landi", callback_data=f"paid_{uid}_{amount}_{data['details']}")
    kb.button(text="❌ Rad etish", callback_data=f"wrej_{uid}_{amount}")
    
    await bot.send_message(ADMIN_ID, f"💸 <b>Yangi yechish so'rovi!</b>\n👤 {message.from_user.full_name}\n💰 Summa: {amount}\n🛠 Usul: {data['method']}\n📋 Rekvizit: {data['details']}", 
                           reply_markup=kb.adjust(1).as_markup(), parse_mode="HTML")
    await message.answer("✅ So'rovingiz yuborildi.", reply_markup=main_menu(uid))
    await state.clear()

# --- ADMIN TASDIQLASH (PUL) ---
@dp.callback_query(F.data.startswith("paid_"))
async def process_payment_confirm(call: types.CallbackQuery):
    parts = call.data.split("_")
    uid, amount, details = int(parts[1]), parts[2], parts[3]
    cursor.execute("UPDATE users SET withdrawn = withdrawn + ? WHERE user_id = ?", (int(amount), uid))
    conn.commit()
    
    cursor.execute("SELECT name FROM users WHERE user_id = ?", (uid,))
    name = cursor.fetchone()[0]
    masked = mask_card(details)
    
    log_text = f"✅ <b>TO'LOV AMALGA OSHIRILDI</b>\n\n👤 Foydalanuvchi: {html.escape(name)}\n💰 Summa: {amount} so'm\n💳 Rekvizit: <code>{masked}</code>\n🕒 Holat: Muvaffaqiyatli ✅"
    await send_log(log_text)
    
    try: await bot.send_message(uid, f"✅ To'lovingiz amalga oshirildi! {amount} so'm yuborildi.")
    except: pass
    await call.message.edit_text(call.message.text + "\n\n✅ <b>TO'LOV TASDIQLANDI</b>")

@dp.callback_query(F.data.startswith("wrej_"))
async def process_payment_reject(call: types.CallbackQuery):
    uid, amount = int(call.data.split("_")[1]), int(call.data.split("_")[2])
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, uid))
    conn.commit()
    try: await bot.send_message(uid, "❌ Pul yechish so'rovingiz rad etildi.")
    except: pass
    await call.message.edit_text(call.message.text + "\n\n❌ <b>RAD ETILDI</b>")

# --- ADMIN PANEL FUNKSIYALARI ---
@dp.message(F.text == "⚙️ Admin Panel")
async def admin_panel_handler(message: types.Message):
    if message.from_user.id == ADMIN_ID: await message.answer("Boshqaruv paneli:", reply_markup=admin_panel_kb())

@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*), SUM(balance), SUM(withdrawn), SUM(votes) FROM users")
    s = cursor.fetchone()
    await message.answer(f"📊 <b>Bot Statistikasi:</b>\n\n👤 Jami foydalanuvchilar: {s[0]}\n🗳 Jami ovozlar: {s[3] or 0}\n💸 To'langan: {s[2] or 0} so'm", parse_mode="HTML")

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
            # copy_message - oddiy matn, forward, rasm, video va hokazolarni asl holidek nusxalab yuboradi.
            await bot.copy_message(chat_id=u_id, from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05) # Telegram spam chekloviga tushmaslik uchun
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

@dp.message(F.text == "🔗 Referal")
async def referal_handler(message: types.Message):
    me = await bot.get_me()
    await message.answer(f"🔗 <b>Sizning referal havolangiz:</b>\n\n<code>https://t.me/{me.username}?start={message.from_user.id}</code>\n\nBonus: {get_config('ref_price')} so'm", parse_mode="HTML")

@dp.message(F.text == "🏆 Yutuqlar")
async def leaderboard_handler(message: types.Message):
    cursor.execute("SELECT name, votes FROM users ORDER BY votes DESC LIMIT 10")
    text = "🏆 <b>Eng ko'p ovoz berganlar:</b>\n\n"
    for i, r in enumerate(cursor.fetchall(), 1): text += f"{i}. {html.escape(r[0])} - {r[1]} ta\n"
    await message.answer(text, parse_mode="HTML")

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
