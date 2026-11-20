import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import downloader

async def run_tests():
    print("========================================")
    print("▶️ 1. URL Aniqlash Testi (Barcha Platformalar)")
    print("========================================")
    test_urls = [
        ("https://www.instagram.com/reel/Cx123456789/", True),
        ("https://www.instagram.com/stories/billieeilish/1234567890123456789/", True),
        ("https://vt.tiktok.com/ZS2345678/", True),
        ("https://vm.tiktok.com/ZM8765432/", True),
        ("https://youtu.be/jNQXAC9IVRw", True),
        ("https://www.youtube.com/shorts/123456789", True),
        ("https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYb", True),
        ("https://t.me/telegram/100", True),
        ("https://pin.it/1234567", True),
        ("https://www.facebook.com/reel/123456789", True),
        ("Salom mana bu video https://www.youtube.com/watch?v=jNQXAC9IVRw juda zo'r", True),
        ("Oddiy matn havola yo'q", False),
        ("https://google.com/search?q=test", False),
    ]
    for text, should_find in test_urls:
        found = downloader.find_supported_url(text)
        assert (found is not None) == should_find, f"Xato: {text} -> {found}"
        print(f"  [OK] '{text[:45]}...' -> {found}")

    print("\n========================================")
    print("▶️ 2. Metadata Olish Testi")
    print("========================================")
    sample_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    info = await downloader.extract_info(sample_url)
    assert info is not None, "Metadata olinmadi!"
    assert "title" in info and info["title"], "Sarlavha yo'q!"
    print(f"  [OK] Sarlavha: {info['title']}")
    print(f"  [OK] Muallif:  {info['uploader']}")
    print(f"  [OK] Davomiyligi: {info['duration']} soniya")

    print("\n========================================")
    print("▶️ 3. Video Yuklash va Auto-Cleanup Testi")
    print("========================================")
    vid_tmpl = str(config.DOWNLOAD_DIR / "verify_vid.%(ext)s")
    vid_res = await downloader.download_video(sample_url, vid_tmpl)
    assert vid_res["success"] is True, f"Video yuklashda xato: {vid_res.get('error')}"
    vid_path = vid_res["file_path"]
    assert os.path.exists(vid_path), "Video fayli diskda topilmadi!"
    print(f"  [OK] Video muvaffaqiyatli saqlandi: {vid_path} ({vid_res['filesize']} bayt)")
    
    # Tozalash
    downloader.cleanup_file(vid_path)
    assert not os.path.exists(vid_path), "Video fayli o'chirilmadi!"
    print("  [OK] Video diskdan muvaffaqiyatli tozalandi.")

    print("\n========================================")
    print("▶️ 4. Audio (MP3) Yuklash Testi")
    print("========================================")
    aud_tmpl = str(config.DOWNLOAD_DIR / "verify_aud.%(ext)s")
    aud_res = await downloader.download_audio(sample_url, aud_tmpl)
    assert aud_res["success"] is True, f"Audio yuklashda xato: {aud_res.get('error')}"
    aud_path = aud_res["file_path"]
    assert os.path.exists(aud_path), "Audio fayli diskda topilmadi!"
    assert aud_path.endswith(".mp3"), f"Audio fayl .mp3 emas: {aud_path}"
    print(f"  [OK] Audio muvaffaqiyatli saqlandi: {aud_path} ({aud_res['filesize']} bayt)")
    downloader.cleanup_file(aud_path)
    assert not os.path.exists(aud_path), "Audio fayli o'chirilmadi!"
    print("  [OK] Audio diskdan muvaffaqiyatli tozalandi.")

    print("\n========================================")
    print("▶️ 5. Instagram Video Fallback / Crawler Testi")
    print("========================================")
    insta_url = "https://www.instagram.com/reel/CU5kYd6Aioa/"
    insta_tmpl = str(config.DOWNLOAD_DIR / "verify_insta_vid.%(ext)s")
    insta_res = await downloader.download_video(insta_url, insta_tmpl)
    assert insta_res["success"] is True, f"Instagram video xatosi: {insta_res.get('error')}"
    insta_path = insta_res["file_path"]
    assert os.path.exists(insta_path), "Instagram video saqlanmadi!"
    print(f"  [OK] Instagram video saqlandi: {insta_path} ({insta_res['filesize']} bayt)")
    downloader.cleanup_file(insta_path)
    assert not os.path.exists(insta_path), "Instagram video o'chirilmadi!"
    print("  [OK] Instagram video tozalandi.")

    print("\n========================================")
    print("▶️ 6. Telegram / Rasm (Photo) Crawler Testi")
    print("========================================")
    tg_url = "https://t.me/telegram/100"
    tg_tmpl = str(config.DOWNLOAD_DIR / "verify_tg_photo.%(ext)s")
    tg_res = await downloader.download_video(tg_url, tg_tmpl)
    assert tg_res["success"] is True, f"Telegram rasm xatosi: {tg_res.get('error')}"
    assert tg_res.get("media_type") == "photo", f"Media type photo emas: {tg_res}"
    tg_path = tg_res["file_path"]
    assert os.path.exists(tg_path), "Telegram rasm fayli saqlanmadi!"
    print(f"  [OK] Rasm muvaffaqiyatli saqlandi: {tg_path} ({tg_res['filesize']} bayt)")
    downloader.cleanup_file(tg_path)
    assert not os.path.exists(tg_path), "Telegram rasm fayli o'chirilmadi!"
    print("  [OK] Rasm tozalandi.")

    print("\n========================================")
    print("▶️ 7. Resilient Architecture & YouTube Fallback Unit Testlari")
    print("========================================")
    import unittest
    import test_resilient_downloader
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_resilient_downloader)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    assert result.wasSuccessful(), f"Unit testlarda xatolik: {len(result.failures)} ta failure, {len(result.errors)} ta error"
    print("  [OK] Barcha mock, fallback, error-classification va cookie testlari muvaffaqiyatli!")

    print("\n========================================")
    print("🎉 BARCHA AMALIY VA BIRLIK TESTLARI MUVAFFAQITYATLI O'TDI!")
    print("========================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
