"""
Bot ma'lumotlar bazasi (SQLite + aiosqlite)
Foydalanuvchilar, yuklamalar va ban ro'yxatini saqlaydi.
"""
import aiosqlite
from datetime import datetime, date
from pathlib import Path
import config

DB_PATH = config.BASE_DIR / "bot_data.db"


async def init_db():
    """Ma'lumotlar bazasini yaratadi va jadvallarni tayyorlaydi."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT    DEFAULT '',
                full_name   TEXT    DEFAULT '',
                first_seen  TEXT    NOT NULL,
                last_active TEXT    NOT NULL,
                is_banned   INTEGER DEFAULT 0,
                download_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                url        TEXT,
                platform   TEXT,
                media_type TEXT,
                success    INTEGER DEFAULT 0,
                timestamp  TEXT    NOT NULL
            )
        """)
        await db.commit()


async def register_user(user_id: int, username: str, full_name: str):
    """Yangi foydalanuvchini ro'yxatdan o'tkazadi yoki mavjudini yangilaydi."""
    now = datetime.now().isoformat(timespec='seconds')
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                full_name   = excluded.full_name,
                last_active = excluded.last_active
        """, (user_id, username or "", full_name or "", now, now))
        await db.commit()


async def is_banned(user_id: int) -> bool:
    """Foydalanuvchi ban ro'yxatida bor-yo'qligini tekshiradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_banned FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0])


async def ban_user(user_id: int) -> bool:
    """Foydalanuvchini bloklaydi. True — muvaffaqiyatli."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def unban_user(user_id: int) -> bool:
    """Foydalanuvchidan ban olib tashlaydi. True — muvaffaqiyatli."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_stats() -> dict:
    """Bot umumiy statistikasini qaytaradi."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as cur:
            banned_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE last_active LIKE ?", (f"{today}%",)
        ) as cur:
            active_today = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM downloads WHERE success = 1"
        ) as cur:
            total_downloads = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM downloads WHERE timestamp LIKE ? AND success = 1",
            (f"{today}%",)
        ) as cur:
            downloads_today = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM downloads WHERE success = 0"
        ) as cur:
            failed_downloads = (await cur.fetchone())[0]
    return {
        "total_users": total_users,
        "banned_count": banned_count,
        "active_today": active_today,
        "total_downloads": total_downloads,
        "downloads_today": downloads_today,
        "failed_downloads": failed_downloads,
    }


async def log_download(
    user_id: int, url: str, platform: str, media_type: str, success: bool
):
    """Yuklab olish harakatini bazaga yozadi."""
    now = datetime.now().isoformat(timespec='seconds')
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO downloads (user_id, url, platform, media_type, success, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, url, platform, media_type, int(success), now))
        if success:
            await db.execute(
                "UPDATE users SET download_count = download_count + 1 WHERE user_id = ?",
                (user_id,)
            )
        await db.commit()


async def get_all_active_user_ids() -> list[int]:
    """Barcha ban qilinmagan foydalanuvchilar ID larini qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE is_banned = 0"
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def get_recent_users(limit: int = 15) -> list:
    """Eng so'nggi faol foydalanuvchilarni qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, username, full_name, first_seen, last_active,
                   is_banned, download_count
            FROM users ORDER BY last_active DESC LIMIT ?
        """, (limit,)) as cur:
            return await cur.fetchall()


async def get_user_info(user_id: int):
    """Bitta foydalanuvchi haqida to'liq ma'lumot qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, username, full_name, first_seen, last_active,
                   is_banned, download_count
            FROM users WHERE user_id = ?
        """, (user_id,)) as cur:
            return await cur.fetchone()


async def get_recent_downloads(limit: int = 10) -> list:
    """So'nggi yuklab olish harakatlarini qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT d.user_id, u.username, u.full_name,
                   d.platform, d.media_type, d.success, d.timestamp
            FROM downloads d
            LEFT JOIN users u ON d.user_id = u.user_id
            ORDER BY d.id DESC LIMIT ?
        """, (limit,)) as cur:
            return await cur.fetchall()
