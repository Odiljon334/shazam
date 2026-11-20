#!/usr/bin/env bash
# Chaqqon Media Downloader Bot Run Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "⚠️ .env fayli yaratildi. Iltimos, unga o'zingizning BOT_TOKEN ingizni kiriting!"
    fi
fi

if [ ! -d "venv" ]; then
    echo "⚙️ Virtual environment yaratilmoqda..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
fi

echo "🚀 Chaqqon Media Downloader Bot ishga tushirilmoqda..."
exec ./venv/bin/python3 bot.py
