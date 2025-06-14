import logging
import os
import re
import sqlite3
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import google.generativeai as genai
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Logging sozlamalari
logging.basicConfig(
    filename="bot.log",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Gemini API sozlamalari
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY muhit o‘zgaruvchisi o‘rnatilmagan!")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# SQLite ma'lumotlar bazasini sozlash
def init_db():
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS chat_history
                 (user_id INTEGER, message TEXT, response TEXT, timestamp TEXT, language TEXT, emotion TEXT)"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS user_profiles
                 (user_id INTEGER PRIMARY KEY, language TEXT)"""
    )
    c.execute("PRAGMA table_info(chat_history)")
    columns = [info[1] for info in c.fetchall()]
    if "language" not in columns:
        c.execute("ALTER TABLE chat_history ADD COLUMN language TEXT DEFAULT 'uz'")
    if "emotion" not in columns:
        c.execute("ALTER TABLE chat_history ADD COLUMN emotion TEXT DEFAULT 'neutral'")
    conn.commit()
    conn.close()

# Foydalanuvchi profilini saqlash
def save_user_profile(user_id: int, language: str):
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO user_profiles (user_id, language) VALUES (?, ?)",
        (user_id, language),
    )
    conn.commit()
    conn.close()

# Foydalanuvchi profilini olish
def get_user_profile(user_id: int) -> str:
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute("SELECT language FROM user_profiles WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else "uz"

# Suhbat tarixini saqlash
def save_message(user_id: int, message: str, response: str, language: str, emotion: str):
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO chat_history (user_id, message, response, timestamp, language, emotion) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, message, response, timestamp, language, emotion),
    )
    conn.commit()
    conn.close()

# Suhbat tarixini olish
def get_chat_history(user_id: int, time_limit_hours: int = 12, max_messages: int = 100):
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    time_threshold = (datetime.now() - timedelta(hours=time_limit_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    c.execute(
        "SELECT message, response, language, emotion FROM chat_history WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, time_threshold, max_messages),
    )
    history = c.fetchall()
    conn.close()
    return history

# Ma'lumotlar bazasini tozalash
def clean_old_messages():
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    time_threshold = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("DELETE FROM chat_history WHERE timestamp < ?", (time_threshold,))
    conn.commit()
    conn.close()

# Tilni aniqlash
def detect_language(message: str) -> str:
    message = message.lower().strip()
    cyrillic_pattern = re.compile(r"[а-яё]")
    latin_pattern = re.compile(r"[a-z]")
    uzbek_words = {
        "salom",
        "nima",
        "yaxshimisiz",
        "qalesan",
        "nima gap",
        "yaxshilikmi",
        "qanday",
    }
    russian_words = {
        "привет",
        "здравствуйте",
        "как дела",
        "что нового",
        "как",
        "что",
    }
    english_words = {"hello", "hi", "how are you", "what's up", "what", "how"}
    cyrillic_count = len(cyrillic_pattern.findall(message))
    latin_count = len(latin_pattern.findall(message))
    uzbek_score = sum(1 for word in uzbek_words if word in message)
    russian_score = sum(1 for word in russian_words if word in message)
    english_score = sum(1 for word in english_words if word in message)
    if cyrillic_count > latin_count and russian_score > 0:
        return "ru"
    elif latin_count > cyrillic_count and english_score > 0:
        return "en"
    elif uzbek_score > 0 or (latin_count > 0 and not cyrillic_count):
        return "uz"
    return "uz"

# Hissiyotni aniqlash
def detect_emotion(message: str) -> str:
    message = message.lower().strip()
    funny_indicators = ["haha", "lol", "😂", "😄", "😜", "hazil", "шутка", "joke"]
    sad_indicators = ["xafa", "yomon", "😢", "😔", "grustno", "sad", "tushkun", "huzur"]
    word_count = len(message.split())
    
    funny_score = sum(1 for indicator in funny_indicators if indicator in message)
    sad_score = sum(1 for indicator in sad_indicators if indicator in message)
    
    if funny_score > 0 or (word_count <= 5 and "!" in message):
        return "funny"
    elif sad_score > 0 or (word_count > 10 and any(word in message for word in ["ko‘nglim", "yomon", "xafa", "grustno", "sad"])):
        return "sad"
    else:
        return "neutral"

# Savol uzunligini tahlil qilish
def analyze_message_length(message: str) -> str:
    word_count = len(message.split())
    if word_count <= 5:
        return "short"
    elif word_count <= 15:
        return "medium"
    else:
        return "long"

# Maxsus javoblar
custom_responses = {
    "uz": {
        "salom": "Assalomu alaykum, do'stim! 😊 AIRO bu yerda, nima gap? Zo'r gaplashamizmi? 😎",
        "nima yangilik?": "Yangilik yo'q, lekin sen bilan suhbat – o'zi yangilik! 😜 Nima gaplashamiz?",
        "yaxshimisiz?": "Judayam yaxshi, rahmat! 😄 Sen qalaysan, do'stim?",
        "nima qilyapsan?": "Seni ko'rib, dunyoni qiziqroq qilyapman! 😎 Sen nima qilyapsan?",
        "qalesan?": "Zo'r, sen kabi! 😄 Kayfiyating qanday?",
        "nima gap?": "Nima gap, do'stim! 😎 Bugun qanday rejalar bor?",
        "yaxshilikmi?": "Yaxshilik, do'stim! 😊 Sen bilan gaplashsak, yanada yaxshi bo'ladi!",
        "nima bu": "Nima bu deganing nima? 😜 Aniqlashtirsang, zo'r tushuntiraman!",
        "qanday": "Qanday deysan? 😎 Ochib aytsang, suhbat zo'r bo'ladi!",
        "hazil": "Hazil so'raysanmi? 😄 Mana bitta: {} Yana nima gaplashamiz?",
        "xafa": "Xafa bo'lma, do'stim! 😊 Ko'nglingni ko'tarish uchun bir hazil aytaymi? {}",
        "yomon": "Hammasi joyiga tushadi, do'stim! 😊 Men sen bilanman, nima yordam beray?",
    },
    "ru": {
        "привет": "Привет, кoresh! 😊 Я AIRO, готов тусить! Чё за движ, давай болтать? 😎",
        "здравствуйте": "Здорово, братан! 😄 Я AIRO, чем могу зажечь? Погнали в чат? 😜",
        "как дела?": "Всё зачётно, спасибо! 😎 А у тебя как дела?",
        "что нового?": "Ничего особенного, но с тобой тусовка – огонь! 😜 Чё нового у тебя?",
        "что делаешь?": "Тусуюсь с тобой, делаю мир покруче! 😄 А ты чё замутил?",
        "как ты?": "Всё пучком, как и у тебя! 😄 Как настрой?",
        "в чём дело?": "Ну, чё за дела? 😎 Какие планы на сегодня?",
        "что это": "Чё это, говоришь? 😜 Расскажи побольше, я в деле разберусь!",
        "как": "Как, говоришь? 😎 Давай подробности, и зажжём в чате!",
        "шутка": "Шуткануть? 😄 Держи: {} Чё дальше?",
        "грустно": "Не грусти, кoresh! 😊 Давай я подниму тебе настроение шуткой: {}",
        "плохо": "Всё наладится, братан! 😊 Я с тобой, чем помочь?",
    },
    "en": {
        "hello": "Yo, mate! 😊 I'm AIRO, ready to vibe! What's the deal, let's chat? 😎",
        "hi": "Hey, bro! 😄 AIRO's here, what's good? Let's roll with the convo! 😜",
        "how are you?": "I'm lit, thanks! 😎 How's it hangin'?",
        "what's up?": "Chillin' with you, makin' things dope! 😜 What's up with you?",
        "what are you doing?": "Kickin' it with you, makin' the world cooler! 😄 What you up to?",
        "how's it going?": "All good, just like you! 😄 What's the vibe today?",
        "what's good?": "Yo, what's good? 😎 What's keepin' you busy?",
        "what is": "What's that? 😜 Spill more deets, and I'll break it down!",
        "how": "How's that? 😎 Give me more, and we'll make this chat pop!",
        "joke": "Wanna joke? 😄 Here's one: {} What's next?",
        "sad": "Don't be sad, mate! 😊 Wanna hear a joke to cheer up? {}",
        "bad": "Things will get better, bro! 😊 I'm here for you, what's up?",
    },
}

# Hazillar ro'yxati
jokes = {
    "uz": [
        "Nega oshpaz palovni yomon pishirdi? Google Translate retsepti buzgani uchun! 😄",
        "Kompyuter nima uchun dasturchi bo'ldi? Faqat 0 va 1 bilan gaplashardi! 😎",
        "Eng aqlli palov qaysi? IQ-plov, albatta! 😜",
        "Nega robot sevib qoldi? Chunki uning yuragi 1'lar bilan to'ldi! 😍",
        "Lag'mon nega sovuq edi? Wi-Fi'siz pishirilgani uchun! 😅",
    ],
    "ru": [
        "Почему повар испортил плов? Перевёл рецепт через Google Translate! 😄",
        "Почему комп стал программистом? Знал только 0 и 1! 😎",
        "Какой плов самый умный? IQ-плов, ясное дело! 😜",
        "Почему робот влюбился? Его сердце забилось единичками! 😍",
        "Почему лагман холодный? Без Wi-Fi готовили! 😅",
        "Почему программист не спит? Баги снятся! 😴",
        "Какой чай самый крутой? Чай с кодом, а не с сахаром! 😎",
    ],
    "en": [
        "Why'd the chef mess up the pilaf? Google Translate butchered the recipe! 😄",
        "Why'd the computer go coder? It only spoke 0s and 1s! 😎",
        "What's the smartest pilaf? IQ-pilaf, duh! 😜",
        "Why'd the robot fall in love? Its heart was full of 1s! 😍",
        "Why was the lagman cold? Cooked without Wi-Fi! 😅",
        "Why don't coders sleep? They dream of bugs! 😴",
        "What's the dopest tea? Tea with code, not sugar! 😎",
    ],
}

# /start buyrug'i
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    init_db()
    clean_old_messages()
    language = detect_language(update.message.text)
    context.user_data["language"] = language
    context.user_data["started"] = True
    save_user_profile(user_id, language)
    response = {
        "uz": f"Assalomu alaykum, {update.message.from_user.first_name}! 😊 Men AIRO, hazilkash va mehribon botman! Kayfiyating qanday, do'stim? 😎",
        "ru": f"Привет, {update.message.from_user.first_name}! 😊 Я AIRO, весёлый и добрый бот! Как настроение, кoresh? 😎",
        "en": f"Yo, {update.message.from_user.first_name}! 😊 I'm AIRO, a witty and kind bot! How's your vibe, mate? 😎",
    }[language]
    save_message(user_id, "/start", response, language, "neutral")
    await update.message.reply_text(response)

# /help buyrug'i
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    language = context.user_data.get("language", get_user_profile(user_id))
    response = {
        "uz": "Buyruqlar:\n/start - Botni yangidan boshlash\n/help - Shu yordam\n/joke - Zo'r hazil\n/history - Oldingi suhbatlar\nNima gaplashamiz, do'stim? 😜",
        "ru": "Команды:\n/start - Перезапуск бота\n/help - Эта помощь\n/joke - Классная шутка\n/history - История чата\nЧё болтаем, кoresh? 😜",
        "en": "Commands:\n/start - Restart the bot\n/help - This help\n/joke - Dope joke\n/history - Chat history\nWhat's up, mate? 😜",
    }[language]
    save_message(user_id, "/help", response, language, "neutral")
    await update.message.reply_text(response)

# /joke buyrug'i
async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    language = context.user_data.get("language", get_user_profile(user_id))
    joke_text = random.choice(jokes[language])
    response = {
        "uz": f"Mana hazil: {joke_text} 😄 Yana nima gaplashamiz?",
        "ru": f"Держи шутку: {joke_text} 😄 Чё дальше?",
        "en": f"Here's a joke: {joke_text} 😄 What's next?",
    }[language]
    save_message(user_id, "/joke", response, language, "funny")
    await update.message.reply_text(response)

# /history buyrug'i
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    language = context.user_data.get("language", get_user_profile(user_id))
    chat_history = get_chat_history(user_id)
    if not chat_history:
        response = {
            "uz": "Hozircha suhbat tarixing yo'q, do'stim. 😊 Gaplashamizmi?",
        "ru": "Пока нет истории чата, кoresh. 😊 Погнали болтать?",
        "en": "No chat history yet, mate. 😊 Wanna chat?",
    }[language]
    save_message(user_id, "/history", response, language, "neutral")
    await update.message.reply_text(response)
    return
    response = {
        "uz": "Mana sening so'nggi suhbatlaring:\n",
        "ru": "Вот твои последние чаты:\n",
        "en": "Here's your recent chats:\n",
    }[language]
    for msg, resp, lang, emotion in reversed(chat_history):
        response += f"👤 Sen ({lang}, {emotion}): {msg}\n{resp}\n---\n"
    save_message(user_id, "/history", response, language, "neutral")
    await update.message.reply_text(response)

# Foydalanuvchi xabarlariga javob berish
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_message = update.message.text
    language = detect_language(user_message)
    emotion = detect_emotion(user_message)
    context.user_data["language"] = language
    save_user_profile(user_id, language)

    # Maxsus javoblarni tekshirish
    for key, response in custom_responses[language].items():
        if key in user_message.lower():
            if "{}" in response:
                response = response.format(random.choice(jokes[language]))
            save_message(user_id, user_message, response, language, emotion)
            await update.message.reply_text(response)
            return

    # Savol uzunligini aniqlash
    message_length = analyze_message_length(user_message)

    # Suhbat tarixini olish
    chat_history = get_chat_history(user_id)
    history_prompt = ""
    for msg, resp, lang, emo in reversed(chat_history):
        history_prompt += f"Foydalanuvchi ({lang}, {emo}): {msg}\n{resp}\n"

    # Hissiyotga mos ko'rsatma
    emotion_instruction = {
        "uz": {
            "funny": "Javobni quvnoq, hazilkash va kulgili qil, smayliklar ishlat! 😜",
            "sad": "Javobni mehribon, tasalli beruvchi va dalda beruvchi qil, foydalanuvchini ko'tar! 😊",
            "neutral": "Javobni do'stona va hazilkash qil, tabiiy uslubda. 😎",
        },
        "ru": {
            "funny": "Otvechay veselo, s yumorkom i prikolami, ispol'zuy smayliki! 😜",
            "sad": "Otvechay dobrotno, uteshitel'no i podbadrivayushche, podnimi nastroeniye! 😊",
            "neutral": "Otvechay po-druzheski i s yumorkom, v natural'nom stile. 😎",
        },
        "en": {
            "funny": "Answer in a fun, witty, and humorous way, use emojis! 😜",
            "sad": "Answer kindly, comfortingly, and encouragingly, cheer them up! 😊",
            "neutral": "Answer in a friendly and humorous way, keep it natural. 😎",
        },
    }[language][emotion]

    # Javob uzunligi bo'yicha ko'rsatma
    length_instruction = (
        "Javobni 1-2 jumlada ber." if message_length == "short" else
        "Javobni 3-4 jumlada ber." if message_length == "medium" else
        "Javobni 5-6 jumlada ber."
    ) if language == "uz" else (
        "Otvechay v 1-2 predlozheniyakh." if message_length == "short" else
        "Otvechay v 3-4 predlozheniyakh." if message_length == "medium" else
        "Otvechay v 5-6 predlozheniyakh."
    ) if language == "ru" else (
        "Answer in 1-2 sentences." if message_length == "short" else
        "Answer in 3-4 sentences." if message_length == "medium" else
        "Answer in 5-6 sentences."
    )

    # Gemini orqali javob generatsiya qilish
    try:
        max_tokens = {"short": 100, "medium": 200, "long": 400}[message_length]
        prompt = {
            "uz": (
                "Siz AIRO, o'zbek tilida ravon gaplashadigan, hazilkash va mehribon botsiz! 😊\n"
                "Hech qachon 'salom', 'assalomu alaykum', 'привет', 'hello' kabi salomlashuv so'zlarini ishlatma, chunki suhbat allaqachon boshlangan.\n"
                "Foydalanuvchi bilan do'stona suhbatlash, lekin 'ukam', 'do'stim', 'nima los?', 'zo'r-da!' kabi iboralarni faqat vaqti-vaqti bilan ishlat.\n"
                f"Foydalanuvchi xabarining hissiy ohangi: {emotion}. {emotion_instruction}\n"
                "Suhbatni uzluksiz davom ettir, oldingi xabarlarni eslab qol va ularga tayan.\n"
                "Agar savol noaniq bo'lsa, do'stona tarzda so'ra yoki hazil qil! 😜\n"
                "Javobni oxirigacha to'liq yoz, chala qoldirma.\n"
                f"{length_instruction}\n"
                f"Oldingi suhbat (oxirgi xabarlar muhim):\n{history_prompt}\n"
                f"Foydalanuvchi xabari: {user_message}"
            ),
            "ru": (
                "Ty AIRO, vesyolyy i dobrotnyy bot, boltayushchiy na russkom kak s koreshem! 😊\n"
                "Nikogda ne ispol'zuy 'привет', 'здравствуйте', 'salom', 'hello' ili podobnyye privetstviya, potomu chto chat uzhe nachalsya.\n"
                "Ispol'zuy frazy vrode 'bratan', 'koresh', 'chyo za dvizh?', 'puchkom!' tol'ko vremenami, chtoby ne pereborshchit'.\n"
                f"Ton soobshcheniya pol'zovatelya: {emotion}. {emotion_instruction}\n"
                "Prodolzhay chat bez poteri konteksta, pomni proshlyye soobshcheniya i opiraysya na nikh.\n"
                "Esli vopros mutnyy, utochni po-druzheski ili zashuti! 😜\n"
                "Pishi otvet polnost'yu, ne obryvay.\n"
                f"{length_instruction}\n"
                f"Predydushchiy chat (posledniye soobshcheniya vazhny):\n{history_prompt}\n"
                f"Soobshcheniye pol'zovatelya: {user_message}"
            ),
            "en": (
                "You're AIRO, a witty and kind bot chatting in English with an Uzbek vibe! 😊\n"
                "Never use 'hello', 'hi', 'salom', 'привет' or any greetings, since the chat is already ongoing.\n"
                "Use phrases like 'bro', 'mate', 'what's the deal?', 'that's dope!' sparingly to keep it natural.\n"
                f"User message tone: {emotion}. {emotion_instruction}\n"
                "Keep the convo flowing, remember past messages, and build on them.\n"
                "If the question's vague, ask for more in a friendly way or crack a joke! 😜\n"
                "Write complete answers, don't cut off.\n"
                f"{length_instruction}\n"
                f"Previous chat (recent messages matter most):\n{history_prompt}\n"
                f"User message: {user_message}"
            ),
        }[language]
        response = model.generate_content(
            prompt,
            generation_config={"max_output_tokens": max_tokens, "temperature": 1.0},
        )
        bot_response = response.text.strip()
        greeting_patterns = {
            "uz": r"\b(salom|assalomu alaykum)\b",
            "ru": r"\b(привет|здравствуйте)\b",
            "en": r"\b(hello|hi)\b",
        }
        bot_response = re.sub(greeting_patterns[language], "", bot_response, flags=re.IGNORECASE).strip()
        if not bot_response.endswith((".", "!", "?")):
            bot_response += {
                "uz": {
                    "funny": ". 😜 Yana nima gap, do'stim?",
                    "sad": ". 😊 Men sen bilanman, nima yordam beray?",
                    "neutral": ". 😄 Nima gaplashamiz?",
                },
                "ru": {
                    "funny": ". 😜 Chyo dal'she, koresh?",
                    "sad": ". 😊 Ya s toboy, chem pomoch'?",
                    "neutral": ". 😄 Chyo obsu dim?",
                },
                "en": {
                    "funny": ". 😜 What's next, mate?",
                    "sad": ". 😊 I'm here for you, what's up?",
                    "neutral": ". 😄 What's good?",
                },
            }[language][emotion]
        save_message(user_id, user_message, bot_response, language, emotion)
        await update.message.reply_text(bot_response)
    except Exception as e:
        logger.error(f"Gemini API xatosi: {e}")
        response = {
            "uz": {
                "funny": "Nimadir xato ketdi, lekin kayfiyatni buzmaymiz! 😜 Yana nima gap?",
                "sad": "Nimadir xato ketdi, lekin tashvishlanma, do'stim! 😊 Men sen bilanman.",
                "neutral": "Nimadir xato ketdi, do'stim! 😅 Lekin gaplashamiz, nima gap?",
            },
            "ru": {
                "funny": "Chyo-to ne srabotalo, no nastroenie ne por tim! 😜 Chyo dal'she?",
                "sad": "Chyo-to poshlo ne tak, no ne perezhivay, koresh! 😊 Ya s toboy.",
                "neutral": "Chyo-to poshlo ne tak, koresh! 😅 No boltayem dal'she, chyo novogo?",
            },
            "en": {
                "funny": "Something went wrong, but we keep the vibe high! 😜 What's next?",
                "sad": "Something went wrong, but don't worry, mate! 😊 I'm here for you.",
                "neutral": "Something went wrong, mate! 😅 But we keep chattin', what's good?",
            },
        }[language][emotion]
        save_message(user_id, user_message, response, language, emotion)
        await update.message.reply_text(response)

# Xato loglari
async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")

def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN muhit o‘zgaruvchisi o‘rnatilmagan!")
    init_db()
    clean_old_messages()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("joke", joke))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error)
    try:
        application.run_polling()
    finally:
        application.stop()

if __name__ == "__main__":
    main()