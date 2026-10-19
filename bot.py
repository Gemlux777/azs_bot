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

# Статусы из gdebenz
STATUS_EMOJI = {
    "yes": "⛽",
    "no": "🔴",
    "queue": "🟡",
    "low": "🟡",
    "unknown": "⚪",
}

STATUS_TEXT = {
    "yes": "⛽ Есть топливо",
    "no": "🔴 Нет топлива",
    "queue": "🟡 Очередь",
    "low": "🟡 Мало топлива",
    "unknown": "⚪ Нет данных",
}

MANUAL_STATUS = {
    "fuel": "⛽ Есть",
    "low": "🟡 Мало",
    "empty": "🔴 Нет",
}

CITIES = {
    "москва": (55.7558, 37.6173),
    "санкт-петербург": (59.9343, 30.3351),
    "казань": (55.7963, 49.1088),
    "екатеринбург": (56.8389, 60.6057),
    "новосибирск": (55.0084, 82.9357),
    "ростов-на-дону": (47.2357, 39.7015),
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
    try:
        lat = message.location.latitude
        lon = message.location.longitude
        await process_coords(message, lat, lon, state)
    except Exception as e:
        logging.exception(f"handle_location error: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз /start")

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_city(message: Message, state: FSMContext):
    try:
        city = message.text.strip().lower()
        if city in CITIES:
            lat, lon = CITIES[city]
            await process_coords(message, lat, lon, state)
        else:
            await message.answer(
                "Пока знаю только: Москва, Санкт-Петербург, Казань, Екатеринбург, Новосибирск, Ростов-на-Дону.\n"
                "Или отправь геолокацию (📎 → Локация)."
            )
    except Exception as e:
        logging.exception(f"handle_city error: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз /start")

async def process_coords(message: Message, lat: float, lon: float, state: FSMContext):
    try:
        await message.answer("Ищу АЗС в радиусе 10 км...")
        stations = await find_fuel_stations(lat, lon, radius_km=10)

        if not stations:
            await message.answer("Рядом не нашёл АЗС. Попробуй другое место.")
            return

        await state.update_data(stations=stations)

        lines = ["Нашёл АЗС (радиус 10 км):\n"]
        for i, s in enumerate(stations, 1):
            emoji = STATUS_EMOJI.get(s.get("fuel_status", "unknown"), "⚪")
            line = f"{emoji} {i}. {s['name']} — {s['distance_km']} км"
            if s.get("address"):
                line += f"\n   📍 {s['address']}"
            if s.get("fuels_now"):
                line += f"\n   ⛽ {s['fuels_now']}"
            if s.get("detail"):
                line += f"\n   ℹ️ {s['detail']}"
            lines.append(line)

        lines.append("\n⚪ = нет данных, ⛽ = есть, 🟡 = мало/очередь, 🔴 = нет")
        lines.append("Данные: gdebenz (народная карта)")

        # Разбиваем на части, если сообщение слишком длинное (лимит Telegram 4096)
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n\n…список обрезан"

        await message.answer(text, reply_markup=stations_keyboard(stations))
    except Exception as e:
        logging.exception(f"process_coords error: {e}")
        await message.answer("Ошибка при поиске АЗС. Попробуй ещё раз /start")

def stations_keyboard(stations):
    buttons = []
    for s in stations:
        emoji = STATUS_EMOJI.get(s.get("fuel_status", "unknown"), "⚪")
        name = s["name"][:40]  # обрезаем длинные названия для кнопки
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {name} ({s['distance_km']} км)",
            callback_data=f"pick:{s['osm_id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data.startswith("pick:"))
async def pick_station(callback: CallbackQuery, state: FSMContext):
    try:
        osm_id = callback.data.split(":", 1)[1]
        data = await state.get_data()
        stations = data.get("stations", [])
        station = next((s for s in stations if s["osm_id"] == osm_id), None)

        if not station:
            await callback.answer("АЗС не найдена, попробуй заново /start")
            return

        station_id = await save_station(osm_id, station["name"], station["lat"], station["lon"])

        status = station.get("fuel_status", "unknown")
        status_text = STATUS_TEXT.get(status, "⚪ Нет данных")

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
        text += f"\n\ngdebenz: {status_text}"
        if station.get("fuels_now"):
            text += f"\n⛽ {station['fuels_now']}"
        if station.get("detail"):
            text += f"\nℹ️ {station['detail']}"
        if station.get("confirmations"):
            text += f"\n👥 Подтверждений: {station['confirmations']}"
        text += "\n\nЕсли видишь другое — поставь свою отметку:"

        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        logging.exception(f"pick_station error: {e}")
        await callback.answer("Ошибка, попробуй ещё раз")

@dp.callback_query(F.data.startswith("report:"))
async def report_status(callback: CallbackQuery):
    try:
        _, station_id, status = callback.data.split(":")
        await save_report(int(station_id), status, callback.from_user.id)
        await callback.message.edit_text(
            f"Спасибо! Твоя отметка сохранена: {MANUAL_STATUS.get(status, status)}\n\n"
            f"Чтобы проверить другую АЗС — /start"
        )
        await callback.answer("Сохранено")
    except Exception as e:
        logging.exception(f"report_status error: {e}")
        await callback.answer("Ошибка сохранения")

async def main():
    try:
        await init_db()
        print("Бот запущен")
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception(f"main error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
