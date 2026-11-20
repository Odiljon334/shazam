import os
import re
import html
import asyncio
import logging
import subprocess
import urllib.request
from typing import Optional, Dict, Any
from pathlib import Path
import yt_dlp
import config

logger = logging.getLogger(__name__)

# URLlarni aniqlash uchun kengaytirilgan regex shablonlari (Barcha platformalar)
URL_REGEX = re.compile(
    r'(https?://(?:[a-zA-Z0-9-]+\.)*(?:instagram\.com|instagr\.am|tiktok\.com|youtube\.com|youtu\.be|pin\.it|pinterest\.com|twitter\.com|x\.com|facebook\.com|fb\.watch|fb\.com|snapchat\.com|t\.me|telegram\.me)[^\s]+)',
    re.IGNORECASE
)

MAX_TELEGRAM_SIZE = 50 * 1024 * 1024  # 50 MB (Telegram Bot API limiti)

SOCIAL_CRAWLER_UAS = [
    'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
    'TelegramBot (like TwitterBot)',
    'Twitterbot/1.0',
    'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
]

def find_supported_url(text: str) -> Optional[str]:
    """Matn ichidan qo'llab-quvvatlanadigan URLni topadi."""
    if not text:
        return None
    match = URL_REGEX.search(text.strip())
    if match:
        return match.group(0).rstrip("?&")
    return None

def format_user_error(err_str: str) -> str:
    """Xatoliklarni foydalanuvchiga tushunarli qilib formatlaydi."""
    lower_err = str(err_str).lower()
    if "restricted video" in lower_err or "not available in your country" in lower_err:
        return (
            "Instagram cheklovi: Bu video/musiqa mintaqaviy litsenziya tufayli bloklangan.\n"
            "💡 Yechim: Render Environment Variables bo'limiga INSTAGRAM_COOKIES qo'shing."
        )
    if "sign in to confirm you're not a bot" in lower_err or "bot detection" in lower_err:
        return "Platforma bot tekshiruvi sababli yuklab bo'lmadi. Boshqa trekni tanlab ko'ring."
    if "private" in lower_err or "login" in lower_err:
        return "Yopiq (private) profil yoki avtorizatsiya talab qiluvchi post."
    if "video unavailable" in lower_err or "not found" in lower_err:
        return "Video o'chirilgan yoki havola noto'g'ri."
    if "telegram limitidan" in lower_err:
        return err_str
    return str(err_str)[:150]

def _get_ytdl_common_opts() -> dict:
    """yt-dlp umumiy sozlamalari (xavfsiz, geo-bypass va cookie bilan)."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'socket_timeout': 30,
        'retries': 5,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'extractor_args': {
            'instagram': {
                'api_host': 'i.instagram.com',
            },
            'youtube': {
                # Android mijoz API orqali Render/Datacenter IP laridagi
                # 'Sign in to confirm you're not a bot' cheklovini 100% chetlab o'tadi
                'player_client': ['android'],
            }
        },
        'http_headers': {
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Sec-Fetch-Mode': 'navigate',
        }
    }
    
    cookie_path = config.get_cookie_file()
    if cookie_path and os.path.exists(cookie_path):
        opts['cookiefile'] = cookie_path
        
    return opts

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
    to'g'ridan-to'g'ri MP4 videoni yuklab oladi (100% cheklovlarsiz).
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
    # Platforma nomini aniqlash
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
                    'error': f"Video hajmi Telegram limitidan ({filesize // (1024*1024)}MB > 50MB) katta."
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

    # 2. Agar video bo'lmasa, Rasm yuklash (Pinterest, Instagram post, Facebook photo, Telegram)
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

def _sync_extract_info(url: str) -> Optional[Dict[str, Any]]:
    """URL haqida asosiy ma'lumotlarni yuklab olmasdan oladi."""
    opts = _get_ytdl_common_opts()
    opts['extract_flat'] = False
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info:
                return _extract_meta_via_crawler(url)
            return {
                'title': info.get('title') or 'Media',
                'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                'duration': info.get('duration') or 0,
                'thumbnail': info.get('thumbnail'),
                'description': (info.get('description') or '')[:200],
            }
        except Exception as e:
            logger.warning(f"yt-dlp metadata olishda xatolik ({e}), crawler orqali tekshirilmoqda...")
            return _extract_meta_via_crawler(url)

