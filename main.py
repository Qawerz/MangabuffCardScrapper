from selenium import webdriver
from selenium_stealth import stealth
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from urllib.parse import urlparse
import json
import time
import logging
import re
import sqlite3
from tqdm import tqdm

import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

logging.basicConfig(
    filename="py_log.log",
    filemode="w",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

BASE_URL = "https://mangabuff.ru/"
COOKIES_FILE = "cookies.json"
LOGIN_URL = "https://mangabuff.ru/login"


def init_db(db_name="cards.db"):
    """
    Initialize SQLite database and create tables if they do not exist.
    Returns:
        sqlite3.Connection: database connection object
    """
    logging.info("Initializing database...")
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY,
        name TEXT,
        image_url TEXT
    )
    """)
    
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
    logging.info("Database initialized.")
    return conn


def save_card_and_comments(conn, card_id: int, card_name: str, image_url: str, comments: list):
    """
    Save or update a card and its comments in the database.
    """
    logging.info(f"Saving card ID {card_id} - '{card_name}' with {len(comments)} comments...")
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT OR REPLACE INTO cards (id, name, image_url) VALUES (?, ?, ?)
    """, (card_id, card_name, image_url))
    
    cursor.execute("DELETE FROM comments WHERE card_id = ?", (card_id,))
    
    for c in comments:
        cursor.execute("""
        INSERT INTO comments (card_id, tag, user, date, text)
        VALUES (?, ?, ?, ?, ?)
        """, (card_id, c["tag"], c["user"], c["date"], c["text"]))
    
    conn.commit()
    logging.debug(f"Card ID {card_id} saved successfully.")


def init_driver():
    """
    Initialize Selenium WebDriver with stealth options.
    Returns:
        webdriver.Chrome
    """
    logging.info("Initializing Selenium driver...")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--log-level=3")
    options.add_argument("--silent")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    service = Service(log_path="NUL")
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, platform="Alt Linux")
    logging.info("Driver initialized.")
    return driver


def wait_for_login_and_save_cookies(required_names=None):
    """
    Open the login page, wait for manual login, and save cookies.
    """
    logging.info("Waiting for manual login to save cookies...")
    driver = init_driver()
    try:
        driver.get(LOGIN_URL)
        print("Please log in manually...")
        WebDriverWait(driver, 15).until_not(EC.presence_of_element_located((By.CLASS_NAME, "login-button")))
        logging.info("Login detected.")
        cookies = driver.get_cookies()
        filtered_cookies = []

        for cookie in cookies:
            if required_names and cookie.get('name') not in required_names:
                continue
            filtered_cookies.append(cookie)
        
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered_cookies, f, indent=2, ensure_ascii=False)
        
        logging.info(f"{len(filtered_cookies)} cookies saved to file.")
        return filtered_cookies
    finally:
        driver.quit()


def load_cookies(path=COOKIES_FILE):
    """
    Load cookies from a file.
    """
    logging.info(f"Loading cookies from {path}...")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        logging.info(f"{len(cookies)} cookies loaded.")
        return cookies
    except FileNotFoundError:
        logging.warning("Cookie file not found.")
        return []


def restore_cookies_and_open(driver, cookies: list, base_url: str):
    """
    Restore cookies in Selenium session and open target page.
    """
    logging.info("Restoring cookies in browser session...")
    driver.get(base_url)

    for c in cookies:
        driver.add_cookie(c)

    driver.refresh()


def parse_comment_block(raw_text: str) -> dict:
    """
    Parse raw comment text into structured dictionary.
    """
    parts = raw_text.split("\n")
    if len(parts) < 5:
        return {"tag": "", "user": "", "date": "", "text": raw_text.strip()}

    if parts[0].startswith("[") and parts[0].endswith("]"):
        tag = parts[0]
        user = parts[1]
        date = parts[2]
        comment_text = "\n".join(parts[4:-1]).strip()
    else:
        tag = ""
        user = parts[0]
        date = parts[1]
        comment_text = "\n".join(parts[3:-1]).strip()

    return {"tag": tag, "user": user, "date": date, "text": comment_text}


def main():
    """
    Main scraping loop:
    - Initialize DB
    - Load or acquire cookies
    - Open Selenium driver
    - Iterate over cards, scrape name, image, comments
    - Save data to SQLite
    """
    logging.info("Starting main scraping process...")
    conn = init_db("cards.db")
    cookies = load_cookies(COOKIES_FILE)
    if not cookies:
        cookies = wait_for_login_and_save_cookies(required_names=["mangabuff_session", "XSRF-TOKEN"])

    driver = init_driver()
    try:
        restore_cookies_and_open(driver, cookies, BASE_URL)
        time.sleep(2)

        total_cards = 280921

        for i in tqdm(range(877, total_cards + 1), desc="Processing cards"):
            page = f"https://mangabuff.ru/cards/{i}/users"
            logging.info(f"Opening page {page}")
            driver.get(page)
            
            try:
                card_name = driver.title[22:]
                logging.info(f"Processing card ID {i}: {card_name}")

                # Try to get image and comments; skip if element not found (404)
                try:
                    img_elem = driver.find_element(By.CLASS_NAME, "card-show__image")
                    img_src = img_elem.get_attribute("src")
                    img_url = img_src if img_src.startswith("http") else "https://mangabuff.ru" + img_src

                    comment_elements = driver.find_elements(By.CLASS_NAME, "comments__item")
                    comments_raw = [el.text for el in comment_elements]
                    comments_structured = [parse_comment_block(c) for c in comments_raw]

                    save_card_and_comments(conn, i, card_name, img_url, comments_structured)
                    logging.info(f"Card ID {i} saved successfully with {len(comments_structured)} comments.")

                except Exception as e:
                    logging.warning(f"Card ID {i} may be deleted or page missing (404). Skipping. Error: {e}")
                    continue  # go to next card

            except Exception as e_outer:
                logging.error(f"Unexpected error processing card ID {i}: {e_outer}")
                continue  # skip to next card

            finally:
                time.sleep(1)  # polite delay
    
    finally:
        conn.close()
        driver.quit()
        logging.info("Scraping finished. Database connection closed and driver quit.")


if __name__ == "__main__":
    main()
