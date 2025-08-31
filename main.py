from selenium import webdriver
from selenium_stealth import stealth
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from urllib.parse import urlparse
import json
import time
import logging
import re
import sqlite3

logging.basicConfig(filename="py_log.log",filemode="w", encoding="utf-8", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE_URL = "https://mangabuff.ru/"
TARGET_URL = "https://mangabuff.ru/cards/1/users"
COOKIES_FILE = "cookies.json"
LOGIN_URL = "https://mangabuff.ru/login"

import sqlite3

def init_db(db_name="cards.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # Таблица карт
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY,
        name TEXT
        image_url TEXT
    )
    """)
    
    # Таблица комментариев
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER,
        tag TEXT,
        user TEXT,
        date TEXT,
        text TEXT,
        FOREIGN KEY(card_id) REFERENCES cards(id)
    )
    """)
    
    conn.commit()
    return conn

def save_card_and_comments(conn, card_id: int, card_name: str, image_url: str, comments: list):
    cursor = conn.cursor()
    
    # Вставляем/обновляем карту
    cursor.execute("""
    INSERT OR REPLACE INTO cards (id, name, image_url) VALUES (?, ?, ?)
    """, (card_id, card_name, image_url))
    
    # Удалим старые комментарии для карты, чтобы не было дублей
    cursor.execute("DELETE FROM comments WHERE card_id = ?", (card_id,))
    
    # Добавляем комментарии
    for c in comments:
        cursor.execute("""
        INSERT INTO comments (card_id, tag, user, date, text)
        VALUES (?, ?, ?, ?, ?)
        """, (card_id, c["tag"], c["user"], c["date"], c["text"]))
    
    conn.commit()

def init_driver():
    logging.info("func: init_driver")
    options = webdriver.ChromeOptions()
    #options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    stealth(driver, platform="Alt Linux")
    return driver


def wait_for_login_and_save_cookies(required_names=None):
    logging.info("func: wait_for_login_and_save_cookies")
    driver = init_driver()
    try:
        driver.get(LOGIN_URL)
        print("Открыл страницу логина. Выполните вход вручную.")
        # Ждём реальный редирект на главную
        WebDriverWait(driver, 15).until_not(EC.presence_of_element_located(By.CLASS_NAME, "login-button"))
        print("Авторизация подтверждена, сохраняю куки...")

        cookies = driver.get_cookies()
        filtered_cookies = []
        
        for cookie in cookies:
            cookie_name = cookie.get('name', '')
            
            # Включаем только нужные имена (если указаны)
            if required_names and cookie_name not in required_names:
                continue
            
            filtered_cookies.append(cookie)
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered_cookies, f, indent=2, ensure_ascii=False)
        print(f"Куки сохранены: {len(cookies)} шт.")
        return filtered_cookies
    finally:
        driver.quit()


def load_cookies(path=COOKIES_FILE):
    logging.info("func: load_cookies")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        print(f"Загружено {len(cookies)} куки из файла")
        return cookies
    except FileNotFoundError:
        print("Файл с куки не найден")
        return []


def restore_cookies_and_open(driver, cookies: list, base_url: str, target_url: str):
    logging.info("func: restore_cookies_and_open")
    driver.get(base_url)

    for c in cookies:
        driver.add_cookie(c)
        
    # Применяем куки
    driver.refresh()
    # Переходим к целевой странице после применения
    driver.get(target_url)



def parse_comment_block(raw_text: str) -> dict:
    """
    Парсим комментарий из блока текста в структурированный словарь.
    Возвращает {"tag": "...", "user": "...", "date": "...", "text": "..."}
    """
    parts = raw_text.split("\n")

    # Минимальная защита от пустого текста
    if len(parts) < 5:
        return {"tag": "", "user": "", "date": "", "text": raw_text.strip()}

    # Если первая строка — [TAG]
    if parts[0].startswith("[") and parts[0].endswith("]"):
        tag = parts[0]
        user = parts[1]
        date = parts[2]
        # после даты идёт "0", затем комментарий и "Ответить"
        comment_text = "\n".join(parts[4:-1]).strip()
    else:
        tag = ""
        user = parts[0]
        date = parts[1]
        comment_text = "\n".join(parts[3:-1]).strip()

    return {
        "tag": tag,
        "user": user,
        "date": date,
        "text": comment_text
    }

def main():

    logging.info("func: main")
    conn = init_db("cards.db")
    cookies = load_cookies(COOKIES_FILE)
    if not cookies:
        cookies = wait_for_login_and_save_cookies(required_names=["mangabuff_session", "XSRF-TOKEN"])

    driver = init_driver()
    try:
        restore_cookies_and_open(driver, cookies, BASE_URL, TARGET_URL)
        # Дайте странице прогрузиться, если нужно
        WebDriverWait(driver, 10)
        time.sleep(2)
        print("Страница открыта с восстановленной сессией.")

        for i in range(1,280921+1):
            page = f"https://mangabuff.ru/cards/{i}/users"
            logging.info(f"Openning {page}")
            driver.get(page)
            try:
                card_name = driver.title[22:]
                logging.info(f"Название карты: {card_name}")
                
                
                logging.info(f"Получены комментарии")
                
                img_elem = driver.find_element(By.CLASS_NAME, "card-show__image")
                img_src = img_elem.get_attribute("src")
                img_url = img_src if img_src.startswith("http") else "https://mangabuff.ru" + img_src
                
                comment_elements = driver.find_elements(By.CLASS_NAME, "comments__item")
                comments_raw = [el.text for el in comment_elements]
                comments_structured = [parse_comment_block(c) for c in comments_raw]
                
                try:
                    save_card_and_comments(conn, i, card_name, img_url, comments_structured)
                    logging.info(f"Карта была добавлена в БД")
                except Exception as e:
                    logging.error(f"Какая то ошибка! Возможно карта удалена... {e}")
            finally:
                time.sleep(1)
        
    finally:
        conn.close()
        driver.quit()


if __name__ == "__main__":
    main()
    