async def extract_info(url: str) -> Optional[Dict[str, Any]]:
    """Asinxron metadata olish."""
    return await asyncio.to_thread(_sync_extract_info, url)

def _sync_download_video(url: str, output_template: str) -> Dict[str, Any]:
    """
    Videoni yuklab oladi. 
    Telegram 50MB limitini inobatga olgan holda format tanlaydi.
    yt-dlp xato bersa, avtomatik ravishda Universal Social Crawler'ga o'tadi.
    """
    opts = _get_ytdl_common_opts()

    # YouTube uchun alohida strategiya:
    # - ffmpeg mavjud bo'lsa, yuqori sifatli video+audio merge qilinadi
    # - ffmpeg yo'q bo'lsa, faqat birlashtirilgan stream (mp4) tanlanadi
    is_youtube = "youtube" in url or "youtu.be" in url

    if is_youtube:
        # Avval ffmpeg bor-yo'qligini tekshirish
        try:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            has_ffmpeg = True
        except Exception:
            has_ffmpeg = False

        if has_ffmpeg:
            # ffmpeg bor: eng yaxshi sifat, video+audio birlashtirish
            fmt = (
                'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]'
                '/bestvideo[height<=720]+bestaudio'
                '/best[height<=720][ext=mp4]'
                '/best[height<=720]'
                '/22/18/best[ext=mp4]/best'
            )
            opts['merge_output_format'] = 'mp4'
        else:
            # ffmpeg yo'q: faqat birlashtirilgan (progressive) stream
            fmt = (
                '22/18'
                '/best[height<=720][ext=mp4]'
                '/best[height<=720]'
                '/best[ext=mp4]'
                '/best'
            )
    else:
        # Boshqa platformalar uchun
        try:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            has_ffmpeg = True
        except Exception:
            has_ffmpeg = False

        if has_ffmpeg:
            fmt = (
                'bestvideo[filesize<48M][ext=mp4]+bestaudio[ext=m4a]'
                '/best[filesize<48M][ext=mp4]'
                '/best[filesize<48M]'
                '/best'
            )
            opts['merge_output_format'] = 'mp4'
        else:
            fmt = (
                'best[filesize<48M][ext=mp4]'
                '/best[filesize<48M]'
                '/best'
            )

    opts.update({
        'format': fmt,
        'outtmpl': output_template,
        'max_filesize': MAX_TELEGRAM_SIZE,
    })
    
    ytdl_err = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                expected_filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(expected_filename)
                mp4_path = f"{base}.mp4"
                
                final_path = mp4_path if os.path.exists(mp4_path) else expected_filename
                
                if not os.path.exists(final_path):
                    dir_name = os.path.dirname(output_template) or "."
                    base_name = os.path.basename(base)
                    found = None
                    if os.path.exists(dir_name):
                        for f in os.listdir(dir_name):
                            if f.startswith(base_name):
                                found = os.path.join(dir_name, f)
                                break
                    if found and os.path.exists(found):
                        final_path = found
                
                if os.path.exists(final_path):
                    filesize = os.path.getsize(final_path)
                    if filesize > MAX_TELEGRAM_SIZE:
                        cleanup_file(final_path)
                        return {
                            'success': False,
                            'error': f"Media hajmi Telegram limitidan ({filesize // (1024*1024)}MB > 50MB) katta."
                        }
                    
                    is_photo = final_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
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
        ytdl_err = e
        logger.warning(f"yt-dlp video ololmadi ({e}), Universal Social Crawler ishga tushmoqda...")

    # --- 100% ISHONCHLI FALLBACK: Universal Social Crawler (Meta datacenter bypass) ---
    crawler_res = _download_via_social_crawler(url, output_template)
    if crawler_res and crawler_res.get('success'):
        return crawler_res

    final_err = ytdl_err if ytdl_err else "Fayl saqlanmadi"
    return {'success': False, 'error': format_user_error(str(final_err))}

async def download_video(url: str, output_template: str) -> Dict[str, Any]:
    """Videoni asinxron oqimda yuklash."""
    return await asyncio.to_thread(_sync_download_video, url, output_template)

