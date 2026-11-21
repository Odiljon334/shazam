import os
import sys
import time
import uuid
import hashlib
import logging
import asyncio
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    CallbackQuery,
    Message,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import downloader
import database
import mtproto_uploader
import proxy_manager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chaqqon_bot")

# ---------------------------------------------------------------------------
# Global holat
# ---------------------------------------------------------------------------
START_TIME = datetime.now()
maintenance_mode: bool = False          # texnik rejim (faqat admin kiradi)
download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

url_cache: dict[str, dict] = {}

# Admin FSM holatlari  {admin_id: state_string}
admin_states: dict[int, str] = {}

# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------

def cache_url(url: str, title: str = "") -> str:
    url_id = hashlib.md5(url.encode()).hexdigest()[:10]
    url_cache[url_id] = {"url": url, "title": title, "time": time.time()}
    now = time.time()
    for k in list(url_cache.keys()):
        if now - url_cache[k]["time"] > 7200:
            url_cache.pop(k, None)
    return url_id


def get_cached_url(url_id: str) -> str | None:
    data = url_cache.get(url_id)
    return data["url"] if data else None


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


def detect_platform(url: str) -> str:
    u = url.lower()
    if "instagram" in u or "instagr.am" in u:
        return "Instagram"
    if "tiktok" in u:
        return "TikTok"
    if "youtube" in u or "youtu.be" in u:
        return "YouTube"
    if "pinterest" in u or "pin.it" in u:
        return "Pinterest"
    if "facebook" in u or "fb.watch" in u or "fb.com" in u:
        return "Facebook"
    if "snapchat" in u:
        return "Snapchat"
    if "t.me" in u or "telegram" in u:
        return "Telegram"
    return "Boshqa"


def uptime_str() -> str:
    delta = datetime.now() - START_TIME
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}s {m}d {s}son"


bot: Bot | None = None


def get_bot() -> Bot:
    global bot
    if bot is None:
        if not config.BOT_TOKEN:
            raise ValueError("BOT_TOKEN aniqlanmadi!")
        bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return bot


dp = Dispatcher()

# ===========================================================================
# ADMIN PANEL — klaviaturalar
# ===========================================================================

def admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stats"),
            InlineKeyboardButton(text="⏱ Uptime", callback_data="adm:uptime"),
        ],
        [
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="adm:users"),
            InlineKeyboardButton(text="📋 So'nggi faollik", callback_data="adm:logs"),
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast", callback_data="adm:broadcast"),
            InlineKeyboardButton(text="🔍 User izlash", callback_data="adm:search_user"),
        ],
        [
            InlineKeyboardButton(text="🚫 Ban", callback_data="adm:ban"),
            InlineKeyboardButton(text="✅ Unban", callback_data="adm:unban"),
        ],
        [
            InlineKeyboardButton(
                text="🔧 Texnik rejim: " + ("🟢 YOQILGAN" if maintenance_mode else "🔴 O'CHIRILGAN"),
                callback_data="adm:maintenance",
            ),
        ],
        [
            InlineKeyboardButton(text="🗑 Downloads tozalash", callback_data="adm:clear_dl"),
            InlineKeyboardButton(text="♻️ Keshni tozalash", callback_data="adm:clear_cache"),
        ],
    ])


def back_to_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Admin panelga qaytish", callback_data="adm:back")]
    ])

# ===========================================================================
# ODDIY FOYDALANUVCHI BUYRUQLARI
# ===========================================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await database.register_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    text = (
        "✨ <b>Assalomu alaykum, aziz do'stim! Chaqqon Bot'ga xush kelibsiz!</b> 🚀\n\n"
        "Bu yerda siz ijtimoiy tarmoqlardagi istalgan video, rasm va musiqalarni "
        "<b>bir zumda, suv belgisiz va eng yuqori sifatda</b> yuklab olasiz! 😍\n\n"
        "<b>🔥 Bot orqali quyidagilarni yuklab olishingiz mumkin:</b>\n\n"
        "• 📸 <b>Instagram</b> — post, stories, reels;\n"
        "• ▶️ <b>YouTube</b> — video, shorts, audio (MP3);\n"
        "• 🎵 <b>Tik Tok</b> — suv belgisiz video;\n"
        "• 📘 <b>Facebook</b> — reels, video, rasm;\n"
        "• 📌 <b>Pinterest</b> — rasm va video;\n"
        "• 👻 <b>Snapchat</b> — rasm va video;\n"
        "• ✈️ <b>Telegram</b> — hikoya seen va ochiq postlar.\n\n"
        "💡 <i>Shunchaki havolani yuboring, qolgan barcha mo'jizani menga qo'yib bering! ⚡️</i>"
    )
    await message.answer(text)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await database.register_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    text = (
        "ℹ️ <b>Yordam &amp; Ko'rsatma:</b>\n\n"
        "1. Istalgan ijtimoiy tarmoqdan havola oling.\n"
        "2. Havolani to'g'ridan-to'g'ri botga yuboring.\n"
        "3. Bot bir necha soniyada mediangizni a'lo sifatda taqdim etadi!\n\n"
        "🎵 <i>Har bir videoning ostidagi maxsus tugma orqali uning toza MP3 musiqasini ham olishingiz mumkin!</i>"
    )
    await message.answer(text)

