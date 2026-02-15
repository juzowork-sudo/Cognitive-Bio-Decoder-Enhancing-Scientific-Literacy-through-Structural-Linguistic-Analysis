import asyncio
import logging
import random
import json
import os
import time
import math
import warnings
from datetime import datetime, timedelta
import io

# --- ГЛУШИТЕЛЬ ПРЕДУПРЕЖДЕНИЙ ---
warnings.filterwarnings("ignore")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

# --- ПОДКЛЮЧЕНИЕ ГРАФИКОВ ---
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("⚠️ Matplotlib не установлен. Графики не будут работать.")

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- НАСТРОЙКИ ---
API_TOKEN = '8320403546:AAFniV3vUipxFb5slT6gkVWYTxDmszLIsHE'
GOOGLE_API_KEY = "AIzaSyAmy5rHzqSjHDMnasmQSWvfN0JDQJaDvmQ" 
DAILY_LIMIT = 10 
REMINDER_HOUR = 19

logging.basicConfig(level=logging.INFO)

# --- БЕЗОПАСНОСТЬ ИИ ---
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- АВТО-ПОДКЛЮЧЕНИЕ ИИ ---
ACTIVE_MODEL = None
print("⚙️ Подключаю ИИ...")
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            clean_name = m.name.replace("models/", "")
            ACTIVE_MODEL = genai.GenerativeModel(model_name=clean_name, safety_settings=SAFETY_SETTINGS)
            print(f"🚀 ИИ подключен: {clean_name}")
            break
except Exception as e:
    print(f"❌ Ошибка ИИ: {e}")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
