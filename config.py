import os
import base64
import tempfile
import contextlib
from pathlib import Path
from typing import Optional, Generator
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

# Download va operatsiyalar uchun asinxron timeout (soniyalarda)
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", 180))

def get_raw_cookies_content() -> Optional[str]:
    """
    Environment o'zgaruvchilaridan (base64 yoki raw) cookie matnini xavfsiz ajratib oladi.
    Render va boshqa bulut platformalarida multiline Netscape cookies base64 formatda
    saqlanishi eng ishonchli usuldir.
    """
    # 1. Base64 formatdagi cookielar
    for b64_var in ("YTDL_COOKIES_B64", "YOUTUBE_COOKIES_B64", "COOKIES_B64"):
        raw_b64 = os.getenv(b64_var)
        if raw_b64 and raw_b64.strip():
            clean_b64 = raw_b64.strip().replace("\n", "").replace("\r", "")
            missing_padding = len(clean_b64) % 4
            if missing_padding:
                clean_b64 += "=" * (4 - missing_padding)
            try:
                decoded = base64.b64decode(clean_b64).decode("utf-8", errors="ignore").strip()
                if decoded:
                    return decoded
            except Exception:
                pass

    # 2. Xom (raw) matn formatidagi cookielar
    for raw_var in ("YTDL_COOKIES", "YOUTUBE_COOKIES", "COOKIES_CONTENT", "INSTAGRAM_COOKIES"):
        raw_val = os.getenv(raw_var)
        if raw_val and raw_val.strip():
            return raw_val.strip()

    return None

@contextlib.contextmanager
def cookie_file_context() -> Generator[Optional[str], None, None]:
    """
    Xavfsiz vaqtinchalik cookie fayli kontekst menejeri.
    Agar env da base64 yoki raw cookie berilgan bo'lsa:
      - Faqat operatsiya davrida mavjud bo'lgan 0600 ruxsatli vaqtinchalik fayl yaratadi.
      - finally blokida faylni diskdan to'liq tozalaydi (Render resurslari xavfsizligi).
    Agar statik COOKIES_FILE yoki cookies.txt mavjud bo'lsa, o'shani uzatadi (o'chirmaydi).
    """
    # 1. Mavjud statik COOKIES_FILE ko'rsatilgan bo'lsa
    env_file = os.getenv("COOKIES_FILE")
    if env_file and os.path.exists(env_file):
        yield env_file
        return

    # 2. Mavjud mahalliy cookies.txt fayli bo'lsa
    local_path = BASE_DIR / "cookies.txt"
    if local_path.exists():
        yield str(local_path)
        return

    # 3. Env orqali uzatilgan cookie matni mavjud bo'lsa
    cookies_content = get_raw_cookies_content()
    if cookies_content:
        temp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix="_cookies.txt",
            prefix="ytdl_",
            delete=False,
            encoding="utf-8"
        )
        try:
            os.chmod(temp.name, 0o600)
            temp.write(cookies_content)
            temp.flush()
            temp.close()
            yield temp.name
        finally:
            if os.path.exists(temp.name):
                try:
                    os.remove(temp.name)
                except Exception:
                    pass
        return

    # 4. Cookie umuman mavjud bo'lmasa
    yield None

def get_cookie_file() -> Optional[str]:
    """
    Merosiy / orqaga muvofiqlik uchun funksiya.
    """
    env_file = os.getenv("COOKIES_FILE")
    if env_file and os.path.exists(env_file):
        return env_file

    local_path = BASE_DIR / "cookies.txt"
    if local_path.exists():
        return str(local_path)

    raw_cookies = get_raw_cookies_content()
    if raw_cookies and raw_cookies.strip():
        cookie_path = BASE_DIR / "cookies.txt"
        cookie_path.write_text(raw_cookies.strip(), encoding="utf-8")
        try:
            os.chmod(str(cookie_path), 0o600)
        except Exception:
            pass
        return str(cookie_path)

    return None
