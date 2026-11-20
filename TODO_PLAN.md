# TODO_PLAN: YouTube Resilient Architecture on Render & Local

Goal: Fix YouTube video downloading when deployed on Render cloud environment (where datacenter IP bot detection / 403 blocks occur) while maintaining clean local behavior, zero resource leaks on Render free tier, and full backward compatibility.

---

## Bosqichlar:

- [x] **1-bosqich: Cookie boshqaruvi va Render muhit konfiguratsiyasi (`config.py`)**
  - [x] `YTDL_COOKIES_B64`, `YTDL_COOKIES`, `YOUTUBE_COOKIES_B64`, `YOUTUBE_COOKIES`, `INSTAGRAM_COOKIES` ni xavfsiz o'qish
  - [x] Base64 dekodlash (padding va encoding xatolarisiz)
  - [x] Xavfsiz vaqtinchalik cookie fayli (0600 permissions) yaratish va `finally` da avtomatik tozalash (`cookie_file_context`)
  - [x] `.env.example` va `render.yaml` ga yangi cookie o'zgaruvchilarini hujjatlashtirish

- [x] **2-bosqich: Diagnostika, xatoliklarni tasniflash va Telegram xabarlari (`downloader.py`)**
  - [x] `classify_error()`: Bot-detection/403, Timeout, Yosh chegarasi/Unavailable, Fayl hajmi limitlarini aniq ajratish
  - [x] Har bir holat uchun tushunarli, yo'naltiruvchi Telegram xabarlari (`format_user_error`)
  - [x] Har bir urinish va xatolik uchun strukturalangan loglar (`logger.info`, `logger.warning`, `logger.error`)

- [x] **3-bosqich: YouTube ko'p bosqichli Fallback va Bulut yt-dlp strategiyasi (`downloader.py`)**
  - [x] Render 512MB RAM uchun mos formatlar (og'ir 1080p/4K o'rniga tezkor 720p/480p/360p pre-muxed format 18/22)
  - [x] YouTube uchun ko'p pog'onali strategiya (Tier 1: `ios`/`android`, Tier 2: `tv`/`mweb`, Tier 3: format 18 fallback, Tier 4: secondary hook interface)
  - [x] Audio uchun ham xuddi shunday YouTube fallback (to'g'ridan-to'g'ri audio -> tv audio -> video-to-mp3)
  - [x] Tarmoq timeoutlari (`socket_timeout=15`, `retries=3`)

- [x] **4-bosqich: Resurslar xavfsizligi va qat'iy tozalash (`bot.py` & `downloader.py`)**
  - [x] Barcha oraliq fayllarni (`.part`, `.ytdl`, `.temp.*`, `_tempvid.*`) har qanday xatolikda `finally` blokida 100% tozalash
  - [x] Telegram yuklashdan oldin va keyin qat'iy 50MB hajm nazorati
  - [x] Bot darajasida asinxron timeout nazorati (`asyncio.wait_for`)

- [x] **5-bosqich: Testlash va Verifikatsiya (Mock unit testlar + Real testlar)**
  - [x] `test_resilient_downloader.py`: Success, YouTube 403 block + fallback, Cleanup on error, Timeout & Size guard unit testlari (6/6 passed)
  - [x] Mavjud `test_suite.py` integratsion testlarini tekshirish (7/7 passed)
  - [x] Sintaksis va lint tekshiruvlari (py_compile 100% clean)
