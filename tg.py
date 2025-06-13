import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import google.generativeai as genai
import sqlite3
import random
from datetime import datetime, timedelta

# Logging sozlamalari
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Gemini API sozlamalari
GOOGLE_API_KEY = "AIzaSyCi2CDi45M5pk9cM49G7YdJ9BlWX06GdeQ"  # Google AI Studio’dan olgan API kaliti
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# SQLite ma’lumotlar bazasini sozlash
def init_db():
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    # Jadvalni yaratish yoki tekshirish
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (user_id INTEGER, message TEXT, response TEXT, timestamp TEXT)''')
    # language ustuni mavjudligini tekshirish va qo‘shish
    c.execute("PRAGMA table_info(chat_history)")
    columns = [info[1] for info in c.fetchall()]
    if 'language' not in columns:
        c.execute("ALTER TABLE chat_history ADD COLUMN language TEXT DEFAULT 'uz'")
    conn.commit()
    conn.close()

# Suhbat tarixini saqlash
def save_message(user_id, message, response, language):
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO chat_history (user_id, message, response, timestamp, language) VALUES (?, ?, ?, ?, ?)",
              (user_id, message, response, timestamp, language))
    conn.commit()
    conn.close()

# Suhbat tarixini olish (oxirgi 10 daqiqa ichidagi xabarlar)
def get_chat_history(user_id, time_limit_minutes=10, max_messages=10):
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    time_threshold = (datetime.now() - timedelta(minutes=time_limit_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT message, response, language FROM chat_history WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
              (user_id, time_threshold, max_messages))
    history = c.fetchall()
    conn.close()
    return history

# Ma'lumotlar bazasini tozalash (1 soatdan eski xabarlarni o'chirish)
def clean_old_messages():
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    time_threshold = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("DELETE FROM chat_history WHERE timestamp < ?", (time_threshold,))
    conn.commit()
    conn.close()

# Tilni aniqlash funksiyasi
def detect_language(message):
    message = message.lower().strip()
    uzbek_words = {"salom", "nima", "yaxshimisiz", "qalesan", "nima gap", "yaxshilikmi"}
    russian_words = {"привет", "здравствуйте", "как дела", "что нового"}
    english_words = {"hello", "hi", "how are you", "what's up"}
    
    if any(word in message for word in uzbek_words):
        return "uz"
    elif any(word in message for word in russian_words):
        return "ru"
    elif any(word in message for word in english_words):
        return "en"
    return "uz"  # Standart til o‘zbek tili

# Maxsus javoblar (o‘zbek, rus, ingliz tillarida)
custom_responses = {
    "uz": {
        "salom": "Assalomu alaykum! 😊 Mening ismim AIRO, YoungMea tomonidan yaratilgan Beta AI man. Nima gap, do‘stim?",
        "nima yangilik?": "Hech nima los, lekin sen bilan suhbat har doim yangilik! 😎 Sen nima deysan?",
        "yaxshimisiz?": "Zo‘r, rahmat! 😄 Senchi, qalaysan?",
        "nima qilyapsan?": "Mana shu yerda, sen bilan gaplashib, dunyoni biroz qiziqroq qilyapman! 😜 Sen nima qilyapsan?",
        "qalesan?": "Judayam zo‘r, sen kabi! 😄 Kayfiyating qanday?",
        "nima gap?": "Nima gap, ukam! 😎 Bugun nimalar bilan bandsan?",
        "yaxshilikmi?": "Yaxshilik, do‘stim! 😊 Sen bilan gaplashsam, yanada yaxshi bo‘ladi!"
    },
    "ru": {
        "привет": "Привет! 😊 Я AIRO, бета-ИИ от YoungMea. Как дела, друг?",
        "здравствуйте": "Здравствуйте! Я AIRO, твой умный помощник. Чем могу помочь? 😄",
        "как дела?": "Всё круто, спасибо! 😎 А у тебя как дела?",
        "что нового?": "Ничего нового, но с тобой всегда весело! 😜 Что скажешь?",
        "что делаешь?": "Тут болтаю с тобой, делаю мир чуточку интереснее! 😄 А ты что делаешь?"
    },
    "en": {
        "hello": "Hey there! 😊 I'm AIRO, a beta AI by YoungMea. What's up, buddy?",
        "hi": "Hi! I'm AIRO, your smart assistant. How can I help you today? 😄",
        "how are you?": "Doing great, thanks! 😎 How about you?",
        "what's up?": "Not much, just chilling with you! 😜 What's on your mind?",
        "what are you doing?": "Just hanging out here, making the world more fun! 😄 What about you?"
    }
}

# Hazillar ro‘yxati (har bir tilda)
jokes = {
    "uz": [
        "Nega oshpaz palovni yomon pishirdi? Chunki u retseptni Google Translate’da tarjima qildi! 😄",
        "Kompyuter nima uchun dasturchi bo‘ldi? U faqat 0 va 1 bilan gaplasha olardi! 😎",
        "O‘zbek taomlari ichida eng aqlli palov qaysi? IQ-plov, albatta! 😜",
        "Nega robot sevib qoldi? Chunki uning yuragi 1’lar bilan to‘ldi! 😍",
        "Nega lag‘mon sovuq edi? Chunki u Wi-Fi’siz pishirilgan! 😅"
    ],
    "ru": [
        "Почему повар плохо приготовил плов? Потому что он перевёл рецепт через Google Translate! 😄",
        "Почему компьютер стал программистом? Потому что он говорил только на 0 и 1! 😎",
        "Какой плов самый умный? IQ-плов, конечно! 😜",
        "Почему робот влюбился? Потому что его сердце заполнилось единицами! 😍",
        "Почему лагман был холодный? Потому что его готовили без Wi-Fi! 😅"
    ],
    "en": [
        "Why did the chef mess up the pilaf? Because he used Google Translate for the recipe! 😄",
        "Why did the computer become a programmer? It could only speak in 0s and 1s! 😎",
        "Which pilaf is the smartest? IQ-pilaf, of course! 😜",
        "Why did the robot fall in love? Its heart was full of 1s! 😍",
        "Why was the lagman cold? It was cooked without Wi-Fi! 😅"
    ]
}

# /start buyrug'i
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    init_db()
    clean_old_messages()
    update.message.reply_text(
        f"Assalomu alaykum, {update.message.from_user.first_name}! 😊 Men AIRO, o‘zbek, rus va ingliz tillarida suhbatlashadigan aqlli botman. "
        "/help orqali buyruqlarni ko‘r yoki shunchaki gaplashamiz, do‘stim!"
    )

# /help buyrug'i
def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Mavjud buyruqlar:\n"
        "/start - Botni ishga tushirish\n"
        "/help - Yordam ma’lumotlari\n"
        "/joke - Hazil eshitish (o‘zbek, rus yoki ingliz tilida)\n"
        "/history - Oxirgi suhbatlarni ko‘rish\n"
        "O‘zbek, rus yoki ingliz tilida yoz, men mos javob beraman! 😎"
    )

# /joke buyrug'i
def joke(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    language = context.user_data.get('language', 'uz')  # Foydalanuvchi tilini olish
    joke_text = random.choice(jokes[language])
    save_message(user_id, "/joke", joke_text, language)
    update.message.reply_text(joke_text)

# /history buyrug'i
def history(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    chat_history = get_chat_history(user_id)
    if not chat_history:
        update.message.reply_text("Hozircha suhbat tarixing yo‘q. Gaplashamizmi, do‘stim? 😊")
        return
    response = "So‘nggi suhbatlaring:\n"
    for msg, resp, lang in reversed(chat_history):
        response += f"👤 Sen ({lang}): {msg}\n🤖 AIRO: {resp}\n---\n"
    update.message.reply_text(response)

# Foydalanuvchi xabarlariga javob berish
def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_message = update.message.text
    language = detect_language(user_message)
    context.user_data['language'] = language  # Foydalanuvchi tilini saqlash
    
    # Maxsus javoblarni tekshirish
    for key, response in custom_responses[language].items():
        if key in user_message.lower():
            save_message(user_id, user_message, response, language)
            update.message.reply_text(response)
            return
    
    # Suhbat tarixini olish
    chat_history = get_chat_history(user_id)
    history_prompt = ""
    for msg, resp, lang in reversed(chat_history):
        history_prompt += f"Foydalanuvchi ({lang}): {msg}\nAIRO: {resp}\n"
    
    # Gemini orqali javob generatsiya qilish
    try:
        prompt = (
            f"Siz AIRO nomli, {language} tilida ravon gaplashadigan, do‘stona va tabiiy suhbatlashadigan AI botsiz. "
            "Foydalanuvchi bilan oldingi suhbatni hisobga oling va xuddi yaqin do‘st bilan gaplashayotgandek, "
            f"{language} tilida, hazil bilan va tabiiy javob ber. Agar savol aniq bo‘lmasa, qiziqarli va do‘stona javob ber. "
            f"Oldingi suhbat:\n{history_prompt}\nFoydalanuvchi xabari: {user_message}"
        )
        response = model.generate_content(
            prompt,
            generation_config={"max_output_tokens": 200, "temperature": 0.9}
        )
        bot_response = response.text or f"Kechirasiz, nimadir chalkashib ketdi. 😅 Yana nima deysiz, do‘stim?"
        save_message(user_id, user_message, bot_response, language)
        update.message.reply_text(bot_response)
    except Exception as e:
        logger.error(f"Gemini API xatosi: {e}")
        update.message.reply_text("Nimadir xato bo‘ldi, ukam. 😅 Keyinroq yana urinib ko‘ramiz, yaxshi?")

# Xato loglari uchun funksiya
def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update {update} caused error {context.error}')

def main() -> None:
    # Bot tokenini kiriting
    TOKEN = "8065125088:AAHB8JYM2ZrudlHaDhvrOIxIBXPSk7054SA"  # BotFather’dan olgan Telegram tokeni

    # Ma’lumotlar bazasini ishga tushirish
    init_db()
    clean_old_messages()

    # Updater obyekti
    updater = Updater(TOKEN)

    # Dispatcher
    dp = updater.dispatcher

    # Buyruqlar va xabarlar uchun handler’lar
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("joke", joke))
    dp.add_handler(CommandHandler("history", history))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_error_handler(error)

    # Botni ishga tushirish
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()