# ===========================================================================
# ADMIN BUYRUQLARI
# ===========================================================================

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "👑 <b>Admin boshqaruv paneli</b>\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=admin_main_kb(),
    )


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    stats = await database.get_stats()
    text = (
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['total_users']}</b>\n"
        f"🟢 Bugun aktiv: <b>{stats['active_today']}</b>\n"
        f"🚫 Ban qilingan: <b>{stats['banned_count']}</b>\n\n"
        f"📥 Jami yuklamalar: <b>{stats['total_downloads']}</b>\n"
        f"📅 Bugun yuklamalar: <b>{stats['downloads_today']}</b>\n"
        f"❌ Muvaffaqiyatsiz: <b>{stats['failed_downloads']}</b>\n\n"
        f"⏱ Uptime: <b>{uptime_str()}</b>"
    )
    await message.answer(text, reply_markup=back_to_admin_kb())


@dp.message(Command("broadcast"))
async def cmd_broadcast_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_states[message.from_user.id] = "awaiting_broadcast"
    await message.answer(
        "📢 <b>Broadcast xabari</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni kiriting.\n"
        "Bekor qilish uchun: /cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:cancel_state")]
        ]),
    )


@dp.message(Command("ban"))
async def cmd_ban_direct(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("ℹ️ Foydalanish: <code>/ban &lt;user_id&gt;</code>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await message.answer("❌ Noto'g'ri ID.")
        return
    ok = await database.ban_user(uid)
    if ok:
        await message.answer(f"✅ Foydalanuvchi <b>{uid}</b> bloklandi.")
        try:
            await get_bot().send_message(uid, "🚫 Siz botdan bloklangansiz.")
        except Exception:
            pass
    else:
        await message.answer(f"⚠️ Foydalanuvchi <b>{uid}</b> bazada topilmadi.")


@dp.message(Command("unban"))
async def cmd_unban_direct(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("ℹ️ Foydalanish: <code>/unban &lt;user_id&gt;</code>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await message.answer("❌ Noto'g'ri ID.")
        return
    ok = await database.unban_user(uid)
    if ok:
        await message.answer(f"✅ Foydalanuvchi <b>{uid}</b> blokdan chiqarildi.")
        try:
            await get_bot().send_message(uid, "✅ Blokingiz olib tashlandi! Botdan foydalanishingiz mumkin.")
        except Exception:
            pass
    else:
        await message.answer(f"⚠️ Foydalanuvchi <b>{uid}</b> bazada topilmadi.")


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.from_user.id in admin_states:
        admin_states.pop(message.from_user.id, None)
        await message.answer("✅ Amal bekor qilindi.", reply_markup=admin_main_kb())
    else:
        await message.answer("⚠️ Bekor qilinadigan amal yo'q.")

# ===========================================================================
# ADMIN CALLBACK HANDLERLAR
# ===========================================================================

@dp.callback_query(F.data.startswith("adm:"))
async def admin_callback(callback: CallbackQuery):
    global maintenance_mode

    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]
    await callback.answer()

    # --- Statistika ---
    if action == "stats":
        stats = await database.get_stats()
        text = (
            "📊 <b>Bot statistikasi</b>\n\n"
            f"👥 Jami foydalanuvchilar: <b>{stats['total_users']}</b>\n"
            f"🟢 Bugun aktiv: <b>{stats['active_today']}</b>\n"
            f"🚫 Ban qilingan: <b>{stats['banned_count']}</b>\n\n"
            f"📥 Jami yuklamalar: <b>{stats['total_downloads']}</b>\n"
            f"📅 Bugun yuklamalar: <b>{stats['downloads_today']}</b>\n"
            f"❌ Muvaffaqiyatsiz: <b>{stats['failed_downloads']}</b>\n\n"
            f"⏱ Uptime: <b>{uptime_str()}</b>"
        )
        await callback.message.edit_text(text, reply_markup=back_to_admin_kb())

    # --- Uptime ---
    elif action == "uptime":
        text = (
            f"⏱ <b>Bot uptime ma'lumoti</b>\n\n"
            f"🕐 Ishga tushgan vaqt: <b>{START_TIME.strftime('%d.%m.%Y %H:%M:%S')}</b>\n"
            f"⏳ Ish vaqti: <b>{uptime_str()}</b>\n\n"
            f"💾 URL kesh: <b>{len(url_cache)}</b> ta yozuv\n"
            f"🔧 Texnik rejim: <b>{'Yoqilgan' if maintenance_mode else 'Ochirilgan'}</b>"
        )
        await callback.message.edit_text(text, reply_markup=back_to_admin_kb())

    # --- Foydalanuvchilar ---
    elif action == "users":
        rows = await database.get_recent_users(15)
        if not rows:
            await callback.message.edit_text("👥 Hali foydalanuvchi yo'q.", reply_markup=back_to_admin_kb())
            return
        lines = ["👥 <b>So'nggi 15 faol foydalanuvchi:</b>\n"]
        for r in rows:
            uid, uname, fname, first_seen, last_active, banned, dl_cnt = r
            ban_icon = "🚫" if banned else "✅"
            uname_str = f"@{uname}" if uname else f"ID:{uid}"
            lines.append(
                f"{ban_icon} <b>{fname or uname_str}</b> ({uname_str})\n"
                f"   📥 {dl_cnt} yuklama | 🕐 {last_active[:10]}"
            )
        await callback.message.edit_text("\n".join(lines), reply_markup=back_to_admin_kb())

    # --- So'nggi faollik ---
    elif action == "logs":
        rows = await database.get_recent_downloads(10)
        if not rows:
            await callback.message.edit_text("📋 Hali yuklama logi yo'q.", reply_markup=back_to_admin_kb())
            return
        lines = ["📋 <b>So'nggi 10 ta yuklama:</b>\n"]
        for r in rows:
            uid, uname, fname, platform, mtype, success, ts = r
            icon = "✅" if success else "❌"
            user_str = f"@{uname}" if uname else str(uid)
            lines.append(
                f"{icon} {platform or '?'} [{mtype or '?'}]\n"
                f"   👤 {user_str} | 🕐 {ts[11:16] if ts else '?'}"
            )
        await callback.message.edit_text("\n".join(lines), reply_markup=back_to_admin_kb())

    # --- Broadcast boshlash ---
    elif action == "broadcast":
        admin_states[callback.from_user.id] = "awaiting_broadcast"
        await callback.message.edit_text(
            "📢 <b>Broadcast xabari</b>\n\n"
            "Barcha foydalanuvchilarga yuboriladigan xabarni kiriting.\n"
            "(HTML formatlash ishlaydi)\n\n"
            "Bekor qilish uchun tugmani bosing:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:cancel_state")]
            ]),
        )

    # --- Foydalanuvchi izlash ---
    elif action == "search_user":
        admin_states[callback.from_user.id] = "awaiting_search_user"
        await callback.message.edit_text(
            "🔍 <b>Foydalanuvchi izlash</b>\n\n"
            "Foydalanuvchi Telegram ID sini kiriting:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:cancel_state")]
            ]),
        )

    # --- Ban ---
    elif action == "ban":
        admin_states[callback.from_user.id] = "awaiting_ban"
        await callback.message.edit_text(
            "🚫 <b>Foydalanuvchini bloklash</b>\n\n"
            "Ban qilinishi kerak bo'lgan foydalanuvchi Telegram ID sini kiriting:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:cancel_state")]
            ]),
        )

    # --- Unban ---
    elif action == "unban":
        admin_states[callback.from_user.id] = "awaiting_unban"
        await callback.message.edit_text(
            "✅ <b>Foydalanuvchidan ban olish</b>\n\n"
            "Blokdan chiqarilishi kerak bo'lgan foydalanuvchi Telegram ID sini kiriting:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:cancel_state")]
            ]),
        )

    # --- Texnik rejim ---
    elif action == "maintenance":
        maintenance_mode = not maintenance_mode
        status = "🟢 YOQILDI" if maintenance_mode else "🔴 O'CHIRILDI"
        await callback.message.edit_text(
            f"🔧 <b>Texnik rejim {status}</b>\n\n"
            + (
                "Bot hozir faqat admin uchun ishlaydi.\n"
                "Oddiy foydalanuvchilar texnik ishlarga doir xabar oladi."
                if maintenance_mode
                else "Bot endi barcha foydalanuvchilar uchun ishlaydi."
            ),
            reply_markup=back_to_admin_kb(),
        )

    # --- Downloads papkasini tozalash ---
    elif action == "clear_dl":
        dl_dir = config.DOWNLOAD_DIR
        count = 0
        total_mb = 0
        for f in dl_dir.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                total_mb += f.stat().st_size
                f.unlink()
                count += 1
        await callback.message.edit_text(
            f"🗑 <b>Downloads papkasi tozalandi</b>\n\n"
            f"🗂 O'chirilgan fayllar: <b>{count}</b>\n"
            f"💾 Bo'shatilgan joy: <b>{total_mb / (1024*1024):.1f} MB</b>",
            reply_markup=back_to_admin_kb(),
        )

    # --- URL keshni tozalash ---
    elif action == "clear_cache":
        count = len(url_cache)
        url_cache.clear()
        await callback.message.edit_text(
            f"♻️ <b>URL kesh tozalandi</b>\n\n"
            f"🗂 O'chirilgan yozuvlar: <b>{count}</b>",
            reply_markup=back_to_admin_kb(),
        )

    # --- Holatni bekor qilish ---
    elif action == "cancel_state":
        admin_states.pop(callback.from_user.id, None)
        await callback.message.edit_text(
            "✅ Amal bekor qilindi.\n\n"
            "👑 <b>Admin boshqaruv paneli</b>\n\nQuyidagi tugmalardan birini tanlang:",
            reply_markup=admin_main_kb(),
        )

    # --- Panelga qaytish ---
    elif action == "back":
        await callback.message.edit_text(
            "👑 <b>Admin boshqaruv paneli</b>\n\nQuyidagi tugmalardan birini tanlang:",
            reply_markup=admin_main_kb(),
        )

    # --- Broadcast tasdiqlash ---
    elif action.startswith("confirm_broadcast:"):
        # Bu yerda broadcast amalga oshiriladi
        await _do_broadcast(callback)

    elif action == "cancel_broadcast":
        admin_states.pop(callback.from_user.id, None)
        await callback.message.edit_text(
            "❌ Broadcast bekor qilindi.",
            reply_markup=back_to_admin_kb(),
        )


