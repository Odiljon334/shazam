import os
import sys
import base64
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import downloader
from downloader import DownloadErrorKind, classify_error, format_user_error

class TestResilientDownloader(unittest.TestCase):

    def setUp(self):
        self.test_dir = config.DOWNLOAD_DIR
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def test_error_classification(self):
        """1. Xatoliklarni tasniflash va Telegram xabarlari testi."""
        # 1.1 Bot detection & 403
        kind, msg = classify_error("HTTP Error 403: Forbidden: Sign in to confirm you're not a bot")
        self.assertEqual(kind, DownloadErrorKind.BOT_BLOCKED)
        self.assertIn("YouTube Xizmati Vaqtincha Band", msg)
        self.assertIn("403 Blok", msg)

        # 1.2 Timeout
        kind, msg = classify_error("Connection timed out after 15 seconds")
        self.assertEqual(kind, DownloadErrorKind.TIMEOUT)
        self.assertIn("Tarmoq Xatoligi", msg)

        # 1.3 Unavailable / Restricted
        kind, msg = classify_error("Video unavailable: This video is private")
        self.assertEqual(kind, DownloadErrorKind.UNAVAILABLE_OR_RESTRICTED)
        self.assertIn("Video Mavjud Emas", msg)

        # 1.4 File size limit
        kind, msg = classify_error("Media hajmi Telegram limitidan (55MB > 50MB) katta.")
        self.assertEqual(kind, DownloadErrorKind.FILE_TOO_LARGE)
        self.assertIn("Fayl Hajmi Limiti", msg)

    def test_cookie_context_raw_and_b64(self):
        """2. Cookie kontekst menejeri: base64 va raw xavfsiz tozalanishi."""
        # Raw cookie
        test_raw = "# Netscape HTTP Cookie File\n.youtube.com TRUE / FALSE 9999999999 SID unit_test_cookie"
        with patch.dict(os.environ, {"YTDL_COOKIES": test_raw}):
            with config.cookie_file_context() as c_path:
                self.assertIsNotNone(c_path)
                self.assertTrue(os.path.exists(c_path))
                with open(c_path) as f:
                    self.assertIn("unit_test_cookie", f.read())
                saved_path = c_path
            # Contexdan chiqqach fayl tozalanishi shart
            self.assertFalse(os.path.exists(saved_path), "Temp cookie fayli o'chirilmadi!")

        # Base64 cookie
        b64_cookie = base64.b64encode(test_raw.encode()).decode()
        with patch.dict(os.environ, {"YTDL_COOKIES_B64": b64_cookie}):
            with config.cookie_file_context() as c_path:
                self.assertIsNotNone(c_path)
                self.assertTrue(os.path.exists(c_path))
                with open(c_path) as f:
                    self.assertIn("unit_test_cookie", f.read())
                saved_path = c_path
            self.assertFalse(os.path.exists(saved_path), "B64 cookie fayli o'chirilmadi!")

    def test_cleanup_template_artifacts(self):
        """3. Oraliq va chala fayllar (.part, .ytdl, .temp) to'liq tozalanishi testi."""
        tmpl = str(self.test_dir / "unit_test_media_123.%(ext)s")
        prefix = str(self.test_dir / "unit_test_media_123")
        
        part_file = f"{prefix}.mp4.part"
        ytdl_file = f"{prefix}.ytdl"
        temp_file = f"{prefix}_tempvid.mp4"
        final_file = f"{prefix}.mp4"

        for p in (part_file, ytdl_file, temp_file, final_file):
            with open(p, "w") as f:
                f.write("dummy content")
            self.assertTrue(os.path.exists(p))

        # Cleanup chaqirilganda barcha artifactlar yo'qolishi kerak
        downloader.cleanup_template_artifacts(tmpl)

        for p in (part_file, ytdl_file, temp_file, final_file):
            self.assertFalse(os.path.exists(p), f"Artifact fayl tozalanmadi: {p}")

    @patch("yt_dlp.YoutubeDL")
    def test_youtube_fallback_execution(self, mock_ydl_cls):
        """
        4. YouTube ko'p pog'onali Fallback mexanizmi:
           Tier 1 (Primary) 403 block bersa, Tier 2 (TV/mweb) muvaffaqiyatli yakunlanishi.
        """
        yt_url = "https://www.youtube.com/watch?v=mock_video_id"
        out_tmpl = str(self.test_dir / "mock_yt_vid_456.%(ext)s")
        expected_mp4 = str(self.test_dir / "mock_yt_vid_456.mp4")

        # Mock instance context managers:
        # 1-chaqiruv: Exception (403 Bot Detection)
        # 2-chaqiruv: Success
        first_ctx = MagicMock()
        first_ctx.extract_info.side_effect = Exception("HTTP Error 403: Forbidden - Sign in to confirm you're not a bot")
        first_ydl = MagicMock()
        first_ydl.__enter__.return_value = first_ctx

        second_ctx = MagicMock()
        second_ctx.extract_info.return_value = {
            'title': 'Mock Video Title',
            'uploader': 'Mock Channel',
            'duration': 60,
            'width': 1280,
            'height': 720
        }
        second_ctx.prepare_filename.return_value = expected_mp4
        second_ydl = MagicMock()
        second_ydl.__enter__.return_value = second_ctx

        def ydl_side_effect(opts):
            strat_client = opts.get('extractor_args', {}).get('youtube', {}).get('player_client', [])
            if strat_client == ['visionos', 'tv_samsung']:
                return first_ydl
            else:
                with open(expected_mp4, "w") as f:
                    f.write("dummy video data")
                return second_ydl

        mock_ydl_cls.side_effect = ydl_side_effect

        try:
            res = downloader._sync_download_video(yt_url, out_tmpl)
            self.assertTrue(res.get("success"), f"Fallback muvaffaqiyatli bo'lmadi: {res}")
            self.assertEqual(res.get("title"), "Mock Video Title")
            self.assertEqual(res.get("file_path"), expected_mp4)
            self.assertTrue(os.path.exists(expected_mp4))
        finally:
            downloader.cleanup_file(expected_mp4)

    @patch("yt_dlp.YoutubeDL")
    def test_youtube_secondary_provider_hook(self, mock_ydl_cls):
        """
        5. Secondary Provider Hook testi:
           Barcha yt-dlp strategiyalari 403 blok olganda, secondary provider hook ishga tushishi.
        """
        yt_url = "https://www.youtube.com/watch?v=all_blocked_id"
        out_tmpl = str(self.test_dir / "mock_sec_789.%(ext)s")
        target_file = str(self.test_dir / "mock_sec_789.mp4")

        # Barcha yt-dlp urinishlari xato bersin
        failing_ctx = MagicMock()
        failing_ctx.extract_info.side_effect = Exception("403 Forbidden: Blocked by bot guard")
        failing_ydl = MagicMock()
        failing_ydl.__enter__.return_value = failing_ctx
        mock_ydl_cls.return_value = failing_ydl

        # Mock secondary provider
        mock_provider = MagicMock()
        with open(target_file, "w") as f:
            f.write("secondary provider video content")
        mock_provider.download_video.return_value = {
            'success': True,
            'file_path': target_file,
            'title': 'Secondary Hook Video',
            'uploader': 'Fallback Provider',
            'duration': 120,
            'filesize': len("secondary provider video content")
        }

        downloader.set_secondary_provider(mock_provider)
        try:
            res = downloader._sync_download_video(yt_url, out_tmpl)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("title"), "Secondary Hook Video")
            mock_provider.download_video.assert_called_once_with(yt_url, out_tmpl)
        finally:
            downloader.set_secondary_provider(None)
            downloader.cleanup_file(target_file)

    @patch("yt_dlp.YoutubeDL")
    def test_max_file_size_guard(self, mock_ydl_cls):
        """
        6. Telegram 50MB limiti nazorati:
           50MB dan katta fayllar rad etilishi va zudlik bilan diskdan o'chirilishi.
        """
        yt_url = "https://www.youtube.com/watch?v=large_video"
        out_tmpl = str(self.test_dir / "large_vid_test.%(ext)s")
        large_file = str(self.test_dir / "large_vid_test.mp4")

        # 55MB virtual fayl yaratish
        with open(large_file, "wb") as f:
            f.seek(55 * 1024 * 1024 - 1)
            f.write(b"\0")

        ctx = MagicMock()
        ctx.extract_info.return_value = {'title': 'Huge 4K Video'}
        ctx.prepare_filename.return_value = large_file
        ydl_mock = MagicMock()
        ydl_mock.__enter__.return_value = ctx
        mock_ydl_cls.return_value = ydl_mock

        res = downloader._sync_download_video(yt_url, out_tmpl)
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error_kind"), DownloadErrorKind.FILE_TOO_LARGE.value)
        # Fayl diskdan zudlik bilan o'chirilgan bo'lishi kerak
        self.assertFalse(os.path.exists(large_file), "Katta hajmli fayl diskdan o'chirilmadi!")

if __name__ == "__main__":
    unittest.main()
