import os
from dotenv import load_dotenv
import telebot
import sqlite3
import logging
import re
from collections import Counter

load_dotenv()

logging.basicConfig(
    filename="bot_log.log",
    filemode="w",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

conn = sqlite3.connect("cards.db", check_same_thread=False)
cursor = conn.cursor()

bot = telebot.TeleBot(os.getenv("TG_TOKEN"), parse_mode="Markdown")
logging.info("Bot started...")

cursor.execute("SELECT * FROM cards")
cards = cursor.fetchall()
last_card = cards[len(cards)-1][0]


rank_triggers = {
    "S": ["s", "S", "эс"],  # "с" кириллическое относится к S
    "C": ["c", "C", "си", "с"],   # "C" латинское и "си" относятся к C
    "A": ["a", "A", "а"],
    "B": ["b", "B", "б", "бэ"],
    "D": ["d", "D", "д"],
    "E": ["e", "E", "е"],
    "G": ["g", "G", "г", "гэ"],
    "H": ["h", "H", "аш"],
    "N": ["n", "N", "эн"],
    "P": ["p", "P", "п", "пэ"],
    "X": ["x", "X", "икс", ],
}

def find_most_common_rank(text, rank_triggers):
    debug_find_ranks(text, rank_triggers)
    # Создаем обратное отображение: символ -> стандартное обозначение
    reverse_mapping = {}
    for standard_rank, variants in rank_triggers.items():
        for variant in variants:
            reverse_mapping[variant.lower()] = standard_rank
    
    # Создаем regex pattern только для допустимых рангов
    all_variants = []
    for variants in rank_triggers.values():
        all_variants.extend(variants)
    
    # Экранируем специальные символы для regex
    escaped_variants = [re.escape(variant) for variant in all_variants]
    pattern = r'(\d+)\s*(' + '|'.join(escaped_variants) + r')'
    
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    found_ranks = []
    
    for number, rank_str in matches:
        # Пропускаем номиналы, начинающиеся с 0
        if number == "0":
            continue
            
        # Приводим к нижнему регистру для сравнения
        rank_lower = rank_str.lower()
        
        # Ищем соответствие в наших триггерах
        for variant, standard_rank in reverse_mapping.items():
            if variant == rank_lower:
                found_ranks.append(f"{number}{standard_rank}")
                break
    
    # Если ничего не найдено, возвращаем None
    if not found_ranks:
        return None
    
    # Считаем частоту встречаемости
    counter = Counter(found_ranks)
    most_common = counter.most_common(1)[0][0]
    
    return most_common


# Для отладки выведем все найденные номиналы
def debug_find_ranks(text, rank_triggers):
    reverse_mapping = {}
    for standard_rank, variants in rank_triggers.items():
        for variant in variants:
            reverse_mapping[variant.lower()] = standard_rank
    
    all_variants = []
    for variants in rank_triggers.values():
        all_variants.extend(variants)
    
    escaped_variants = [re.escape(variant) for variant in all_variants]
    pattern = r'(\d+)\s*(' + '|'.join(escaped_variants) + r')'
    
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    print("Найденные совпадения:")
    for number, rank_str in matches:
        # Пропускаем номиналы, начинающиеся с 0
        if number == "0":
            print(f"  Пропущено: '{number}{rank_str}' -> начинается с 0")
            continue
            
        rank_lower = rank_str.lower()
        matched_rank = None
        for variant, standard_rank in reverse_mapping.items():
            if variant == rank_lower:
                matched_rank = f"{number}{standard_rank}"
                break
        
        print(f"  '{number}{rank_str}' -> {matched_rank}")




@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.send_message(message.chat.id, f"Привет! В базе есть {last_card}! Введи число и получи информацию о карте!")
    
@bot.message_handler(content_types='text')
def send_card_info(message):
    logging.info(f"Got message from {message.from_user.id} -- {message.from_user.username} -- {message.text}")
    
    try:
        cid = int(message.text)
    except ValueError:
        bot.send_message(message.chat,id, "Некорректное число!")
        return
    
    if cid <= 0 or cid > last_card:
        bot.send_message(message.chat,id, "Некорректное число!")
        return
    
    try:
        card = [item for item in cards if item[0] == cid][0]
        
        
        # Достаем комментарии
        cursor.execute("SELECT text FROM comments WHERE card_id=?", (cid,))
        comments = cursor.fetchall()
        
        comments_text=""

        if comments:
            for text in comments:
                comments_text += f"{text[0]}\n"
            
        bot.send_photo(
            message.chat.id,
            photo=f"{card[2]}",
            caption=f"ID-карты: {card[0]}\nНазвание карты: {card[1]}\n\nПредположительная цена: `{find_most_common_rank(comments_text, rank_triggers)}`\n\nСсылка: https://mangabuff.ru/cards/{card[0]}/users"
        )

    except Exception as e:
        logging.error(f"Ошибка при получении карты {cid}: {e}")
        bot.send_message(
            message.chat.id,
            f"Такой карты нет в базе. Возможно, она была удалена.\nПроверьте сами: https://mangabuff.ru/cards/{cid}/users"
        )
    
    
bot.infinity_polling()
conn.close()