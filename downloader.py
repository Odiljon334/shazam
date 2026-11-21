import os
import re
import html
import asyncio
import logging
import subprocess
import urllib.request
from urllib.parse import urlparse
from enum import Enum
from typing import Optional, Dict, Any, List, Protocol
from pathlib import Path
import yt_dlp
import config

logger = logging.getLogger(__name__)

# URLlarni aniqlash uchun kengaytirilgan regex shablonlari (Barcha platformalar)
URL_REGEX = re.compile(
    r'(https?://(?:[a-zA-Z0-9-]+\.)*(?:instagram\.com|instagr\.am|tiktok\.com|youtube\.com|youtu\.be|pin\.it|pinterest\.com|twitter\.com|x\.com|facebook\.com|fb\.watch|fb\.com|snapchat\.com|t\.me|telegram\.me)[^\s]+)',
    re.IGNORECASE
)

MAX_TELEGRAM_SIZE = config.MAX_FILE_SIZE_BYTES  # 50 MB Telegram Bot API limiti

SOCIAL_CRAWLER_UAS = [
    'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
    'TelegramBot (like TwitterBot)',
    'Twitterbot/1.0',
    'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
]

class DownloadErrorKind(Enum):
    BOT_BLOCKED = "bot_blocked"
    TIMEOUT = "timeout"
    UNAVAILABLE_OR_RESTRICTED = "unavailable_or_restricted"
    FILE_TOO_LARGE = "file_too_large"
    FORMAT_NOT_AVAILABLE = "format_not_available"
    GENERAL = "general"

def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc if netloc else "unknown"
    except Exception:
        return "unknown"

def classify_error(err: Any) -> tuple[DownloadErrorKind, str]:
    """
    Xatoliklarni tahlil qilib, ularni kategoriyaga ajratadi va
    foydalanuvchiga Telegramda ko'rsatish uchun chiroyli matn shakllantiradi.
    """
    err_str = str(err).lower()

    # 1. YouTube / platforma bot tekshiruvi va 403 bloklari
    if any(k in err_str for k in [
        "sign in to confirm you're not a bot",
        "confirm you’re not a bot",
        "bot detection",
        "http error 403",
        "403: forbidden",
        "forbidden",
        "sabr",
        "signature decipher",
        "blocked by youtube",
    ]):
        msg = (
            "🤖 <b>YouTube Xizmati Vaqtincha Band:</b>\n"
            "YouTube bulut serveri ushbu so'rovni vaqtincha chekladi (403 Blok).\n"
            f"🔍 <i>Sabab:</i> <code>{html.escape(str(err)[:180])}</code>\n\n"
            "💡 Iltimos, boshqa havola yuboring yoki birozdan so'ng qayta urinib ko'ring."
        )
        return DownloadErrorKind.BOT_BLOCKED, msg

    # 2. Tarmoq va Timeout xatoliklari
    if any(k in err_str for k in [
        "timed out",
        "timeout",
        "timeouterror",
        "socket_timeout",
        "socket.timeout",
        "connection reset",
        "connection refused",
        "name resolution",
        "network is unreachable",
        "remote end closed connection",
    ]):
        msg = (
            "⏳ <b>Tarmoq Xatoligi (Timeout):</b>\n"
            "Serverga ulanish vaqti tugadi yoki internet aloqasi sekinlashdi.\n"
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        )
        return DownloadErrorKind.TIMEOUT, msg

    # 3. Mavjud bo'lmagan, yopiq yoki yosh chegarasi qo'yilgan videolar
    if any(k in err_str for k in [
        "video unavailable",
        "private video",
        "this video is private",
        "removed by the user",
        "not found",
        "http error 404",
        "404: not found",
        "age-restricted",
        "confirm your age",
        "inappropriate for some users",
        "restricted video",
        "not available in your country"
    ]):
        if "restricted video" in err_str or "not available in your country" in err_str:
            msg = (
                "🚫 <b>Mintaqaviy Litsenziya Cheklovi:</b>\n"
                "Bu video/musiqa mintaqaviy litsenziya tufayli bloklangan.\n"
                "💡 Render Environment Variables bo'limiga INSTAGRAM_COOKIES qo'shing."
            )
        else:
            msg = (
                "🚫 <b>Video Mavjud Emas yoki Cheklangan:</b>\n"
                "Ushbu media o'chirilgan, yopiq (private) profil yoki yosh chegarasi (18+) mavjud."
            )
        return DownloadErrorKind.UNAVAILABLE_OR_RESTRICTED, msg

    # 4. Fayl hajmi limiti (Telegram 50MB)
    if any(k in err_str for k in [
        "telegram limitidan",
        "file is too large",
        "max_filesize",
        "filesize exceeded",
        "file size",
    ]):
        msg = (
            "📦 <b>Fayl Hajmi Limiti:</b>\n"
            "Media fayl hajmi Telegram Bot API ruxsat bergan 50 MB limitidan oshib ketdi."
        )
        return DownloadErrorKind.FILE_TOO_LARGE, msg

    # 5. Umumiy boshqa xatoliklar
    clean_err = str(err).strip()
    if "ERROR:" in clean_err:
        clean_err = clean_err.split("ERROR:", 1)[1].strip()
    msg = f"⚠️ <b>Yuklab olishda xatolik:</b>\n{html.escape(clean_err[:180])}"
    return DownloadErrorKind.GENERAL, msg