USER_DB_FILE = "user_progress.json"
MORPH_DB_FILE = "database.json"

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
def load_json(filename):
    if not os.path.exists(filename): return {}
    try:
        with open(filename, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- БАЗА ЗНАНИЙ ---
MORPHEMES = {} 
COMPLEX_TERMS = {
    "Фотосинтез": "Свет + Соединение", "Цитология": "Клетка + Наука",
    "Гидролиз": "Вода + Растворение", "Биология": "Жизнь + Наука",
    "Эпидермис": "Над + Кожа", "Автотроф": "Сам + Питание",
    "Микробиология": "Малый + Жизнь + Наука", "Прокариоты": "Перед + Ядро",
    "Гемофилия": "Кровь + Любовь"
}

# --- АЛГОРИТМ SUPERMEMO-2 (SM-2) ---
def calculate_sm2(quality, repetitions, interval, ease_factor):
    """
    quality: 0-5 (оценка пользователя)
    repetitions: кол-во успешных повторений подряд
    interval: текущий интервал в днях
    ease_factor: сложность слова (стандарт 2.5)
    """
    if quality < 3:
        # Если забыл или трудно - сброс
        return 0, 1, ease_factor
    
    # Если вспомнил (3-5)
    new_repetitions = repetitions + 1
    
    if new_repetitions == 1:
        new_interval = 1
    elif new_repetitions == 2:
        new_interval = 6
    else:
        new_interval = math.ceil(interval * ease_factor)
    
    # Формула изменения Ease Factor
    new_ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if new_ease_factor < 1.3: new_ease_factor = 1.3
    
    return new_repetitions, new_interval, round(new_ease_factor, 2)

# --- МЕНЮ ---
def get_main_menu(streak=0):
    fire_text = f"🔥 {streak} дн." if streak > 0 else "🔥 Старт"
    kb = [
        [KeyboardButton(text="🎓 Учить морфемы")],
        [KeyboardButton(text="🤖 Морфемный анализ терминов"), KeyboardButton(text="🧩 Угадай термин")],
        [KeyboardButton(text="📊 Мой прогресс"), KeyboardButton(text=fire_text)] 
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ЛОГИКА ПРОГРЕССА ---
def check_user_data(user_data):
    today = datetime.now().strftime("%Y-%m-%d")
    
    if "stats" not in user_data: 
        user_data["stats"] = {"studied": 0, "today_new": 0, "last_date": "", "streak": 0}
    if "history" not in user_data: user_data["history"] = {}
    if "streak" not in user_data["stats"]: user_data["stats"]["streak"] = 0

    if user_data["stats"].get("last_date") != today:
        last_date_str = user_data["stats"].get("last_date")
        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_diff = (datetime.now().date() - last_date).days
            if days_diff > 1:
                user_data["stats"]["streak"] = 0
        user_data["stats"]["today_new"] = 0 
    
    return user_data

def update_streak(user_data):
    today = datetime.now().strftime("%Y-%m-%d")
    last_date_str = user_data["stats"].get("last_date")
    
    if last_date_str != today:
        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            yesterday = datetime.now().date() - timedelta(days=1)
            
            if last_date == yesterday:
                user_data["stats"]["streak"] += 1
            elif last_date != datetime.now().date():
                user_data["stats"]["streak"] = 1
        else:
            user_data["stats"]["streak"] = 1
            
        user_data["stats"]["last_date"] = today
    return user_data

# --- ГРАФИКИ ---
def create_progress_graph(history_data):
    if not HAS_MATPLOTLIB: return None
    dates = sorted(list(history_data.keys()))[-7:]
    values = [history_data[d] for d in dates]
    if not dates: dates, values = ["Сегодня"], [0]

    plt.figure(figsize=(6, 4))
    bars = plt.bar(dates, values, color='#FF5722', zorder=3)
    plt.title('Активность (Огонек 🔥)', fontsize=14)
    plt.grid(axis='y', linestyle='--', alpha=0.7, zorder=0)
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2.0, height, '%d' % int(height), ha='center', va='bottom')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

# --- ИИ ЗАПРОС ---
async def ask_gemini(term):
    if not ACTIVE_MODEL: return "⚠️ ИИ не подключен."
    try:
        prompt = (f"Ты — академический словарь. Термин: '{term}'.\n"
                  f"Задача:\n1. Исправь опечатки.\n"
                  f"2. Морфемный разбор: Переведи КАЖДЫЙ корень.\n"
                  f"   Пример: Миокард -> [Мио-] (мышца) + [-кард] (сердце).\n"
                  f"3. Определение: Одно предложение.\nБез воды.")
        response = await ACTIVE_MODEL.generate_content_async(prompt)
        return response.text if response.text else "⚠️ Пустой ответ."
    except Exception as e:
        return f"⚠️ Ошибка: {e}"

# --- ФОНОВАЯ ЗАДАЧА ---
async def daily_reminder_task():
    print("⏰ Служба напоминаний запущена...")
    while True:
        now = datetime.now()
        if now.hour == REMINDER_HOUR and now.minute == 0:
            db = load_json(USER_DB_FILE)
            today = now.strftime("%Y-%m-%d")
            for user_id, data in db.items():
                if data.get("stats", {}).get("last_date") != today:
                    streak = data.get("stats", {}).get("streak", 0)
                    msg = f"🔥 **Огонек ({streak} дн.) гаснет!**\nЗайди на пару минут."
                    try: await bot.send_message(user_id, msg, parse_mode="Markdown")
                    except: pass
            await asyncio.sleep(61)
        await asyncio.sleep(60)

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    global MORPHEMES
    MORPHEMES = load_json(MORPH_DB_FILE)
    streak = load_json(USER_DB_FILE).get(str(message.chat.id), {}).get("stats", {}).get("streak", 0)
    await message.answer(f"🧬 **Bio-Decoder**\nСистема Anki (SM-2) активирована! 🧠", reply_markup=get_main_menu(streak), parse_mode="Markdown")

@dp.message(F.text == "🤖 Морфемный анализ терминов")
async def ai_mode_start(message: types.Message):
    await message.answer("🤖 Введите термин:")

@dp.message(F.text == "🎓 Учить морфемы")
async def study_mode(message: types.Message):
    global MORPHEMES
    if not MORPHEMES: MORPHEMES = load_json(MORPH_DB_FILE)
    user_id = str(message.chat.id)
    db = load_json(USER_DB_FILE)
    if user_id not in db: db[user_id] = {}
    db[user_id] = check_user_data(db[user_id])
    save_json(USER_DB_FILE, db)

    now_ts = time.time()
    due_cards = []
    
    # 1. Сначала повторения (Review)
    if "cards" in db[user_id]:
        for m in db[user_id]["cards"]:
            if db[user_id]["cards"][m]["next_review"] <= now_ts: due_cards.append(m)
    
    # 2. Потом новые (New), если лимит позволяет
    if not due_cards:
        if db[user_id]["stats"]["today_new"] >= DAILY_LIMIT:
            streak = db[user_id]["stats"].get("streak", 0)
            await message.answer(f"🛑 План выполнен!\nЖду тебя завтра.", reply_markup=get_main_menu(streak))
            return
        
        all_keys = list(MORPHEMES.keys())
        random.shuffle(all_keys)
        new_cards = [k for k in all_keys if k not in db[user_id].get("cards", {})]
        
        if not new_cards: return await message.answer("🎉 База выучена!")
        due_cards = new_cards[:1]

    current_morph = random.choice(due_cards)
    status = "🆕 Новое" if "cards" not in db[user_id] or current_morph not in db[user_id]["cards"] else "re Повторение"
    
    btn = [[InlineKeyboardButton(text="Показать ответ 🔄", callback_data=f"show:{current_morph}")]]
    await message.answer(f"[{status}]\nТермин: **{current_morph.upper()}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=btn), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("show:"))
async def show_back(call: CallbackQuery):
    morph = call.data.split(":")[1]
    data = MORPHEMES.get(morph, {"m": "...", "ex": "..."})
    # Кнопки с оценками для SM-2
    btns = [
        [InlineKeyboardButton(text="Снова (1м)", callback_data=f"rate:{morph}:again"),
         InlineKeyboardButton(text="Трудно (10м)", callback_data=f"rate:{morph}:hard")],
        [InlineKeyboardButton(text="Хорошо", callback_data=f"rate:{morph}:good"),
         InlineKeyboardButton(text="Легко", callback_data=f"rate:{morph}:easy")]
    ]
    await call.message.edit_text(f"🧬 **{morph.upper()}**\n\n📖 {data['m']}\n💡 {data['ex']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("rate:"))
async def rate_card(call: CallbackQuery):
    _, morph, rating_str = call.data.split(":")
    user_id = str(call.message.chat.id)
    db = load_json(USER_DB_FILE)
    if "cards" not in db[user_id]: db[user_id]["cards"] = {}
    
    db[user_id] = check_user_data(db[user_id])
    db[user_id] = update_streak(db[user_id])
    streak = db[user_id]["stats"]["streak"]
    
    # 1. Получаем текущие параметры карточки (или дефолтные)
    card_data = db[user_id]["cards"].get(morph, {"repetitions": 0, "interval": 0, "ease_factor": 2.5})
    
    # 2. Конвертируем кнопку в оценку SM-2 (Quality 0-5)
    quality = 0
    if rating_str == "again": quality = 0 # Fail
    elif rating_str == "hard": quality = 3 # Hard pass
    elif rating_str == "good": quality = 4 # Good pass
    elif rating_str == "easy": quality = 5 # Easy pass

    # 3. Рассчитываем новые параметры по алгоритму SM-2
    new_rep, new_int_days, new_ef = calculate_sm2(
        quality, 
        card_data.get("repetitions", 0), 
        card_data.get("interval", 0), 
        card_data.get("ease_factor", 2.5)
    )

    # 4. Вычисляем время следующего показа
    now = time.time()
    if quality < 3: # Again
        next_review = now + 60 # 1 минута
    elif quality == 3: # Hard
        next_review = now + 600 # 10 минут
    else: # Good/Easy
        next_review = now + (new_int_days * 86400) # Дни в секунды

    # 5. Сохраняем новые данные
    is_new = morph not in db[user_id]["cards"]
    db[user_id]["cards"][morph] = {
        "next_review": next_review,
        "last_rating": rating_str,
        "repetitions": new_rep,
        "interval": new_int_days,
        "ease_factor": new_ef
    }
    
    congrats_message = None
    if is_new: 
        db[user_id]["stats"]["today_new"] += 1
        if db[user_id]["stats"]["today_new"] == DAILY_LIMIT:
            congrats_message = f"🎉 **Ты крутой!**\nПлан выполнен!\n🔥 Стрик: {streak} дн."
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    db[user_id]["history"][today_str] = db[user_id]["history"].get(today_str, 0) + 1
    save_json(USER_DB_FILE, db)
    
    await call.message.delete()
    if congrats_message:
        await call.message.answer(congrats_message, reply_markup=get_main_menu(streak), parse_mode="Markdown")
    await study_mode(call.message)

@dp.message(F.text == "🧩 Угадай термин")
async def game_start(message: types.Message):
    if not COMPLEX_TERMS: return
    term, correct = random.choice(list(COMPLEX_TERMS.items()))
    values = list(COMPLEX_TERMS.values())
    if correct in values: values.remove(correct)
    opts = random.sample(values, min(2, len(values))) + [correct]
    random.shuffle(opts)
    btns = [[InlineKeyboardButton(text=o, callback_data=f"guess:{'1' if o==correct else '0'}")] for o in opts]
    await message.answer(f"🧩 **{term.upper()}** - это?", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("guess:"))
async def game_check(call: CallbackQuery):
    txt = "✅ Верно!" if call.data.split(":")[1] == "1" else "❌ Ошибка."
    await call.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Дальше ➡️", callback_data="play_next")]]))

@dp.callback_query(F.data == "play_next")
async def play_next(call: CallbackQuery):
    await call.message.delete()
    await game_start(call.message)

@dp.message(F.text == "📊 Мой прогресс")
async def stats(message: types.Message):
    db = load_json(USER_DB_FILE)
    u = db.get(str(message.chat.id))
    if not u: return
    u = check_user_data(u)
    streak = u["stats"].get("streak", 0)
    photo = create_progress_graph(u.get("history", {}))
    caption = f"📊 **Статистика**\n🔥 Серия: **{streak} дн.**\n📚 Выучено: **{len(u.get('cards', {}))}**"
    if photo: await message.answer_photo(BufferedInputFile(photo.read(), "chart.png"), caption=caption, parse_mode="Markdown")
    else: await message.answer(caption)

@dp.message(F.text.startswith("🔥"))
async def fire_status(message: types.Message): await stats(message)

@dp.message()
async def handle_ai(message: types.Message):
    if message.text.startswith("/") or message.text in ["🎓 Учить морфемы", "🤖 Морфемный анализ терминов", "🧩 Угадай термин", "📊 Мой прогресс"]: return
    w = await message.answer("⏳ Анализирую...")
    res = await ask_gemini(message.text)
    await w.delete()
    await message.answer(res, parse_mode="Markdown")

async def main():
    asyncio.create_task(daily_reminder_task())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())