async def _do_broadcast(callback: CallbackQuery):
    """Broadcast xabarini barcha foydalanuvchilarga yuboradi."""
    btext = callback.message.text or ""
    # Xabar matnini extractdan olish (keyingi xabar orqali keladi)
    # Bu oddiy yondashuv: admin state dan olish
    # Amalda broadcast_text ni admin_states da saqlaymiz
    broadcast_text = admin_states.pop(callback.from_user.id, None)
    if not broadcast_text or broadcast_text == "awaiting_broadcast":
        await callback.message.edit_text("❌ Xabar topilmadi.", reply_markup=back_to_admin_kb())
        return

    user_ids = await database.get_all_active_user_ids()
    sent = 0
    failed = 0
    status_msg = await callback.message.answer(
        f"📢 Broadcast boshlandi... (0/{len(user_ids)})"
    )

    for i, uid in enumerate(user_ids, 1):
        try:
            await get_bot().send_message(uid, broadcast_text)
            sent += 1
        except Exception:
            failed += 1
        if i % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 Yuborilmoqda... ({i}/{len(user_ids)})"
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)  # flood limit

    await status_msg.edit_text(
        f"✅ <b>Broadcast yakunlandi!</b>\n\n"
        f"📨 Yuborildi: <b>{sent}</b>\n"
        f"❌ Xato: <b>{failed}</b>",
        reply_markup=back_to_admin_kb(),
    )

