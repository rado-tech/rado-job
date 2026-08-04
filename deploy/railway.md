# Railway'ga joylash

Boshlang'ich bosqich uchun. Foydalanuvchi ko'paygach VPS'ga o'tasiz —
o'tish oson, chunki hamma ma'lumot bitta papkada.

---

## ⚠️ Eng muhim qadam: VOLUME

Railway konteynerni har deploy'da noldan yaratadi. **Volume ulamasangiz
baza, zaxiralar va jurnal har yangilanishda o'chib ketadi.**

Volume ulash **majburiy**. Uni o'tkazib yubormang.

---

## Qadamlar

### 1. Kodni GitHub'ga yuklang

```bash
git init
git add .
git commit -m "Rado Job bot"
git branch -M main
git remote add origin https://github.com/USERNAME/rado-job.git
git push -u origin main
```

`.gitignore` da `.env`, baza va zaxiralar bor — ular yuklanmaydi. To'g'ri.

### 2. Railway'da loyiha yarating

[railway.app](https://railway.app) → **New Project** →
**Deploy from GitHub repo** → repozitoriyani tanlang.

Railway `railway.json` va `Procfile` ni o'zi topadi va `python -m bot`
buyrug'i bilan ishga tushiradi.

### 3. Volume qo'shing (majburiy!)

Servis sahifasida → **Settings** → **Volumes** → **Add Volume**

- **Mount path:** `/data`
- Hajmi: 1 GB yetarli (baza bir necha MB bo'ladi)

### 4. Muhit o'zgaruvchilari

**Variables** bo'limiga qo'shing:

```
BOT_TOKEN=8980062173:AAF...
ADMIN_IDS=5796648371
DATA_DIR=/data
TZ=Asia/Tashkent
```

`DATA_DIR=/data` — eng muhim qator. Shundan keyin baza, zaxiralar va
jurnal Volume ichida saqlanadi va deploy'lardan omon qoladi.

`DB_URL` ni **yozmang** — bot o'zi `/data/rado_job.db` ni tanlaydi.

### 5. Ishga tushiring

Deploy tugagach Telegramda sizga xabar keladi:

> 🟢 Bot ishga tushdi.

Kelmasa: **Deployments** → **View Logs** dan xatoni ko'ring.

---

## Kundalik zaxira

Bot har kuni tunda soat 04:00 (Toshkent vaqti) da bazadan nusxa oladi va
uni **Telegram orqali sizga fayl qilib yuboradi**. Kuniga faqat bir marta —
bot bir necha marta qayta ishga tushsa ham takror yubormaydi.

Bundan tashqari:
- **To'xtashdan oldin** ham nusxa oladi (Railway konteynerni o'chirganda)
- **Ishga tushganda** oxirgi nusxa 20 soatdan eski bo'lsa darhol oladi
- **Sxema o'zgarishidan oldin** avtomat nusxa

**Telegramga kelgan fayllarni o'chirmang.** Volume yo'qolsa ham ular
bilan hamma narsani tiklaysiz.

Qo'lda olish: `⚙️ Sozlamalar` → `💾 Zaxira nusxa` yoki `/backup`.

---

## Tiklash

Railway konsolida (**Settings → Deploy → Custom Start Command** vaqtincha
o'zgartirib) yoki mahalliy kompyuterda:

```bash
# Telegramdagi zaxira faylini yuklab oling, keyin:
python restore.py rado_job-20260804-0400.db
```

Mahalliy tiklab, `rado_job.db` ni Railway Volume'ga yuklash eng oson yo'l.

---

## Railway'ning cheklovlari (bilib turing)

| Muammo | Ta'siri |
|---|---|
| Volume'siz fayl tizimi vaqtinchalik | **Baza o'chadi** — shuning uchun Volume majburiy |
| Bepul kredit tugaydi | Bot to'xtaydi. Narxlarni saytdan tekshiring |
| Konteyner tez-tez qayta ishga tushadi | Bot chidaydi, lekin qisqa uzilishlar bo'ladi |
| Chiquvchi trafik hisoblanadi | Ko'p reklama tarqatsangiz kredit tez tugaydi |

Bot to'xtab qolsa, qayta ishga tushganda sizga **qancha vaqt o'chib
turgani** haqida xabar keladi — ya'ni jimgina yo'qolib qolmaydi.

---

## VPS'ga o'tish (keyinroq)

Ko'chirish oddiy, chunki hamma ma'lumot bitta papkada:

1. Telegramdan oxirgi zaxira faylini yuklab oling
2. VPS'da kodni klonlang, `.venv` yarating, `pip install -r requirements.txt`
3. `.env` faylini yarating (`DATA_DIR=.` yoki `/var/lib/rado-job`)
4. `python restore.py <zaxira-fayl>`
5. `deploy/rado-job.service` ni o'rnating

Kodning bironta qatorini o'zgartirish kerak emas.