def format_user_error(err_str: Any) -> str:
    """Foydalanuvchiga ko'rsatiladigan xabar matnini qaytaradi."""
    _, msg = classify_error(err_str)
    return msg

def log_download_event(event: str, url: str, **kwargs):
    """Strukturalangan muvaffaqiyatli hodisa logi."""
    domain = _extract_domain(url)
    details = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info(f"[DOWNLOAD_EVENT] event={event} domain={domain} {details}".strip())

def log_download_error(event: str, url: str, exc: Exception, strategy: str = "default", **kwargs):
    """Strukturalangan xatolik logi."""
    kind, _ = classify_error(exc)
    domain = _extract_domain(url)
    details = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.warning(
        f"[DOWNLOAD_ERROR] event={event} domain={domain} strategy={strategy} kind={kind.value} error='{exc}' {details}".strip()
    )

def normalize_youtube_url(url: str) -> str:
    """
    YouTube URLlarini tozalaydi va radio/mix pleylistlarni to'g'ridan-to'g'ri video URL ga aylantiradi.
    Masalan:
    https://youtube.com/playlist?list=RDSgLjmnHMqAE&playnext=1 -> https://www.youtube.com/watch?v=SgLjmnHMqAE
    https://www.youtube.com/watch?v=SgLjmnHMqAE&list=RD... -> https://www.youtube.com/watch?v=SgLjmnHMqAE
    """
    if not url:
        return url
    lower_u = url.lower()
    if "youtube.com" not in lower_u and "youtu.be" not in lower_u:
        return url

    # 1. list=RD<video_id> (YouTube Radio/Mix pleylist)
    rd_match = re.search(r'[?&]list=RD([a-zA-Z0-9_-]{11})', url)
    if rd_match:
        return f"https://www.youtube.com/watch?v={rd_match.group(1)}"

    # 2. v=<video_id> parametri bo'lsa
    v_match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
    if v_match:
        return f"https://www.youtube.com/watch?v={v_match.group(1)}"

    # 3. youtu.be/<video_id>
    ytbe_match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
    if ytbe_match:
        return f"https://www.youtube.com/watch?v={ytbe_match.group(1)}"

    return url

def find_supported_url(text: str) -> Optional[str]:
    """Matn ichidan qo'llab-quvvatlanadigan URLni topadi va tozalaydi."""
    if not text:
        return None
    match = URL_REGEX.search(text.strip())
    if match:
        raw_url = match.group(0).rstrip("?&")
        return normalize_youtube_url(raw_url)
    return None

def _get_ytdl_common_opts(cookie_path: Optional[str] = None) -> dict:
    """
    yt-dlp umumiy sozlamalari (Render bulut muhiti va local uchun optimallashgan).
    Xotira (RAM) tejash, Node.js EJS challenge solver, socket timeout va retries bilan.
    """
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'socket_timeout': 20,
        'retries': 3,
        'fragment_retries': 3,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'noplaylist': True,
        'playlist_items': '1',
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
    }
    if cookie_path and os.path.exists(cookie_path):
        opts['cookiefile'] = cookie_path
    return opts