# ===========================================================================
# ADMIN FSM — matn xabarlarini qayta ishlash
# ===========================================================================

async def _handle_admin_fsm(message: Message) -> bool:
    """
    Admin FSM holatini tekshiradi.
    True qaytarsa — xabar admin FSM tomonidan qayta ishlandi.
    """
    global maintenance_mode

    state = admin_states.get(message.from_user.id)
    if not state:
        return False

    text = message.text or ""

    # --- Broadcast matnini kutmoqda ---
    if state == "awaiting_broadcast":
        # Tasdiqlash so'rash
        admin_states[message.from_user.id] = text  # matnni holatga saqlash
        preview = text[:300] + ("..." if len(text) > 300 else "")
        await message.answer(
            f"📢 <b>Broadcast oldindan ko'rish:</b>\n\n"
            f"{preview}\n\n"
            f"<b>Jami foydalanuvchilar soni:</b> {len(await database.get_all_active_user_ids())} ta\n\n"
            f"Yuborishni tasdiqlaysizmi?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Ha, yuborish", callback_data="adm:confirm_broadcast:"),
                    InlineKeyboardButton(text="❌ Bekor", callback_data="adm:cancel_broadcast"),
                ]
            ]),
        )
        return True

    # --- Foydalanuvchi izlash ---
    if state == "awaiting_search_user":
        admin_states.pop(message.from_user.id, None)
        try:
            uid = int(text.strip())
        except ValueError:
            await message.answer("❌ Noto'g'ri ID.", reply_markup=back_to_admin_kb())
            return True
        row = await database.get_user_info(uid)
        if not row:
            await message.answer(
                f"⚠️ Foydalanuvchi <b>{uid}</b> bazada topilmadi.",
                reply_markup=back_to_admin_kb(),
            )
            return True
        uid_, uname, fname, first_seen, last_active, banned, dl_cnt = row
        ban_text = "🚫 Ban qilingan" if banned else "✅ Faol"
        uname_str = f"@{uname}" if uname else "yo'q"
        info = (
            f"👤 <b>Foydalanuvchi ma'lumoti</b>\n\n"
            f"🆔 ID: <code>{uid_}</code>\n"
            f"📛 Ism: <b>{fname or '—'}</b>\n"
            f"🔗 Username: {uname_str}\n"
            f"📅 Ro'yxatdan: {first_seen[:10]}\n"
            f"🕐 Oxirgi faollik: {last_active[:16]}\n"
            f"📥 Yuklamalar: <b>{dl_cnt}</b>\n"
            f"🔒 Holat: {ban_text}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 Ban" if not banned else "✅ Unban",
                    callback_data=f"adm:{'ban' if not banned else 'unban'}",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Qaytish", callback_data="adm:back")],
        ])
        await message.answer(info, reply_markup=kb)
        return True

    # --- Ban ---
    if state == "awaiting_ban":
        admin_states.pop(message.from_user.id, None)
        try:
            uid = int(text.strip())
        except ValueError:
            await message.answer("❌ Noto'g'ri ID.", reply_markup=back_to_admin_kb())
            return True
        ok = await database.ban_user(uid)
        if ok:
            await message.answer(f"✅ Foydalanuvchi <b>{uid}</b> bloklandi.", reply_markup=back_to_admin_kb())
            try:
                await get_bot().send_message(uid, "🚫 Siz botdan bloklangansiz.")
            except Exception:
                pass
        else:
            await message.answer(
                f"⚠️ Foydalanuvchi <b>{uid}</b> bazada topilmadi.",
                reply_markup=back_to_admin_kb(),
            )
        return True

    # --- Unban ---
    if state == "awaiting_unban":
        admin_states.pop(message.from_user.id, None)
        try:
            uid = int(text.strip())
        except ValueError:
            await message.answer("❌ Noto'g'ri ID.", reply_markup=back_to_admin_kb())
            return True
        ok = await database.unban_user(uid)
        if ok:
            await message.answer(
                f"✅ Foydalanuvchi <b>{uid}</b> blokdan chiqarildi.",
                reply_markup=back_to_admin_kb(),
            )
            try:
                await get_bot().send_message(
                    uid, "✅ Blokingiz olib tashlandi! Botdan foydalanishingiz mumkin."
                )
            except Exception:
                pass
        else:
            await message.answer(
                f"⚠️ Foydalanuvchi <b>{uid}</b> bazada topilmadi.",
                reply_markup=back_to_admin_kb(),
            )
        return True

    return False

