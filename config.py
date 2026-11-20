import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# .env faylini yuklash
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DOWNLOAD_DIR = BASE_DIR / os.getenv("DOWNLOAD_DIR", "downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 50MB Telegram limiti
MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", 50 * 1024 * 1024))

# Celeron va HDD uchun qat'iy parallel yuklash chegarasi (max 2)
MAX_CONCURRENT_DOWNLOADS = 2

# Admin ID (Telegram user ID)
ADMIN_ID = int(os.getenv("ADMIN_ID", "8430493961"))

def get_cookie_file() -> Optional[str]:
    """
    Instagram va boshqa platformalar uchun cookie faylini aniqlaydi.
    Render.com yoki bulutli xizmatlarda INSTAGRAM_COOKIES env o'zgaruvchisi berilsa,
    uni avtomatik faylga aylantiradi.
    """
    raw_cookies = (
        os.getenv("YOUTUBE_COOKIES")
        or os.getenv("INSTAGRAM_COOKIES")
        or os.getenv("COOKIES_CONTENT")
    )
    if raw_cookies and raw_cookies.strip():
        cookie_path = BASE_DIR / "cookies.txt"
        cookie_path.write_text(raw_cookies.strip(), encoding="utf-8")
        return str(cookie_path)
    
    env_file = os.getenv("COOKIES_FILE")
    if env_file and os.path.exists(env_file):
        return env_file
        
    local_path = BASE_DIR / "cookies.txt"
    if local_path.exists():
        return str(local_path)
        
    return None