def cleanup_file(filepath: Optional[str]) -> None:
    """Faylni diskdan butunlay o'chirib tashlaydi (ephemeral disk to'lib qolmasligi uchun)."""
    if not filepath:
        return
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Vaqtinchalik fayl tozalandi: {filepath}")
    except Exception as e:
        logger.warning(f"Faylni o'chirishda xatolik ({filepath}): {e}")

def cleanup_template_artifacts(output_template_or_filepath: str) -> None:
    """
    Berilgan shablon yoki fayl prefiksiga tegishli bo'lgan barcha vaqtinchalik,
    chala (.part, .ytdl, .temp.*, _tempvid.*) fayllarni diskdan tozalaydi.
    """
    if not output_template_or_filepath:
        return
    try:
        dir_name = os.path.dirname(output_template_or_filepath) or "."
        raw_name = os.path.basename(output_template_or_filepath)
        clean_prefix = raw_name.replace(".%(ext)s", "").replace("%(ext)s", "").rstrip(".%")

        if os.path.exists(dir_name):
            for entry in os.listdir(dir_name):
                if entry.startswith(clean_prefix):
                    full_p = os.path.join(dir_name, entry)
                    try:
                        if os.path.isfile(full_p):
                            os.remove(full_p)
                            logger.debug(f"Artifact tozalandi: {full_p}")
                    except Exception as err:
                        logger.warning(f"Artifact tozalash xatosi ({full_p}): {err}")
    except Exception as e:
        logger.warning(f"cleanup_template_artifacts xatosi: {e}")

# ==============================================================================
# Secondary Extractor / Provider Interface (Fallback Hook)
# ==============================================================================
class SecondaryMediaProvider(Protocol):
    """
    Tashqi yordamchi provider yoki hook uchun standart interfeys.
    Primary va fallback yt-dlp urinishlari tugaganda ishga tushiriladi.
    """
    def download_video(self, url: str, output_path: str) -> Optional[Dict[str, Any]]: ...
    def download_audio(self, url: str, output_path: str) -> Optional[Dict[str, Any]]: ...

_secondary_provider: Optional[SecondaryMediaProvider] = None

def set_secondary_provider(provider: Optional[SecondaryMediaProvider]) -> None:
    """Secondary provider hook'ni o'rnatish."""
    global _secondary_provider
    _secondary_provider = provider

def get_secondary_provider() -> Optional[SecondaryMediaProvider]:
    return _secondary_provider