# ===========================================================================
# ASOSIY MATN XABARLARINI QAYTA ISHLASH
# ===========================================================================

@dp.message(F.text)
async def handle_incoming_text(message: Message):
    user_id = message.from_user.id

    # Admin FSM tekshirish
    if is_admin(user_id):
        handled = await _handle_admin_fsm(message)
        if handled:
            return

    # Foydalanuvchini ro'yxatdan o'tkazish / yangilash
    await database.register_user(
        user_id,
        message.from_user.username,
        message.from_user.full_name,
    )

    # Ban tekshirish
    if await database.is_banned(user_id):
        await message.answer("🚫 Siz botdan bloklangansiz. Murojaat qiling: @admin")
        return

    # Texnik rejim (faqat admin kira oladi)
    if maintenance_mode and not is_admin(user_id):
        await message.answer(
            "🔧 <b>Texnik ishlar davom etmoqda</b>\n\n"
            "Bot hozircha vaqtincha to'xtatilgan. Tez orada qayta ishlaydi! ⏳"
        )
        return

    text = message.text.strip()
    url = downloader.find_supported_url(text)
    platform = detect_platform(url) if url else "Boshqa"

    if not url:
        await message.answer(
            "😊 <b>Salom, qadrdonim!</b>\n\n"
            "Menga quyidagi ijtimoiy tarmoqlardan birining video yoki rasm havolasini yuboring:\n"
            "• <b>Instagram</b>, <b>YouTube</b>, <b>TikTok</b>, <b>Facebook</b>, "
            "<b>Pinterest</b>, <b>Snapchat</b> yoki <b>Telegram</b>.\n\n"
            "Men darhol uni sizga eng a'lo sifatda yuklab beraman! 🎬✨"
        )
        return

    status_msg = await message.answer("🚀 <i>Ajoyib havola! Qidirmoqdaman va siz uchun tayyorlayapman...</i>")

    file_id = uuid.uuid4().hex[:12]
    out_tmpl = str(config.DOWNLOAD_DIR / f"media_{file_id}.%(ext)s")

    async with download_semaphore:
        try:
            res = await asyncio.wait_for(
                downloader.download_video(url, out_tmpl),
                timeout=config.DOWNLOAD_TIMEOUT_SECONDS
            )

            if not res.get("success"):
                err = res.get("error", "Noma'lum xatolik")
                await database.log_download(user_id, url, platform, "video", False)
                await status_msg.edit_text(
                    f"😔 <b>Kechirasiz, yuklab bo'lmadi:</b>\n{err}\n\n"
                    f"💡 <i>Boshqa havola bilan sinab ko'ring yoki birozdan so'ng qayta urining!</i>"
                )
                return

            file_path = res["file_path"]
            filesize = res.get("filesize", 0)
            if filesize > config.MAX_FILE_SIZE_BYTES:
                downloader.cleanup_file(file_path)
                err = downloader.format_user_error(f"Fayl hajmi Telegram limitidan ({filesize // (1024*1024)}MB > 50MB) katta.")
                await status_msg.edit_text(f"😔 {err}")
                return

            title = res.get("title", "Media")
            uploader = res.get("uploader", "Noma'lum")
            media_type = res.get("media_type", "video")

            await database.log_download(user_id, url, platform, media_type, True)
            await status_msg.edit_text("📤 <i>Tayyor bo'ldi! Telegramga uchmoqda...</i>")

            is_image = media_type == "photo" or file_path.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            )

            if is_image:
                caption = (
                    f"📸 <b>{title}</b>\n"
                    f"👤 <b>Manba:</b> {uploader}\n\n"
                    f"✨ <i>Siz uchun eng a'lo sifatda yuklab berildi!</i>\n"
                    f"⚡️ <b>@chaqqon_robot</b>"
                )
                await message.answer_photo(photo=FSInputFile(file_path), caption=caption)
            else:
                url_id = cache_url(url, title)
                music_btn = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(
                            text="🎵 Musiqasini yuklab olish (MP3)",
                            callback_data=f"aud:{url_id}",
                        )
                    ]]
                )
                caption = (
                    f"🎬 <b>{title}</b>\n"
                    f"👤 <b>Manba:</b> {uploader}\n\n"
                    f"✨ <i>Siz uchun eng a'lo sifatda yuklab berildi! Maroq bilan tomosha qiling!</i> 🍿\n"
                    f"⚡️ <b>@chaqqon_robot</b>"
                )

                filesize = res.get("filesize") or (os.path.getsize(file_path) if os.path.exists(file_path) else 0)
                if filesize > 50 * 1024 * 1024:
                    logger.info(f"Fayl hajmi ({filesize // (1024*1024)}MB) 50MB dan katta. MTProto orqali yuborilmoqda...")
                    await mtproto_uploader.send_large_video(
                        chat_id=message.chat.id,
                        file_path=file_path,
                        caption=caption,
                        width=res.get("width"),
                        height=res.get("height"),
                        duration=res.get("duration"),
                    )
                else:
                    try:
                        await message.answer_video(
                            video=FSInputFile(file_path),
                            caption=caption,
                            width=res.get("width"),
                            height=res.get("height"),
                            duration=res.get("duration"),
                            reply_markup=music_btn,
                        )
                    except Exception as send_err:
                        if "too large" in str(send_err).lower() or "413" in str(send_err):
                            logger.info("Bot API 413 xatosi berdi. MTProto orqali yuborilmoqda...")
                            await mtproto_uploader.send_large_video(
                                chat_id=message.chat.id,
                                file_path=file_path,
                                caption=caption,
                                width=res.get("width"),
                                height=res.get("height"),
                                duration=res.get("duration"),
                            )
                        else:
                            raise send_err

            try:
                await status_msg.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            logger.warning(f"Download timeout ({config.DOWNLOAD_TIMEOUT_SECONDS}s) for URL: {url}")
            err_msg = downloader.format_user_error("timed out")
            await status_msg.edit_text(f"⏳ {err_msg}")
        except Exception as e:
            logger.error(f"Media yuborishda xatolik: {e}")
            err_msg = downloader.format_user_error(str(e))
            await status_msg.edit_text(f"❌ {err_msg}")
        finally:
            if "res" in locals() and isinstance(res, dict) and res.get("file_path"):
                downloader.cleanup_file(res.get("file_path"))
            downloader.cleanup_template_artifacts(out_tmpl)

