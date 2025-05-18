import os
import asyncio
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Загружаем .env из текущей директории, если файл есть
if os.path.exists(".env"):
    load_dotenv()
else:
    print("Warning: .env file not found, переменные окружения будут браться из системных настроек")

# Получаем токен из переменных окружения
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    print("Ошибка: токен бота не найден. Проверьте переменную окружения BOT_TOKEN.")
    exit()

# Категории объявлений
CATEGORIES = ['🏠 Аренда', '💼 Работа', '🔧 Услуги', '🛒 Куплю/Продам', '🎁 Отдам даром']

# FSM состояния
class AdStates(StatesGroup):
    category = State()
    title = State()
    description = State()
    price = State()
    photo = State()
    contact = State()

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе SQLite (будет создана в текущей папке)
conn = sqlite3.connect("ads.db")
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    title TEXT,
    description TEXT,
    price TEXT,
    photo TEXT,
    contact TEXT,
    created_at TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS ad_limits (
    user_id INTEGER,
    date TEXT,
    count INTEGER,
    PRIMARY KEY(user_id, date)
)''')

conn.commit()

# Клавиатуры
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить объявление")],
        [KeyboardButton(text="🔍 Посмотреть объявления")]
    ],
    resize_keyboard=True
)

category_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")] for cat in CATEGORIES]
)

@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer("Привет! Я бот для объявлений по Пльзеню и окрестностям.\n\nВыберите действие:", reply_markup=main_kb)

@dp.message(F.text == "➕ Добавить объявление")
async def add_ad(message: Message, state: FSMContext):
    user_id = message.from_user.id
    date_str = datetime.now().date().isoformat()
    cursor.execute("SELECT count FROM ad_limits WHERE user_id = ? AND date = ?", (user_id, date_str))
    row = cursor.fetchone()
    if row and row[0] >= 5:
        await message.answer("Вы уже добавили 5 объявлений сегодня. Попробуйте снова завтра.")
        return
    await message.answer("Выберите категорию:", reply_markup=category_kb)
    await state.set_state(AdStates.category)

@dp.callback_query(F.data.startswith("cat_"))
async def category_chosen(callback: CallbackQuery, state: FSMContext):
    category = callback.data[4:]
    await state.update_data(category=category)
    await callback.message.answer("Введите заголовок объявления:")
    await state.set_state(AdStates.title)
    await callback.answer()

@dp.message(AdStates.title)
async def ad_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Теперь введите описание:")
    await state.set_state(AdStates.description)

@dp.message(AdStates.description)
async def ad_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Укажите цену (в CZK):")
    await state.set_state(AdStates.price)

@dp.message(AdStates.price)
async def ad_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text)
    await message.answer("Пришлите фото (одну картинку) или пропустите, написав 'нет':")
    await state.set_state(AdStates.photo)

@dp.message(AdStates.photo)
async def ad_photo(message: Message, state: FSMContext):
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.text and message.text.lower() == "нет":
        file_id = None
    else:
        await message.answer("Пожалуйста, отправьте фото или напишите 'нет'.")
        return
    await state.update_data(photo=file_id)
    await message.answer("Укажите контактную информацию (телефон, Telegram и т.п.):")
    await state.set_state(AdStates.contact)

@dp.message(AdStates.contact)
async def ad_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    date_str = datetime.now().date().isoformat()

    cursor.execute("SELECT count FROM ad_limits WHERE user_id = ? AND date = ?", (user_id, date_str))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE ad_limits SET count = count + 1 WHERE user_id = ? AND date = ?", (user_id, date_str))
    else:
        cursor.execute("INSERT INTO ad_limits (user_id, date, count) VALUES (?, ?, 1)", (user_id, date_str))

    cursor.execute(
        "INSERT INTO ads (user_id, category, title, description, price, photo, contact, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, data['category'], data['title'], data['description'], data['price'], data['photo'], message.text, datetime.now().isoformat())
    )
    conn.commit()

    await message.answer("Объявление успешно добавлено! Спасибо!", reply_markup=main_kb)
    await state.clear()

@dp.message(F.text == "🔍 Посмотреть объявления")
async def view_ads(message: Message):
    cursor.execute("SELECT category, title, description, price, photo, contact, created_at FROM ads ORDER BY id DESC LIMIT 5")
    ads = cursor.fetchall()
    if not ads:
        await message.answer("Объявлений пока нет.")
        return
    for ad in ads:
        text = (f"<b>{ad[1]}</b>\nКатегория: {ad[0]}\nЦена: {ad[3]} CZK\n"
                f"Описание: {ad[2]}\nКонтакт: {ad[5]}\nДобавлено: {ad[6][:10]}")
        if ad[4]:
            await message.answer_photo(photo=ad[4], caption=text)
        else:
            await message.answer(text)

async def main():
    print("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