# ==============================================================================
# Universal Social Crawler (Instagram / Meta / Web Fallback)
# ==============================================================================
def _extract_meta_via_crawler(url: str) -> Optional[Dict[str, Any]]:
    """Ijtimoiy tarmoq botlari orqali sahifa metama'lumotlarini tezkor olish."""
    for ua in SOCIAL_CRAWLER_UAS:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                page = resp.read().decode('utf-8', errors='ignore')

                title = "Media"
                tm = re.search(r'<meta\s+property=[\"\']og:title[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I)
                if not tm:
                    tm = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+property=[\"\']og:title[\"\']', page, re.I)
                if tm:
                    title = html.unescape(tm.group(1)).strip()

                thumb = None
                im = re.search(r'<meta\s+property=[\"\']og:image[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I)
                if not im:
                    im = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+property=[\"\']og:image[\"\']', page, re.I)
                if im:
                    thumb = html.unescape(im.group(1)).strip()

                vm = re.search(r'<meta\s+property=[\"\']og:video[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I)
                if not vm:
                    vm = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+property=[\"\']og:video[\"\']', page, re.I)

                if vm or tm:
                    return {
                        'title': title,
                        'uploader': "Instagram" if "instagram" in url else "Media",
                        'duration': 0,
                        'thumbnail': thumb,
                        'description': title[:200]
                    }
        except Exception as e:
            logger.debug(f"Crawler meta error ({ua}): {e}")
            continue
    return None

def _download_via_social_crawler(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    Cloud / Datacenter (Render) IP'larida Meta/Instagram bloklaganda,
    Facebook va Telegram botlari uchun ruxsat berilgan maxsus oqimdan
    to'g'ridan-to'g'ri MP4 videoni yoki rasmni yuklab oladi.
    """
    video_url = None
    image_url = None
    title = "Media"

    for ua in SOCIAL_CRAWLER_UAS:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                page = resp.read().decode('utf-8', errors='ignore')

                vm = (
                    re.search(r'<meta\s+property=[\"\']og:video(?::secure_url)?[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I) or
                    re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+property=[\"\']og:video(?::secure_url)?[\"\']', page, re.I) or
                    re.search(r'[\"\']video_url[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', page, re.I) or
                    re.search(r'(https://[^\s\"\'<>]+\.mp4[^\s\"\'<>]*)', page, re.I)
                )

                tm = (
                    re.search(r'<meta\s+property=[\"\']og:title[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I) or
                    re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+property=[\"\']og:title[\"\']', page, re.I) or
                    re.search(r'<title>([^<]+)</title>', page, re.I)
                )
                if tm:
                    title = html.unescape(tm.group(1)).strip()

                if vm:
                    video_url = html.unescape(vm.group(1)).replace('\\/', '/')
                    break

                im = (
                    re.search(r'<meta\s+property=[\"\']og:image(?::secure_url)?[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I) or
                    re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+property=[\"\']og:image(?::secure_url)?[\"\']', page, re.I) or
                    re.search(r'<meta\s+name=[\"\']twitter:image[\"\']\s+content=[\"\']([^\"\']+)[\"\']', page, re.I) or
                    re.search(r'[\"\']display_url[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', page, re.I)
                )
                if im and not image_url:
                    image_url = html.unescape(im.group(1)).replace('\\/', '/')
        except Exception as e:
            logger.debug(f"Crawler request error ({ua}): {e}")
            continue

    lower_url = url.lower()
    if "instagram" in lower_url or "instagr.am" in lower_url:
        uploader = "Instagram"
    elif "tiktok" in lower_url:
        uploader = "TikTok"
    elif "youtube" in lower_url or "youtu.be" in lower_url:
        uploader = "YouTube"
    elif "pinterest" in lower_url or "pin.it" in lower_url:
        uploader = "Pinterest"
    elif "facebook" in lower_url or "fb.watch" in lower_url or "fb.com" in lower_url:
        uploader = "Facebook"
    elif "snapchat" in lower_url:
        uploader = "Snapchat"
    elif "t.me" in lower_url or "telegram" in lower_url:
        uploader = "Telegram"
    else:
        uploader = "Media"

    # 1. Video yuklash
    if video_url:
        try:
            final_file = output_path.replace(".%(ext)s", ".mp4") if ".%(ext)s" in output_path else output_path
            if not final_file.endswith(".mp4"):
                base, _ = os.path.splitext(final_file)
                final_file = f"{base}.mp4"

            v_req = urllib.request.Request(
                video_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Referer': url
                }
            )
            with urllib.request.urlopen(v_req, timeout=30) as v_resp, open(final_file, 'wb') as f:
                while True:
                    chunk = v_resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

            filesize = os.path.getsize(final_file)
            if filesize > MAX_TELEGRAM_SIZE:
                cleanup_file(final_file)
                return {
                    'success': False,
                    'error': f"Video hajmi Telegram limitidan ({filesize // (1024*1024)}MB > 50MB) katta.",
                    'error_kind': DownloadErrorKind.FILE_TOO_LARGE.value
                }

            return {
                'success': True,
                'media_type': 'video',
                'file_path': final_file,
                'title': title,
                'uploader': uploader,
                'duration': 0,
                'filesize': filesize
            }
        except Exception as e:
            logger.error(f"Crawler video yuklashda xatolik: {e}")

    # 2. Rasm yuklash (Pinterest, Instagram post, Facebook photo, Telegram)
    # YouTube uchun hech qachon rasm/thumbnail qaytarilmaydi!
    is_youtube = "youtube" in lower_url or "youtu.be" in lower_url
    if image_url and not is_youtube:
        try:
            final_file = output_path.replace(".%(ext)s", ".jpg") if ".%(ext)s" in output_path else output_path
            if not final_file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                base, _ = os.path.splitext(final_file)
                final_file = f"{base}.jpg"

            i_req = urllib.request.Request(
                image_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Referer': url
                }
            )
            with urllib.request.urlopen(i_req, timeout=20) as i_resp, open(final_file, 'wb') as f:
                while True:
                    chunk = i_resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

            filesize = os.path.getsize(final_file)
            return {
                'success': True,
                'media_type': 'photo',
                'file_path': final_file,
                'title': title if title != "Media" else "Rasm",
                'uploader': uploader,
                'duration': 0,
                'filesize': filesize
            }
        except Exception as e:
            logger.error(f"Crawler rasm yuklashda xatolik: {e}")

    return None

# ==============================================================================
# Metadata Extraction
# ==============================================================================
def _sync_extract_info(url: str) -> Optional[Dict[str, Any]]:
    """URL haqida asosiy ma'lumotlarni yuklab olmasdan oladi."""
    is_yt = "youtube.com" in url.lower() or "youtu.be" in url.lower()

    with config.cookie_file_context() as cookie_path:
        opts = _get_ytdl_common_opts(cookie_path=cookie_path)
        opts['extract_flat'] = False

        # YouTube uchun maxsus player_client strategiyalari (cookiesiz, avtomatik bot-bypass)
        client_attempts = (
            [None, ['tv_samsung'], ['visionos']] if is_yt else [None]
        )

        for client_group in client_attempts:
            iter_opts = dict(opts)
            if is_yt and (client_group is None or 'visionos' in client_group):
                iter_opts.pop('cookiefile', None)
            if client_group:
                iter_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': client_group,
                    }
                }
            try:
                with yt_dlp.YoutubeDL(iter_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return {
                            'title': info.get('title') or 'Media',
                            'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                            'duration': info.get('duration') or 0,
                            'thumbnail': info.get('thumbnail'),
                            'description': (info.get('description') or '')[:200],
                        }
            except Exception as e:
                log_download_error("extract_info_attempt", url, e, strategy=str(client_group))
                continue

    # yt-dlp muvaffaqiyatsiz bo'lsa, crawler orqali tekshirish
    return _extract_meta_via_crawler(url)

async def extract_info(url: str) -> Optional[Dict[str, Any]]:
    """Asinxron metadata olish."""
    return await asyncio.to_thread(_sync_extract_info, url)

# ==============================================================================
# Video Download (Multi-Tier Resilient YouTube & Cloud Architecture)
# ==============================================================================
def _resolve_downloaded_file(ydl: yt_dlp.YoutubeDL, info: dict, output_template: str) -> Optional[str]:
    """yt-dlp saqlagan haqiqiy yakuniy fayl yo'lini aniqlaydi."""
    expected_filename = ydl.prepare_filename(info)
    base, _ = os.path.splitext(expected_filename)
    mp4_path = f"{base}.mp4"

    if os.path.exists(mp4_path):
        return mp4_path
    if os.path.exists(expected_filename):
        return expected_filename

    dir_name = os.path.dirname(output_template) or "."
    base_name = os.path.basename(base)
    if os.path.exists(dir_name):
        for f in os.listdir(dir_name):
            if f.startswith(base_name) and not f.endswith(('.part', '.ytdl', '.temp')):
                candidate = os.path.join(dir_name, f)
                if os.path.exists(candidate):
                    return candidate
    return None

def _sync_download_video(url: str, output_template: str) -> Dict[str, Any]:
    """
    Videoni yuklab oladi.
    Render 512MB RAM cheklovini hisobga olgan holda format tanlaydi.
    YouTube bloklariga qarshi ko'p bosqichli Fallback arxitekturasi:
      Tier 1: Cloud-optimized iOS/Android player client
      Tier 2: TV / MWeb player client
      Tier 3: Standalone format 18 (360p pre-muxed mp4, minimal RAM/CPU)
      Tier 4: Secondary Provider Hook
      Tier 5: Universal Social Crawler (Instagram/TikTok/Meta)
    """
    is_yt = "youtube.com" in url.lower() or "youtu.be" in url.lower()
    last_err: Optional[Exception] = None

    with config.cookie_file_context() as cookie_path:
        base_opts = _get_ytdl_common_opts(cookie_path=cookie_path)
        base_opts.update({
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'max_filesize': MAX_TELEGRAM_SIZE,
        })

        # YouTube uchun ketma-ket sinab ko'riladigan strategiyalar (Cloud Datacenter + Home IP Resilient)
        if is_yt:
            yt_format = (
                'bestvideo[height<=720][filesize_approx<40M]+bestaudio[filesize_approx<8M]/'
                'bestvideo[height<=480][filesize_approx<42M]+bestaudio[filesize_approx<6M]/'
                'bestvideo[height<=360][filesize_approx<42M]+bestaudio[filesize_approx<6M]/'
                'bestvideo[height<=240]+bestaudio[abr<=64]/'
                'best[filesize<48M]/18/best'
            )
            strategies = [
                {
                    'name': 'yt_authenticated_cookies',
                    'format': yt_format,
                    'no_cookies': False,
                },
                {
                    'name': 'yt_zero_cookie_adaptive',
                    'format': yt_format,
                    'no_cookies': True,
                },
                {
                    'name': 'yt_tv_samsung_cloud',
                    'format': yt_format,
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['tv_samsung'],
                        }
                    },
                    'no_cookies': True,
                },
                {
                    'name': 'yt_visionos_direct',
                    'format': yt_format,
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['visionos'],
                        }
                    },
                    'no_cookies': True,
                }
            ]
        else:
            strategies = [
                {
                    'name': 'general_social',
                    'format': 'bestvideo[filesize<48M][ext=mp4]+bestaudio[ext=m4a]/best[filesize<48M][ext=mp4]/best[filesize<48M]/bestvideo[filesize_approx<48M]+bestaudio/18/best',
                    'extractor_args': {
                        'instagram': {'api_host': 'i.instagram.com'},
                    },
                    'no_cookies': False,
                }
            ]

        for strat in strategies:
            strat_opts = dict(base_opts)
            if strat.get('no_cookies'):
                strat_opts.pop('cookiefile', None)
            strat_opts['format'] = strat['format']
            if 'extractor_args' in strat:
                strat_opts['extractor_args'] = strat['extractor_args']

            try:
                log_download_event("strategy_attempt_start", url, strategy=strat['name'])
                with yt_dlp.YoutubeDL(strat_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        final_path = _resolve_downloaded_file(ydl, info, output_template)
                        if final_path and os.path.exists(final_path):
                            filesize = os.path.getsize(final_path)
                            if filesize > MAX_TELEGRAM_SIZE:
                                cleanup_file(final_path)
                                return {
                                    'success': False,
                                    'error': f"Media hajmi Telegram limitidan ({filesize // (1024*1024)}MB > 50MB) katta.",
                                    'error_kind': DownloadErrorKind.FILE_TOO_LARGE.value
                                }

                            is_photo = final_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                            log_download_event("strategy_success", url, strategy=strat['name'], filesize=filesize)
                            return {
                                'success': True,
                                'media_type': 'photo' if is_photo else 'video',
                                'file_path': final_path,
                                'title': info.get('title') or ('Rasm' if is_photo else 'Video'),
                                'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                                'duration': info.get('duration') or 0,
                                'width': info.get('width'),
                                'height': info.get('height'),
                                'filesize': filesize
                            }
            except Exception as e:
                last_err = e
                log_download_error("strategy_failed", url, e, strategy=strat['name'])
                cleanup_template_artifacts(output_template)
                continue

    # Tier 4: Agar ro'yxatdan o'tgan Secondary Provider mavjud bo'lsa
    sec_provider = get_secondary_provider()
    if sec_provider:
        try:
            log_download_event("secondary_provider_attempt", url)
            sec_res = sec_provider.download_video(url, output_template)
            if sec_res and sec_res.get('success'):
                return sec_res
        except Exception as sec_e:
            log_download_error("secondary_provider_failed", url, sec_e, strategy="secondary_hook")

    # Tier 5: Universal Social Crawler (Instagram/TikTok/Pinterest uchun qutqaruvchi oqim)
    if not is_yt:
        crawler_res = _download_via_social_crawler(url, output_template)
        if crawler_res and crawler_res.get('success'):
            return crawler_res

    # Barcha usullar muvaffaqiyatsiz bo'lsa, qoldiq fayllarni tozalash va xatolikni tasniflash
    cleanup_template_artifacts(output_template)
    err_obj = last_err if last_err else Exception("Fayl yuklab olinmadi")
    kind, formatted_msg = classify_error(err_obj)
    return {
        'success': False,
        'error': formatted_msg,
        'error_kind': kind.value
    }

async def download_video(url: str, output_template: str) -> Dict[str, Any]:
    """Videoni asinxron oqimda yuklash."""
    return await asyncio.to_thread(_sync_download_video, url, output_template)

# ==============================================================================
# Audio (MP3) Download (Resilient Architecture)
# ==============================================================================
def _sync_download_audio(url: str, output_template: str) -> Dict[str, Any]:
    """
    Audioni (MP3) yuklab oladi va ffmpeg orqali 192kbps MP3 ga konvert qiladi.
    YouTube bloklarida ko'p pog'onali strategiya (Direct Audio -> TV client -> Video-to-MP3).
    Barcha oraliq fayllar strictly finally blokida tozalanadi.
    """
    is_yt = "youtube.com" in url.lower() or "youtu.be" in url.lower()
    primary_err: Optional[Exception] = None

    dir_name = os.path.dirname(output_template) or "."
    raw_name = os.path.basename(output_template)
    clean_prefix = raw_name.replace(".%(ext)s", "").replace("%(ext)s", "").rstrip(".%")
    target_mp3 = os.path.join(dir_name, f"{clean_prefix}.mp3")
    temp_vid_template = os.path.join(dir_name, f"{clean_prefix}_tempvid.%(ext)s")

    with config.cookie_file_context() as cookie_path:
        base_opts = _get_ytdl_common_opts(cookie_path=cookie_path)
        base_opts.update({
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'max_filesize': MAX_TELEGRAM_SIZE,
        })

        if is_yt:
            audio_strategies = [
                {
                    'name': 'yt_audio_adaptive_cloud',
                    'format': 'bestaudio[ext=m4a][filesize<48M]/bestaudio[ext=webm][filesize<48M]/bestaudio[filesize<48M]/18/best',
                    'no_cookies': True,
                },
                {
                    'name': 'yt_audio_tv_samsung',
                    'format': 'bestaudio[filesize<48M]/best[height<=480]/18/best',
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['tv_samsung'],
                        }
                    },
                    'no_cookies': True,
                },
                {
                    'name': 'yt_audio_authenticated_cookies',
                    'format': 'bestaudio[filesize<48M]/18/best',
                    'no_cookies': False,
                }
            ]
        else:
            audio_strategies = [
                {
                    'name': 'general_audio',
                    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best[height<=480]/18/best',
                    'extractor_args': {},
                    'no_cookies': False,
                }
            ]

        for strat in audio_strategies:
            strat_opts = dict(base_opts)
            if strat.get('no_cookies'):
                strat_opts.pop('cookiefile', None)
            strat_opts['format'] = strat['format']
            if strat.get('extractor_args'):
                strat_opts['extractor_args'] = strat['extractor_args']

            try:
                log_download_event("audio_strategy_attempt", url, strategy=strat['name'])
                with yt_dlp.YoutubeDL(strat_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        expected_filename = ydl.prepare_filename(info)
                        base, _ = os.path.splitext(expected_filename)
                        cand_mp3 = f"{base}.mp3"

                        if not os.path.exists(cand_mp3) and os.path.exists(target_mp3):
                            cand_mp3 = target_mp3

                        if not os.path.exists(cand_mp3) and os.path.exists(dir_name):
                            for f in os.listdir(dir_name):
                                if f.startswith(clean_prefix) and f.endswith('.mp3'):
                                    cand_mp3 = os.path.join(dir_name, f)
                                    break

                        if os.path.exists(cand_mp3):
                            filesize = os.path.getsize(cand_mp3)
                            if filesize > MAX_TELEGRAM_SIZE:
                                cleanup_file(cand_mp3)
                                return {
                                    'success': False,
                                    'error': f"Audio hajmi ({filesize // (1024*1024)}MB > 50MB) Telegram limitidan katta.",
                                    'error_kind': DownloadErrorKind.FILE_TOO_LARGE.value
                                }

                            log_download_event("audio_success", url, strategy=strat['name'], filesize=filesize)
                            return {
                                'success': True,
                                'file_path': cand_mp3,
                                'title': info.get('title') or 'Musiqa',
                                'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                                'duration': info.get('duration') or 0,
                                'filesize': filesize
                            }
            except Exception as e:
                primary_err = e
                log_download_error("audio_strategy_failed", url, e, strategy=strat['name'])
                cleanup_template_artifacts(output_template)
                continue

    # --- FALLBACK: Video yuklab, ffmpeg orqali MP3 ajratish ---
    temp_vid_path: Optional[str] = None
    try:
        log_download_event("audio_video_extract_fallback_start", url)
        vid_res = _sync_download_video(url, temp_vid_template)
        if vid_res and vid_res.get('success') and vid_res.get('file_path'):
            temp_vid_path = vid_res['file_path']

            cmd = [
                'ffmpeg', '-y', '-i', temp_vid_path,
                '-vn', '-acodec', 'libmp3lame', '-b:a', '192k',
                target_mp3
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            if os.path.exists(target_mp3):
                filesize = os.path.getsize(target_mp3)
                if filesize > MAX_TELEGRAM_SIZE:
                    cleanup_file(target_mp3)
                    return {
                        'success': False,
                        'error': f"Audio hajmi ({filesize // (1024*1024)}MB > 50MB) Telegram limitidan katta.",
                        'error_kind': DownloadErrorKind.FILE_TOO_LARGE.value
                    }

                log_download_event("audio_video_extract_fallback_success", url, filesize=filesize)
                return {
                    'success': True,
                    'file_path': target_mp3,
                    'title': vid_res.get('title') or 'Musiqa',
                    'uploader': vid_res.get('uploader') or "Noma'lum",
                    'duration': vid_res.get('duration') or 0,
                    'filesize': filesize
                }
    except Exception as fallback_err:
        log_download_error("audio_video_extract_fallback_error", url, fallback_err, strategy="ffmpeg_video_extract")
    finally:
        if temp_vid_path:
            cleanup_file(temp_vid_path)
        cleanup_template_artifacts(temp_vid_template)

    # Secondary provider audio hook
    sec_provider = get_secondary_provider()
    if sec_provider:
        try:
            sec_res = sec_provider.download_audio(url, output_template)
            if sec_res and sec_res.get('success'):
                return sec_res
        except Exception as sec_e:
            log_download_error("secondary_audio_failed", url, sec_e, strategy="secondary_audio_hook")

    cleanup_template_artifacts(output_template)
    err_obj = primary_err if primary_err else Exception("Audio faylni yaratib bo'lmadi")
    kind, formatted_msg = classify_error(err_obj)
    return {
        'success': False,
        'error': formatted_msg,
        'error_kind': kind.value
    }

async def download_audio(url: str, output_template: str) -> Dict[str, Any]:
    """Audioni asinxron oqimda yuklash."""
    return await asyncio.to_thread(_sync_download_audio, url, output_template)

# ==============================================================================
# Search Music
# ==============================================================================
def _sync_search_music(query: str, limit: int = 4) -> list[Dict[str, Any]]:
    """Matn bo'yicha audio treklarni qidiradi."""
    results = []
    search_query = f"ytsearch{limit}:{query}"

    with config.cookie_file_context() as cookie_path:
        opts = _get_ytdl_common_opts(cookie_path=cookie_path)
        opts.update({
            'extract_flat': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['visionos', 'tv_samsung'],
                }
            }
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(search_query, download=False)
                if res and 'entries' in res:
                    for entry in res['entries']:
                        if not entry:
                            continue
                        entry_id = entry.get('id')
                        url = entry.get('url') or (f"https://www.youtube.com/watch?v={entry_id}" if entry_id else None)
                        if url:
                            results.append({
                                'id': entry_id,
                                'title': entry.get('title') or 'Musiqa',
                                'uploader': entry.get('uploader') or entry.get('channel') or "Noma'lum",
                                'duration': entry.get('duration') or 0,
                                'url': url,
                            })
        except Exception as e:
            logger.error(f"Musiqa qidirishda xatolik: {e}")
    return results

async def search_music(query: str, limit: int = 4) -> list[Dict[str, Any]]:
    """Asinxron musiqa qidirish."""
    return await asyncio.to_thread(_sync_search_music, query, limit)