# ===========================================================================
# AUDIO CALLBACK
# ===========================================================================

@dp.callback_query(F.data.startswith("aud:"))
async def on_download_audio_callback(callback: CallbackQuery):
    await callback.answer()
    url_id = callback.data.split(":", 1)[1]
    url = get_cached_url(url_id)
    user_id = callback.from_user.id

    if not url:
        await callback.message.answer("⚠️ Havola muddati tugagan. Iltimos, havolani qaytadan yuboring.")
        return

    # Ban tekshirish
    if await database.is_banned(user_id):
        await callback.message.answer("🚫 Siz botdan bloklangansiz.")
        return

    if maintenance_mode and not is_admin(user_id):
        await callback.message.answer("🔧 Texnik ishlar davom etmoqda. Biroz kuting.")
        return

    file_id = uuid.uuid4().hex[:12]
    out_tmpl = str(config.DOWNLOAD_DIR / f"aud_{file_id}.%(ext)s")

    status_msg = await callback.message.answer("🎧 <i>Musiqa (MP3) ajratib olinmoqda, kuting...</i>")
    platform = detect_platform(url)

    async with download_semaphore:
        try:
            res = await asyncio.wait_for(
                downloader.download_audio(url, out_tmpl),
                timeout=config.DOWNLOAD_TIMEOUT_SECONDS
            )

            if not res.get("success"):
                err = res.get("error", "Noma'lum xatolik")
                await database.log_download(user_id, url, platform, "audio", False)
                await status_msg.edit_text(f"❌ <b>Audio ajratib bo'lmadi:</b>\n{err}")
                return

            file_path = res["file_path"]
            filesize = res.get("filesize", 0) or (os.path.getsize(file_path) if os.path.exists(file_path) else 0)
            if filesize > config.MAX_FILE_SIZE_BYTES:
                downloader.cleanup_file(file_path)
                err = downloader.format_user_error(f"Audio hajmi ({filesize // (1024*1024)}MB > {config.MAX_FILE_SIZE_BYTES // (1024*1024)}MB) Telegram limitidan katta.")
                await status_msg.edit_text(f"❌ {err}")
                return

            title = res.get("title", "Musiqa")
            uploader_name = res.get("uploader", "Noma'lum")

            await database.log_download(user_id, url, platform, "audio", True)
            await status_msg.edit_text("📤 <i>Musiqa Telegramga yuborilmoqda...</i>")

            caption = (
                f"🎵 <b>{title}</b>\n"
                f"👤 <b>Ijrochi:</b> {uploader_name}\n\n"
                f"✨ <i>Eng toza va tiniq sifatda!</i>\n"
                f"⚡️ <b>@chaqqon_robot</b>"
            )

            if filesize > 50 * 1024 * 1024:
                logger.info(f"Audio fayl hajmi ({filesize // (1024*1024)}MB) 50MB dan katta. MTProto orqali yuborilmoqda...")
                await mtproto_uploader.send_large_audio(
                    chat_id=callback.message.chat.id,
                    file_path=file_path,
                    title=title,
                    performer=uploader_name,
                    duration=res.get("duration"),
                )
            else:
                audio_input = FSInputFile(file_path)
                try:
                    if file_path.lower().endswith(".mp3"):
                        await callback.message.answer_audio(
                            audio=audio_input,
                            title=title,
                            performer=uploader_name,
                            duration=res.get("duration"),
                            caption=caption,
                        )
                    else:
                        await callback.message.answer_document(document=audio_input, caption=caption)
                except Exception as send_err:
                    if "too large" in str(send_err).lower() or "413" in str(send_err):
                        logger.info("Audio yuborishda 413 xatosi. MTProto orqali yuborilmoqda...")
                        await mtproto_uploader.send_large_audio(
                            chat_id=callback.message.chat.id,
                            file_path=file_path,
                            title=title,
                            performer=uploader_name,
                            duration=res.get("duration"),
                        )
                    else:
                        raise send_err

            try:
                await status_msg.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            logger.warning(f"Audio download timeout ({config.DOWNLOAD_TIMEOUT_SECONDS}s) for URL: {url}")
            err_msg = downloader.format_user_error("timed out")
            await status_msg.edit_text(f"⏳ {err_msg}")
        except Exception as e:
            logger.error(f"Audio yuborishda xatolik: {e}")
            err_msg = downloader.format_user_error(str(e))
            await status_msg.edit_text(f"❌ {err_msg}")
        finally:
            if "res" in locals() and isinstance(res, dict) and res.get("file_path"):
                downloader.cleanup_file(res.get("file_path"))
            downloader.cleanup_template_artifacts(out_tmpl)

