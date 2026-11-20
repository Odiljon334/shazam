# TODO_PLAN: Universal Media Downloader & Emotsional Yangilanish

Maqsad:
1. Instagram (post, stories, reels), YouTube (video, shorts, audio), TikTok (suv belgisiz), Facebook (reels, rasm), Pinterest (rasm, video), Snapchat (rasm, video), Telegram (hikoya/post) qo'llab-quvvatlash.
2. Rasm va video formatlarini avtomatik aniqlash (rasm bo'lsa rasm, video bo'lsa video, audio so'ralsa MP3).
3. Bot xabarlariga to'liq jonli, emotsional, jalb qiluvchi va professional ruh berish.
4. Render keep-alive (sleep mode) ni saqlash va test qilib GitHub ga push qilish.

---

## Bosqichlar:

- [x] **1-bosqich: Platformalar va Media turlarini kengaytirish (`downloader.py`)**
  - [x] `URL_REGEX` ga `snapchat.com` va `t.me` havolalarini qo'shish
  - [x] Rasm va video formatlarini avtomatik ajratuvchi universal media yuklagich (`download_media`) yaratish
  - [x] Pinterest, Facebook, Instagram rasmlarini to'g'ridan-to'g'ri yuklab olish
  - [x] YouTube uchun Video va Audio (MP3) imkoniyatini ta'minlash
  - [x] Telegram ochiq hikoya va postlaridan media ajratish (tg web preview)

- [x] **2-bosqich: Emotsional va Chiroyli Matnlar & UX (`bot.py`)**
  - [x] Start xabarini emotsional, samimiy va to'liq ro'yxat bilan yangilash
  - [x] Yuklash jarayoni xabarlarini jonli qilish (Yuklanmoqda... Tayyorlanmoqda... Yuborilmoqda...)
  - [x] Har bir media ostiga chiroyli emotsional tavsif va `[🎵 Musiqasini olish (MP3)]` tugmasi
  - [x] Noto'g'ri yoki tushunarsiz xabarlarga jonli, yordam beruvchi javoblar

- [x] **3-bosqich: Amaliy Testlar (Verification)**
  - [x] Instagram (video/rasm) testi
  - [x] YouTube (video/audio) testi
  - [x] TikTok va Pinterest testi
  - [x] Snapchat va Telegram havolalari testi
  - [x] `test_suite.py` ni yangilab to'liq yurgizish (6/6 yashil)

- [x] **4-bosqich: GitHub ga Push va Renderga Chiqarish**
  - [x] `bot.py`, `downloader.py`, `test_suite.py`, `TODO_PLAN.md` push qilindi (`c29857a`)
