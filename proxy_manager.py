"""
Proxy Manager — Avtomatik Proxy Yig'uvchi va Tekshiruvchi Tizim (Reja B)
Render bulut muhitidagi YouTube bloklaridan (403 / bot wall) qochish uchun
dinamik aylanuvchi proksilar havzasini (pool) boshqaradi.
"""

import os
import time
import random
import logging
import urllib.request
import urllib.error
import concurrent.futures
from typing import Optional, List, Set

logger = logging.getLogger("chaqqon_bot.proxy_manager")

PROXY_SOURCES = [
    "https://cdn.jsdelivr.net/gh/officialputuid/KangProxy@main/https/https.txt",
    "https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/http.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=3500&country=all&ssl=yes&anonymity=all",
]

CHECK_URL = "https://www.google.com/generate_204"
CACHE_TTL = 600  # 10 daqiqa kesh

_verified_proxies: List[str] = []
_last_scrape_time: float = 0.0
_failed_proxies: Set[str] = set()


def get_static_proxy() -> Optional[str]:
    """
    Agar atrof-muhit o'zgaruvchilarida (masalan, Webshare yoki xususiy proxy)
    ko'rsatilgan bo'lsa, uni eng birinchi navbatda qaytaradi.
    """
    for var in ("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY", "YTDL_PROXY"):
        val = os.getenv(var)
        if val and val.strip():
            return val.strip()
    return None


def _check_single_proxy(proxy_str: str, timeout: float = 3.0) -> Optional[str]:
    """Bitta proksini Google/YouTube HTTPS SSL CONNECT orqali tekshirish."""
    clean_proxy = proxy_str.strip()
    if not clean_proxy.startswith("http"):
        clean_proxy = f"http://{clean_proxy}"

    proxy_handler = urllib.request.ProxyHandler({'http': clean_proxy, 'https': clean_proxy})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        req = urllib.request.Request(
            CHECK_URL,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with opener.open(req, timeout=timeout) as resp:
            if resp.status in (204, 200):
                return clean_proxy
    except Exception:
        pass
    return None


def scrape_and_validate_proxies(max_needed: int = 10, batch_size: int = 40) -> List[str]:
    """Ochiq manbalardan yangi proksilarni yig'ib, ishlaydiganlarini aniqlaydi."""
    global _verified_proxies, _last_scrape_time, _failed_proxies
    now = time.time()

    # Kesh muddati o'tmagan bo'lsa va ro'yxat bo'sh bo'lmasa
    if _verified_proxies and (now - _last_scrape_time < CACHE_TTL):
        return _verified_proxies

    logger.info("Proxy Scraper: Yangi HTTPS proksilar qidirilmoqda...")
    raw_candidates: Set[str] = set()

    for src in PROXY_SOURCES:
        try:
            req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                lines = resp.read().decode('utf-8', errors='ignore').splitlines()
                for line in lines:
                    line = line.strip()
                    if line and ":" in line and line not in _failed_proxies:
                        raw_candidates.add(line)
                    if len(raw_candidates) >= 150:
                        break
        except Exception as e:
            logger.debug(f"Proxy manbasi xatosi ({src}): {e}")

    if not raw_candidates:
        logger.warning("Proxy Scraper: Birorta ham nomzod proxy topilmadi.")
        return []

    candidates_list = list(raw_candidates)
    random.shuffle(candidates_list)
    test_batch = candidates_list[:batch_size]

    valid_proxies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(_check_single_proxy, p, 3.0): p for p in test_batch}
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res:
                    valid_proxies.append(res)
                    if len(valid_proxies) >= max_needed:
                        break
            except Exception:
                pass

    logger.info(f"Proxy Scraper: {len(test_batch)} tadan {len(valid_proxies)} ta ishlaydigan HTTPS proxy topildi.")
    _verified_proxies = valid_proxies
    _last_scrape_time = now
    return _verified_proxies


def get_working_proxy() -> Optional[str]:
    """Ishlaydigan faol proksini qaytaradi (avval statik, keyin havzadan)."""
    static_p = get_static_proxy()
    if static_p:
        return static_p

    proxies = scrape_and_validate_proxies()
    if proxies:
        return random.choice(proxies)
    return None


def get_verified_count() -> int:
    return len(_verified_proxies)


def report_proxy_failure(proxy_url: Optional[str]) -> None:
    """Xato bergan proksini qora ro'yxatga kiritadi va havzadan o'chiradi."""
    global _verified_proxies, _failed_proxies
    if not proxy_url:
        return

    _failed_proxies.add(proxy_url)
    clean = proxy_url.replace("http://", "").replace("https://", "")
    _failed_proxies.add(clean)

    if proxy_url in _verified_proxies:
        _verified_proxies.remove(proxy_url)
    logger.debug(f"Proxy ishlamay qoldi va o'chirildi: {proxy_url}")