# ===========================================================================
# WEB SERVER (Render.com healthcheck + keep-alive)
# ===========================================================================

async def health_check_handler(request):
    stats = await database.get_stats()
    return web.json_response({
        "status": "online",
        "service": "Chaqqon Video Downloader Bot",
        "uptime": uptime_str(),
        "total_users": stats["total_users"],
        "total_downloads": stats["total_downloads"],
        "maintenance": maintenance_mode,
        "verified_proxies": proxy_manager.get_verified_count(),
    })


async def proxy_refresher_task():
    logger.info("Proxy pool warm-up boshlanmoqda...")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, proxy_manager.scrape_and_validate_proxies, 6, 40)
        logger.info(f"Proxy pool tayyor: {proxy_manager.get_verified_count()} ta ishlaydigan HTTPS proxy.")
    except Exception as e:
        logger.warning(f"Dastlabki proxy warm-up xatosi: {e}")

    while True:
        try:
            await asyncio.sleep(600)
            await loop.run_in_executor(None, proxy_manager.scrape_and_validate_proxies, 6, 40)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Davriy proxy yangilashda xatolik: {e}")


async def test_yt_handler(request):
    url = request.query.get("url", "https://www.youtube.com/watch?v=jNQXAC9IVRw")
    import traceback, shutil, time
    t0 = time.time()
    try:
        res = await downloader.download_video(url, "/tmp/debug_test.%(ext)s")
        file_p = res.get("file_path")
        if file_p:
            downloader.cleanup_file(file_p)
        downloader.cleanup_template_artifacts("/tmp/debug_test.%(ext)s")
        return web.json_response({
            "status": "ok",
            "url": url,
            "duration_seconds": round(time.time() - t0, 2),
            "download_result": {k: v for k, v in res.items() if k != "file_path"}
        })
    except Exception as e:
        return web.json_response({
            "status": "error",
            "duration_seconds": round(time.time() - t0, 2),
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


async def render_keep_alive_task():
    await asyncio.sleep(20)
    external_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEP_ALIVE_URL")
    if not external_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
        external_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/health"
    port = int(os.environ.get("PORT", 8080))
    target_url = external_url or f"http://127.0.0.1:{port}/health"
    logger.info(f"🚀 Anti-Sleep Keep-Alive: {target_url}")
    while True:
        try:
            await asyncio.sleep(480)
            async with aiohttp.ClientSession() as session:
                async with session.get(target_url, timeout=15) as resp:
                    logger.info(f"⚡️ Keep-Alive ping: HTTP {resp.status}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Keep-Alive xato: {e}")


async def on_app_startup(app):
    await database.init_db()
    logger.info("✅ Ma'lumotlar bazasi tayyor.")
    app["keep_alive_task"] = asyncio.create_task(render_keep_alive_task())
    app["proxy_task"] = asyncio.create_task(proxy_refresher_task())

    if not config.BOT_TOKEN:
        logger.warning("DIQQAT: BOT_TOKEN yo'q! Faqat healthcheck rejimi.")
        return
    try:
        active_bot = get_bot()
        logger.info("Telegram Bot polling boshlanmoqda...")
        await active_bot.delete_webhook(drop_pending_updates=True)
        app["bot_task"] = asyncio.create_task(dp.start_polling(active_bot))
    except Exception as e:
        logger.error(f"Botni ishga tushirishda xatolik: {e}")


async def on_app_cleanup(app):
    for key in ("keep_alive_task", "bot_task", "proxy_task"):
        if key in app:
            app[key].cancel()
            try:
                await app[key]
            except asyncio.CancelledError:
                pass
    if bot is not None:
        await bot.session.close()


async def proxy_diag_handler(request):
    return web.json_response({
        "verified_count": proxy_manager.get_verified_count(),
        "static_proxy": proxy_manager.get_static_proxy(),
        "pool": list(proxy_manager._verified_proxies)[:10],
    })


async def test_yt_extract_handler(request):
    url = request.query.get("url", "https://www.youtube.com/watch?v=jNQXAC9IVRw")
    proxy = request.query.get("proxy")
    use_pool = request.query.get("pool") == "1"
    client = request.query.get("client", "tv_samsung")
    import yt_dlp, time
    t0 = time.time()

    opts = {
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 6,
        'retries': 1,
        'extractor_args': {'youtube': {'player_client': [client, 'visionos']}},
        'noplaylist': True,
    }
    if proxy:
        opts['proxy'] = proxy
    elif use_pool:
        opts['proxy'] = proxy_manager.get_working_proxy()

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return web.json_response({
                "status": "success",
                "duration_seconds": round(time.time() - t0, 2),
                "title": info.get("title"),
                "proxy_used": opts.get("proxy"),
                "client": client,
                "formats_count": len(info.get("formats", []))
            })
    except Exception as e:
        return web.json_response({
            "status": "error",
            "duration_seconds": round(time.time() - t0, 2),
            "proxy_used": opts.get("proxy"),
            "client": client,
            "error": str(e)
        })


def main():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    app.router.add_get("/proxy-diag", proxy_diag_handler)
    app.router.add_get("/test-yt-extract", test_yt_extract_handler)
    app.router.add_get("/test-yt", test_yt_handler)
    app.on_startup.append(on_app_startup)
    app.on_cleanup.append(on_app_cleanup)
    logger.info(f"Render/Web server ishga tushmoqda (Port: {port})...")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot server to'xtatildi.")