def _ffmpeg_to_mp3(input_path: str, output_mp3: str) -> bool:
    """Istalgan media faylni ffmpeg orqali MP3 ga o'tkazadi."""
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', input_path,
             '-vn', '-acodec', 'libmp3lame', '-b:a', '192k',
             '-ar', '44100', output_mp3],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=120,
        )
        return os.path.exists(output_mp3) and os.path.getsize(output_mp3) > 0
    except Exception as e:
        logger.warning(f"ffmpeg MP3 konvert xatosi: {e}")
        return False


def _has_ffmpeg() -> bool:
    """ffmpeg o'rnatilganligini tekshiradi."""
    try:
        subprocess.run(
            ['ffmpeg', '-version'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _sync_download_audio(url: str, output_template: str) -> Dict[str, Any]:
    """
    Audioni MP3 formatda yuklab oladi.
    Strategiya:
      1. yt-dlp + FFmpegExtractAudio → to'g'ridan MP3
      2. Fallback: video yuklab → ffmpeg -vn → MP3
      3. Agar ffmpeg yo'q → yt-dlp bestaudio yuklab saqlanadi
    """
    has_ff = _has_ffmpeg()

    opts = _get_ytdl_common_opts()

    if has_ff:
        # Eng yaxshi yo'l: yt-dlp o'zi audio ajratib MP3 chiqaradi
        opts.update({
            'format': (
                'bestaudio[ext=m4a]/bestaudio[ext=webm]'
                '/bestaudio/best[height<=480]/18/best'
            ),
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'max_filesize': MAX_TELEGRAM_SIZE,
        })
    else:
        # ffmpeg yo'q — faqat audio stream yuklaymiz
        opts.update({
            'format': 'bestaudio[ext=m4a]/bestaudio/18/best',
            'outtmpl': output_template,
            'max_filesize': MAX_TELEGRAM_SIZE,
        })
    
    primary_err = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                expected_filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(expected_filename)
                dir_name = os.path.dirname(output_template) or "."
                base_name = os.path.basename(base)

                # ffmpeg bor: .mp3 fayl hosil bo'ladi (FFmpegExtractAudio qiladi)
                if has_ff:
                    mp3_path = f"{base}.mp3"
                    if not os.path.exists(mp3_path):
                        for f in os.listdir(dir_name):
                            if f.startswith(base_name) and f.endswith('.mp3'):
                                mp3_path = os.path.join(dir_name, f)
                                break
                    if os.path.exists(mp3_path):
                        filesize = os.path.getsize(mp3_path)
                        if filesize > MAX_TELEGRAM_SIZE:
                            cleanup_file(mp3_path)
                            return {
                                'success': False,
                                'error': f"Audio hajmi ({filesize // (1024*1024)}MB > 50MB) Telegram limitidan katta."
                            }
                        return {
                            'success': True,
                            'file_path': mp3_path,
                            'title': info.get('title') or 'Musiqa',
                            'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                            'duration': info.get('duration') or 0,
                            'filesize': filesize
                        }
                else:
                    # ffmpeg yo'q: yuklab olingan faylni (m4a/webm/mp4) topib
                    # ffmpeg orqali konvert qilishga urinamiz (agar keyinchalik o'rnatilsa)
                    raw_path = expected_filename
                    if not os.path.exists(raw_path):
                        for f in sorted(os.listdir(dir_name)):
                            if f.startswith(base_name):
                                raw_path = os.path.join(dir_name, f)
                                break
                    if os.path.exists(raw_path):
                        # Oxirgi urinish: ffmpeg paydo bo'ldimi?
                        if _has_ffmpeg():
                            mp3_path = f"{base}.mp3"
                            if _ffmpeg_to_mp3(raw_path, mp3_path):
                                cleanup_file(raw_path)
                                filesize = os.path.getsize(mp3_path)
                                return {
                                    'success': True,
                                    'file_path': mp3_path,
                                    'title': info.get('title') or 'Musiqa',
                                    'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                                    'duration': info.get('duration') or 0,
                                    'filesize': filesize
                                }
                        # ffmpeg hali ham yo'q: xom faylni qaytaramiz
                        filesize = os.path.getsize(raw_path)
                        return {
                            'success': True,
                            'file_path': raw_path,
                            'title': info.get('title') or 'Musiqa',
                            'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                            'duration': info.get('duration') or 0,
                            'filesize': filesize
                        }
    except Exception as e:
        primary_err = e
        logger.warning(f"yt-dlp audio xatosi ({e}), fallback ishga tushmoqda...")

    # --- FALLBACK: Avval videoni yuklab, keyin MP3 ga o'giramiz ---
    try:
        dir_name = os.path.dirname(output_template) or "."
        raw_name = os.path.basename(output_template)
        clean_prefix = raw_name.replace(".%(ext)s", "").replace("%(ext)s", "").rstrip(".%")

        temp_vid_template = os.path.join(dir_name, f"{clean_prefix}_tempvid.%(ext)s")
        target_mp3 = os.path.join(dir_name, f"{clean_prefix}.mp3")

        vid_res = None

        # 1. YouTube uchun format 18 (progressive, audio+video birlashgan)
        if "youtube" in url or "youtu.be" in url:
            try:
                yt_opts = _get_ytdl_common_opts()
                yt_opts.update({
                    'format': '18/best[height<=480][ext=mp4]/best[ext=mp4]/best',
                    'outtmpl': temp_vid_template,
                })
                with yt_dlp.YoutubeDL(yt_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        exp = ydl.prepare_filename(info)
                        base, _ = os.path.splitext(exp)
                        cand = None
                        for ext in ('.mp4', '.webm', '.m4a', ''):
                            test = f"{base}{ext}" if ext else exp
                            if os.path.exists(test):
                                cand = test
                                break
                        if not cand:
                            for f in os.listdir(dir_name):
                                if f.startswith(os.path.basename(base)):
                                    cand = os.path.join(dir_name, f)
                                    break
                        if cand and os.path.exists(cand):
                            vid_res = {
                                'success': True,
                                'file_path': cand,
                                'title': info.get('title') or 'Musiqa',
                                'uploader': info.get('uploader') or info.get('channel') or "Noma'lum",
                                'duration': info.get('duration') or 0
                            }
            except Exception as yt_err:
                logger.warning(f"YouTube fallback audio xatosi: {yt_err}")

        # 2. Boshqa platformalar uchun umumiy video yuklash
        if not vid_res or not vid_res.get('success'):
            vid_res = _sync_download_video(url, temp_vid_template)

        # 3. Social Crawler (Meta/Instagram fallback)
        if not vid_res or not vid_res.get('success'):
            vid_res = _download_via_social_crawler(url, temp_vid_template)

        if vid_res and vid_res.get('success') and vid_res.get('file_path'):
            vid_path = vid_res['file_path']

            # ffmpeg bilan MP3 chiqarish
            if _has_ffmpeg():
                ok = _ffmpeg_to_mp3(vid_path, target_mp3)
                cleanup_file(vid_path)
                if ok and os.path.exists(target_mp3):
                    filesize = os.path.getsize(target_mp3)
                    return {
                        'success': True,
                        'file_path': target_mp3,
                        'title': vid_res.get('title') or 'Musiqa',
                        'uploader': vid_res.get('uploader') or "Noma'lum",
                        'duration': vid_res.get('duration') or 0,
                        'filesize': filesize
                    }
            else:
                # ffmpeg yo'q: xom faylni qaytaramiz
                filesize = os.path.getsize(vid_path)
                return {
                    'success': True,
                    'file_path': vid_path,
                    'title': vid_res.get('title') or 'Musiqa',
                    'uploader': vid_res.get('uploader') or "Noma'lum",
                    'duration': vid_res.get('duration') or 0,
                    'filesize': filesize
                }
    except Exception as fallback_err:
        logger.error(f"Fallback audio ajratishda xatolik: {fallback_err}")

    final_err = primary_err if primary_err else "Audio faylni yaratib bo'lmadi"
    return {'success': False, 'error': format_user_error(str(final_err))}

def _sync_search_music(query: str, limit: int = 4) -> list[Dict[str, Any]]:
    """Matn bo'yicha audio treklarni qidiradi."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    results = []
    search_query = f"ytsearch{limit}:{query}"
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

async def download_audio(url: str, output_template: str) -> Dict[str, Any]:
    """Audioni asinxron oqimda yuklash."""
    return await asyncio.to_thread(_sync_download_audio, url, output_template)

def cleanup_file(filepath: Optional[str]) -> None:
    """Faylni diskdan butunlay o'chirib tashlaydi (HDD to'lib qolmasligi uchun)."""
    if not filepath:
        return
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Vaqtinchalik fayl tozalandi: {filepath}")
    except Exception as e:
        logger.warning(f"Faylni o'chirishda xatolik ({filepath}): {e}")
