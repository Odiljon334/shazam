"""
MTProto Uploader — Telegram 2GB Limit Kengaytmasi
Rasmiy HTTP Bot API-ning 50MB chegarasidan o'tib, Telegram MTProto protokoli
orqali 2000 MB (2 GB) gacha bo'lgan videolarni foydalanuvchiga to'g'ridan-to'g'ri yetkazadi.
"""

import os
import asyncio
import logging
from typing import Optional
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio
import config

logger = logging.getLogger("chaqqon_bot.mtproto")

_client: Optional[TelegramClient] = None
_client_lock = asyncio.Lock()


async def get_mtproto_client() -> Optional[TelegramClient]:
    """Telethon MTProto bot klientini xavfsiz initsializatsiya qiladi."""
    global _client
    if not config.API_ID or not config.API_HASH or not config.BOT_TOKEN:
        logger.warning("MTProto: API_ID, API_HASH yoki BOT_TOKEN mavjud emas.")
        return None

    async with _client_lock:
        if _client is None or not _client.is_connected():
            session_file = str(config.DOWNLOAD_DIR / "chaqqon_mtproto_bot")
            _client = TelegramClient(session_file, config.API_ID, config.API_HASH)
            await _client.start(bot_token=config.BOT_TOKEN)
            logger.info("✅ Telegram MTProto ulandi: 2000 MB (2 GB) yuklash limiti faol.")
        return _client


async def send_large_video(
    chat_id: int,
    file_path: str,
    caption: str = "",
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[int] = None,
) -> bool:
    """50MB dan 2000MB gacha bo'lgan videolarni MTProto orqali yuborish."""
    client = await get_mtproto_client()
    if not client:
        raise RuntimeError("MTProto klienti ishga tushmadi")

    filesize_mb = os.path.getsize(file_path) / (1024 * 1024)
    logger.info(f"MTProto: {filesize_mb:.1f}MB hajmdagi video foydalanuvchiga yuborilmoqda (Chat: {chat_id})...")

    attrs = [
        DocumentAttributeVideo(
            duration=int(duration or 0),
            w=int(width or 0),
            h=int(height or 0),
            supports_streaming=True,
        )
    ]

    await client.send_file(
        entity=chat_id,
        file=file_path,
        caption=caption,
        parse_mode="html",
        attributes=attrs,
        supports_streaming=True,
    )
    logger.info("MTProto: Video muvaffaqiyatli yetkazildi.")
    return True


async def send_large_audio(
    chat_id: int,
    file_path: str,
    title: str = "Audio",
    performer: str = "Chaqqon Robot",
    duration: Optional[int] = None,
) -> bool:
    """50MB dan katta bo'lgan MP3 / Audio fayllarni MTProto orqali yuborish."""
    client = await get_mtproto_client()
    if not client:
        raise RuntimeError("MTProto klienti ishga tushmadi")

    filesize_mb = os.path.getsize(file_path) / (1024 * 1024)
    logger.info(f"MTProto: {filesize_mb:.1f}MB hajmdagi audio foydalanuvchiga yuborilmoqda...")

    attrs = [
        DocumentAttributeAudio(
            duration=int(duration or 0),
            title=title,
            performer=performer,
        )
    ]

    await client.send_file(
        entity=chat_id,
        file=file_path,
        caption=f"🎵 <b>{title}</b>\n👤 <i>{performer}</i>\n⚡️ <b>@chaqqon_robot</b>",
        parse_mode="html",
        attributes=attrs,
    )
    logger.info("MTProto: Audio muvaffaqiyatli yetkazildi.")
    return True
