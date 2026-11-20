# Python 3.11 Slim rasmi
FROM python:3.11-slim

# Tizim paketlarini yangilash, FFmpeg va Node.js (YouTube JS challenge uchun) o'rnatish
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bog'liqliklarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Loyiha kodlarini ko'chirish
COPY . .

# Render kutadigan standart port
ENV PORT=10000
EXPOSE 10000

# Bot va healthcheck serverini ishga tushirish
CMD ["python", "bot.py"]
