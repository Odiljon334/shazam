# ⚡️ Shazam — Chaqqon Media Downloader Telegram Bot

Instagram, TikTok, YouTube, Pinterest va boshqa platformalardan video, musiqa (MP3) va nomlarini tezkor, ortiqcha reklamalarsiz yuklab beruvchi yengil va mustahkam Telegram bot.

Render.com (Free Web Service) va Docker uchun 100% moslashtirilgan.

---

## 🚀 Imkoniyatlari

- **Platformalar**: Instagram (Reels, Post, IGTV), TikTok (suv belgisiz video va musiqa), YouTube (Shorts va videolar), Pinterest, Twitter/X, Facebook.
- **Video & MP3**:
  - `🎬 Video yuklash`: Eng optimal formatda (Telegram 50MB chegarasiga mos).
  - `🎵 Musiqa (MP3)`: Videodan yuqori sifatli audio (MP3 192kbps) ajratib olish va ijrochi/nomi bilan yuborish.
- **Render.com ga moslashtirilgan**:
  - Maxsus aiohttp healthcheck serveri `$PORT` orqali ishlaydi (Render bepul rejasida bot uxlab qolmaydi va deploy xatosiz o'tadi).
  - Dockerfile orqali FFmpeg to'liq avtomat o'rnatiladi.
- **Disk va CPU Tejamkorligi**:
  - Bir vaqtning o'zida maksimal 2 ta yuklash (asyncio Semaphore).
  - Fayl foydalanuvchiga yuborilishi bilan avtomatik o'chiriladi (`auto-cleanup`).

---

## 🌐 Render.com ga O'rnatish (1-klikda Deploy)

1. [Render.com](https://render.com) ga kiring va GitHub akkauntingiz bilan kiring.
2. **New +** -> **Web Service** ni tanlang.
3. Ushbu **shazam** repositoriyasini tanlang.
4. Render avtomatik ravishda **Docker** muhitini aniqlaydi.
5. **Environment Variables** (Muhit o'zgaruvchilari) bo'limiga quyidagilarni kiriting:
   - `BOT_TOKEN`: Sizning Telegram bot tokeningiz (masalan: `9257918829:AAEO...`)
   - `DOWNLOAD_DIR`: `downloads`
   - `MAX_FILE_SIZE_BYTES`: `52428800`
6. **Create Web Service** tugmasini bosing! Bot bir necha daqiqada ishga tushadi.

---

## 💻 Mahalliy Server yoki Kompyuterda Ishga Tushirish

### 1. Tokenni kiritish
```bash
cp .env.example .env
nano .env
```
`BOT_TOKEN=` qatoriga o'zingizning bot tokeningizni yozing.

### 2. Ishga tushirish
```bash
./run.sh
```

---

## 📁 Loyiha Tuzilmasi

```
shazam/
├── bot.py               # Aiogram 3 va Render aiohttp serveri
├── downloader.py        # yt-dlp va ffmpeg media downloader dvigateli
├── config.py            # Konfiguratsiya va limitlar
├── requirements.txt     # Python paketlari
├── Dockerfile           # Render/Docker uchun konteyner konfiguratsiyasi
├── render.yaml          # Render Blueprint avtomatik deploy fayli
├── run.sh               # Mahalliy ishga tushirish skripti
├── chaqqon_bot.service  # Systemd service (Linux VPS uchun)
├── .env.example         # Muhit o'zgaruvchilari namunasi
└── downloads/           # Vaqtinchalik fayllar papkasi (avtomatik tozalanadi)
```
