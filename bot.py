import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import init_db, save_station, save_report
from osm import find_fuel_stations

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_СВОЙ_ТОКЕН_СЮДА")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Form(StatesGroup):
    waiting_location = State()

# Эмодзи для статусов, которые приходят из gdebenz (osm.py)
STATUS_EMOJI = {
    "yes": "⛽",
    "queue": "🟡",
    "low": "🟡",
    "no": "🔴",
    "unknown": "⚪",
}

# Расшифровка для кнопок отметки (ручной краудсорсинг)
MANUAL_STATUS = {
    "fuel": "⛽ Есть",
    "low": "🟡 Мало",
    "empty": "🔴 Нет",
}

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_location)
    await message.answer(
        "Привет! Я покажу АЗС рядом и статус топлива по данным gdebenz (народная карта).\n\n"
        "Отправь геолокацию (📎 → Локация) или напиши город."
    )

@dp.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await process_coords(message, lat, lon, state)

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_city(message: Message, state: FSMContext):
    city = message.text.strip().lower()
    cities = {
        "москва": (55.7558, 37.6173),
        "санкт-петербург": (59.9343, 30.3351),
        "казань": (55.7963, 49.1088),
        "екатеринбург": (56.8389, 60.6057),
        "новосибирск": (55.0084, 82.9357),
        "ростов-на-дону": (47.2357, 39.7015),
    }
    if city in cities:
        lat, lon = cities[city]
        await process_coords(message, lat, lon, state)
    else:
        await message.answer(
            "Пока знаю только: Москва, Санкт-Петербург, Казань, Екатеринбург, Новосибирск, Ростов-на-Дону.\n"
            "Или отправь геолокацию (📎 → Локация)."
        )

async def process_coords(message: Message, lat: float, lon: float, state: FSMContext):
    await message.answer("Ищу АЗС в радиусе 10 км и проверяю данные gdebenz...")
    stations = await find_fuel_stations(lat, lon, radius_km=10)

    if not stations:
        await message.answer("Рядом не нашёл АЗС. Попробуй другое место.")
        return

    await state.update_data(stations=stations)

    lines = ["Нашёл АЗС (радиус 10 км):\n"]
    for i, s in enumerate(stations, 1):
        # Берём статус из gdebenz (fuel_status), если нет — unknown
        status = s.get("fuel_status", "unknown")
        emoji = STATUS_EMOJI.get(status, "⚪")
        
        line = f"{emoji} {i}. {s['name']} — {s['distance_km']} км"
        if s.get("address"):
            line += f"\n   📍 {s['address']}"
        lines.append(line)

    lines.append("\n⚪ = нет данных, ⛽ = есть, 🟡 = мало/очередь, 🔴 = нет")
    lines.append("Данные: gdebenz (народная карта, могут быть неточными)")
    lines.append("\nНажми на АЗС, чтобы посмотреть детали или поставить свою отметку:")
    await message.answer("\n".join(lines), reply_markup=stations_keyboard(stations))

def stations_keyboard(stations):
    buttons = []
    for s in stations:
        status = s.get("fuel_status", "unknown")
        emoji = STATUS_EMOJI.get(status, "⚪")
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {s['name']} ({s['distance_km']} км)",
            callback_data=f"pick:{s['osm_id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data.startswith("pick:"))
async def pick_station(callback: CallbackQuery, state: FSMContext):
    osm_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    stations = data.get("stations", [])
    station = next((s for s in stations if s["osm_id"] == osm_id), None)

    if not station:
        await callback.answer("АЗС не найдена, попробуй заново /start")
        return

    # Сохраняем станцию в БД (чтобы потом можно было ставить отметки)
    station_id = await save_station(osm_id, station["name"], station["lat"], station["lon"])

    # Показываем статус из gdebenz
    status = station.get("fuel_status", "unknown")
    emoji = STATUS_EMOJI.get(status, "⚪")
    status_text = {
        "yes": "⛽ Есть топливо",
        "queue": "🟡 Очередь",
        "low": "🟡 Мало топлива",
        "no": "🔴 Нет топлива",
        "unknown": "⚪ Нет данных от gdebenz",
    }.get(status, "⚪ Нет данных")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⛽ Есть", callback_data=f"report:{station_id}:fuel"),
            InlineKeyboardButton(text="🟡 Мало", callback_data=f"report:{station_id}:low"),
            InlineKeyboardButton(text="🔴 Нет", callback_data=f"report:{station_id}:empty"),
        ]
    ])
    text = f"{station['name']} ({station['distance_km']} км)"
    if station.get("address"):
        text += f"\n📍 {station['address']}"
    text += f"\n\nДанные gdebenz: {status_text}"
    text += f"\n\nЕсли видишь другое — поставь свою отметку:"

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("report:"))
async def report_status(callback: CallbackQuery):
    _, station_id, status = callback.data.split(":")
    await save_report(int(station_id), status, callback.from_user.id)

    await callback.message.edit_text(
        f"Спасибо! Твоя отметка сохранена: {MANUAL_STATUS.get(status, status)}\n\n"
        f"Чтобы проверить другую АЗС — /start"
    )
    await callback.answer("Сохранено")

async def main():
    await init_db()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
