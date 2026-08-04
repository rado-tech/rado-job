# Rado Job — kunlik ish topish boti

Admin yoki ish beruvchi e'lon joylaydi → ishchilar yozilish to'lovini qilib chek
yuboradi → admin bir tugma bilan tasdiqlaydi → ishchiga ish manzili avtomat
boradi. Joylar to'lganda e'lon o'zi yopiladi, joy bo'shasa navbatdagi odam
chaqiriladi.

---

## Tez boshlash

```bash
.venv\Scripts\python.exe -m bot
```

`.env` da faqat 3 narsa kerak:

```
BOT_TOKEN=...        <- @BotFather bergan token
ADMIN_IDS=123456789  <- sizning Telegram ID (@userinfobot dan)
DB_URL=sqlite+aiosqlite:///./rado_job.db
```

**Qolgan hamma narsa bot ichida sozlanadi:** `🛠 Admin` → `⚙️ Sozlamalar`.
Kanal, moderatsiya chati, karta raqami, to'lov summasi, bron muddati —
hammasi o'sha yerda, botni qayta ishga tushirmasdan.

---

## Birinchi sozlash (5 daqiqa)

Botga `/start` → `🛠 Admin` → `⚙️ Sozlamalar`:

**0. 🆓 Bepul rejim** — yoqilgan holda keladi. Karta rekvizitisiz ham
bugunoq ishga tushirasiz: e'lonlar bepul bo'ladi, odam yig'asiz. Pulli
rejimga keyin bir tugma bilan o'tasiz.

**1. 💳 Karta raqami va 👤 Karta egasi** — pulli rejimga o'tishdan oldin
to'ldirilishi shart (bot o'zi tekshiradi).

**2. 📢 Kanallar** — bir nechta bo'lishi mumkin
- Botni kanalga **administrator** qilib qo'shing
  (huquqlar: «Xabar joylash» + «Xabarlarni tahrirlash»)
- Bot o'sha zahoti sizga tugma yuboradi: «Shu chatni nima sifatida ishlatamiz?»
- Yoki kanaldan xabarni botga forward qiling / `@kanal_nomi` deb yozing
- Guruh uchun: guruhda `/id` yozing va raqamni yuboring

**3. 👮 Moderatsiya chati** (ixtiyoriy) — cheklar shu yerga tushadi

**4. 🛡 Moderatorlar** (ixtiyoriy) — chek tekshiruvchilar

> ID raqamini qo'lda yozish shart emas. Telegram guruhni supergruppaga
> aylantirganda ID **o'zgaradi** — bot buni o'zi payqab, yangi ID ni
> saqlab qo'yadi.

---

## Bepul va pulli e'lonlar

Ikki daraja boshqaruv:

**1. Global rejim** — `⚙️ Sozlamalar` dagi eng yuqoridagi tugma:

| Rejim | Nima bo'ladi |
|---|---|
| 🆓 **Bepul rejim** | Yangi e'lonlar avtomat bepul. Ishchi «Bepul yozilish» bosishi bilan **darhol** ish manzili va lokatsiyani oladi — chek ham, admin tasdig'i ham, bron muddati ham yo'q |
| 💳 **Pulli rejim** | Yangi e'lonlarda yozilish to'lovi so'raladi |

Rejimni almashtirish **eski e'lonlarga tegmaydi**. Ya'ni bepuldan pulliga
o'tsangiz, hozir joylangan bepul e'lonlar bepulligicha qoladi.

**2. Har bir e'lon alohida:**
- E'lon yaratishda oldindan ko'rishdagi `✏️ To'lov` tugmasi
- Joylangan e'londa `🆓 Bepul qilish` / `💳 Pulli qilish` tugmasi —
  kanaldagi post ham darhol yangilanadi

> Kimdir allaqachon pul to'lagan e'lonning narxi o'zgarmaydi — bot buni
> bloklaydi. Aks holda janjal chiqadi.

**Bepul ishlarda no-show muammosi.** Pul to'lagan odam albatta boradi —
puli ketgan. Bepul bo'lganda bu tiyilish yo'qoladi va odam «yozilib
qo'yaman, borsam boraman» deydi. Shuning uchun `🚷 No-show limiti` bor:
belgilangan martadan ko'p ishga chiqmagan odam **bepul** ishlarga yozila
olmaydi. Pulli ishlarga cheklov qo'llanmaydi — u yerda pul o'zi filtr.

**Tavsiya etilgan yo'l:** bepul rejimda boshlang → auditoriya va ish
beruvchilar to'planadi → pulli rejimga o'ting, lekin vaqti-vaqti bilan
alohida e'lonlarni bepul qoldiring (yangi hudud ochganda, kanal
reklamasida, bayramda).

---

## 🌐 Ikki til

Ishchi birinchi `/start` da tilni tanlaydi: 🇺🇿 O'zbekcha yoki 🇷🇺 Русский.
Keyin istalgan payt `/til` orqali o'zgartiradi.

**Ruschaga ishchi ko'radigan hamma narsa tarjima qilingan:** ro'yxatdan
o'tish, e'lon kartasi, to'lov ko'rsatmasi, eslatmalar, navbat, referal,
shikoyat, tugmalar. **Admin paneli o'zbekcha qoladi** — uni siz va
moderatorlar ishlatasiz.

Texnik jihati: `bot/texts.py` — oddiy modul emas, **proksi**. Undan nima
so'ralsa, joriy foydalanuvchi tiliga mos lug'atdan qaytaradi
(`bot/locales/uz.py`, `bot/locales/ru.py`). Shu tufayli handler'lardagi
`texts.job_card(...)` chaqiruvlarining birortasini o'zgartirish kerak
bo'lmadi.

> ⚠️ Kodda `from bot.texts import money` deb **yozmang** — bu tarjimani
> import paytida qotirib qo'yadi. `from bot import texts` va
> `texts.money(...)` deb yozing. `wiring_test.py` buni avtomat tekshiradi.

Yangi til qo'shish: `bot/locales/` ga fayl qo'shib, `bot/i18n.py` dagi
`LANGS` ga kalit yozasiz. Tarjimasi yo'q matn avtomat o'zbekchaga qaytadi.

---

## 📊 Kunlik hisobot

Har kuni soat **21:00** da xodimlarga keladi. Hoziroq ko'rish: `/hisobot`.

Ichida: yangi foydalanuvchi va e'lonlar, tasdiqlangan/rad etilgan
yozilishlar, **chiqish darajasi** (%), tushum, tekshirilmagan cheklar —
va eng qimmatlisi: **ertangi to'lmagan joylar ro'yxati**.

Soat 21:00 ataylab tanlangan: ertangi e'lonlar to'lgan-to'lmagani shu
paytda aniq bo'ladi va bo'sh joylarni to'ldirishga (reklama tarqatish,
bepul qilish) hali vaqt bor.

---

## Eslatma va davomat

Bot ishchini **uch marta** eslatadi va o'zi so'raydi:

| Qachon | Nima |
|---|---|
| Ish oldingi kuni **20:00** | «Ertaga ishingiz bor» + manzil + lokatsiya |
| Ishgacha **2 soat** qolganda | «Yo'lga chiqing» + manzil |
| Ish boshlangandan **5 soat** keyin | «Ishga chiqdingizmi?» ✅/❌ |

Davomat so'rovi **ikki tomonga** boradi: ishchiga (o'zi javob beradi) va
ish muallifiga (ro'yxat + tugmalar). Muallifning qarori ustun turadi.

Ilgari admin qo'lda belgilashi kerak edi — u esa unutardi va ishonchlilik
ko'rsatkichi o'lik qolardi. Endi o'zi ishlaydi.

**Bekor qilish oynasi.** Ishgacha **3 soatdan kam** qolganda bekor qilish
«ishga chiqmagan» deb yoziladi — lekin odam buni **oldindan ko'radi** va
o'zi tanlaydi. Joy baribir bo'shaydi va navbatdagi chaqiriladi.

> Nega jazolaymiz-u, joyni bo'shatamiz? Chunki aytmasdan kelmaslikdan
> ko'ra, aytib bekor qilish yaxshiroq. Ogohlantirish ko'rsatiladi, lekin
> yo'l yopilmaydi.

Barcha vaqtlar `⚙️ Sozlamalar` da ko'rinadi.

---

## 🎁 Referal — do'st chaqirish

`/dost` → shaxsiy havola. Do'st shu havola orqali kirib **birinchi ishga
yozilsa**, chaqiruvchiga **bepul yozilish bonusi** beriladi.

Bonus pulli e'longa ishlatiladi: e'lon kartasida ikkita tugma chiqadi —
«✅ Yozilish · 10 000» va «🎁 Bonus bilan bepul». Qaysi ishga sarflashni
odam o'zi hal qiladi.

**Soxta akkauntga qarshi:** mukofot ro'yxatdan o'tganda emas, do'st
**haqiqatan ishga yozilganda** beriladi. Telefon raqami majburiy bo'lgani
ustiga bu ikkinchi to'siq.

O'chirish: `referral_reward` ni 0 qiling.

---

## 🆘 Murojaatlar

Ishchi: tasdiqlangan ish kartasida `🆘 Shikoyat` tugmasi yoki `/shikoyat`.

Admin/moderator: `🆘 Murojaatlar` bo'limi — har biriga `✍️ Javob berish`
yoki `✅ Yopish`. Javob to'g'ridan-to'g'ri foydalanuvchiga boradi.

Real pul aylanganda bu majburiy: busiz odam shikoyatini ochiq kanalga
yozadi va obro'ingizga zarar yetadi.

---

## 📣 Reklama tarqatish

`🛠 Admin` → `📣 Reklama` (yoki `/reklama`) — faqat admin uchun.

1. Reklama xabarini botga yuborasiz — matn, rasm, video, rasm+izoh
2. Ixtiyoriy tugma: `Buyurtma berish - https://havola`
3. Auditoriya: 🌍 hamma / 📍 hudud / 🧰 kasb / 📢 kanallar
4. **Oldindan ko'rish** — aynan qanday ko'rinishi va necha kishiga
   borishi, taxminiy vaqt bilan
5. Tasdiqlaysiz → fon rejimida tarqaladi → yakunda hisobot

Xabar **nusxalanadi**, forward qilinmaydi — «Forwarded from» yozuvi
chiqmaydi va reklama tabiiy ko'rinadi.

---

## Bir nechta kanal va filtr

Har bir kanalga **hudud** va **kasb** filtri qo'yish mumkin:

| Kanal | Filtr | Nima oladi |
|---|---|---|
| Umumiy kanal | yo'q | barcha e'lonlar |
| Chilonzor ishlari | 📍 Chilonzor | faqat Chilonzor |
| Yuk tashish guruhi | 🧰 Yuk tashish | faqat yuk tashish |

**Nega filtr muhim?** Filtrsiz 5 ta kanalda turgan odam bitta e'lonni 5 marta
ko'radi va obunani bekor qiladi. Filtr bilan har kanal o'z auditoriyasiga
mos e'lon oladi.

**Yuklama.** Joy to'lganda bot har bir kanaldagi postni alohida tahrirlashi
kerak. Ortiqcha so'rov bo'lmasligi uchun bot **matn barmoq izini** saqlaydi
va o'zgarish bo'lmasa Telegramga umuman murojaat qilmaydi.

**Ishonchlilik.** Bitta kanal ishlamasa qolganlari baribir joylanadi.
Ketma-ket 5 marta xato bergan kanal avtomat to'xtatiladi va sizga xabar
beriladi — bot o'lik kanalga urinib vaqt sarflamaydi.

---

## Huquqlar: admin va moderator

| Amal | Moderator | Admin |
|---|:---:|:---:|
| To'lov cheklarini tasdiqlash/rad etish | ✅ | ✅ |
| E'lon joylash, yopish, takrorlash | ✅ | ✅ |
| Ish beruvchi e'lonini tasdiqlash | ✅ | ✅ |
| Yozilganlar, «ishga chiqdi/chiqmadi» | ✅ | ✅ |
| ⚙️ Sozlamalar (karta, kanallar) | ❌ | ✅ |
| 📊 Moliyaviy statistika | ❌ | ✅ |
| 👥 Foydalanuvchilar, telefon raqamlar | ❌ | ✅ |
| 🚫 Bloklash | ❌ | ✅ |
| 🛡 Moderator tayinlash | ❌ | ✅ |

Moderator qo'shish: `⚙️ Sozlamalar` → `🛡 Moderatorlar` → `➕`, yoki
`/mod 123456789`. U avval botga `/start` yozgan bo'lishi kerak.

`.env` dagi `ADMIN_IDS` — **egalari**. Ularning rolini hech kim tortib
ololmaydi, boshqa admin ham.

---

## Baza va bot to'xtab qolmasligi

### 0. Hamma ma'lumot bitta papkada — `DATA_DIR`

Baza, zaxira nusxalar va jurnal `DATA_DIR` ichiga tushadi:

```
DATA_DIR/
  rado_job.db
  backups/
  logs/
```

| Muhit | Qiymat |
|---|---|
| Mahalliy kompyuter | `DATA_DIR=.` (standart) |
| Railway | `DATA_DIR=/data` (ulangan Volume) |
| VPS | `DATA_DIR=.` yoki `/var/lib/rado-job` |

Bitta joyda bo'lgani uchun ko'chirish oson: shu papkani nusxalasangiz —
hammasi ko'chdi. Railway'da esa uni bitta Volume qilib ulash kifoya.

`DB_URL` ni faqat PostgreSQL ishlatganda yozing.

### 1. Bot qayerda ishlaydi — eng muhim savol

**Noutbukda ishlatmang.** Qopqoq yopilsa, Wi-Fi uzilsa, Windows tunda
yangilanib qayta yuklansa — bot o'ladi va buni hech kim bilmaydi.

**Boshlang'ich bosqichda — Railway** (bepul/arzon, tez):
[deploy/railway.md](deploy/railway.md). ⚠️ **Volume ulash majburiy**,
aks holda baza har deploy'da o'chadi.

**Foydalanuvchi ko'paygach — Linux VPS** (~$4-6/oy: Hetzner, Contabo,
DigitalOcean; O'zbekistonda Ahost, Uzcloud). Eng arzon tarif yetarli — bu
bot minglab foydalanuvchida ham 200 MB dan kam RAM ishlatadi.

O'tish oson: Telegramdagi oxirgi zaxirani `restore.py` bilan tiklaysiz,
kodning bironta qatorini o'zgartirmaysiz.

Serverda `deploy/rado-job.service` faylini ishlating:

```bash
sudo cp deploy/rado-job.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rado-job
```

`Restart=always` tufayli dastur qanday sababdan qulasa ham 10 soniyada
o'zi ko'tariladi; `enable` tufayli server qayta yuklansa ham o'zi ishga
tushadi.

Windowsda vaqtincha ishlatmoqchi bo'lsangiz: `deploy/windows-service.md`
(NSSM orqali xizmat qilish).

### 2. Bot to'xtab qolsa — darhol bilasiz

Bot har daqiqada bazaga «men tirikman» belgisini yozadi. Qayta ishga
tushganda o'sha belgiga qarab **qancha vaqt o'chib turganini** hisoblab,
sizga xabar beradi:

> 🟢 Bot ishga tushdi.
> ⚠️ Bundan oldin **3 soat 20 daqiqa** o'chib turgan edi.

Tashqi xizmat, pul, sozlash kerak emas. Har qanday paytda `/health`
yozsangiz: ishlash muddati, baza hajmi, oxirgi zaxira, baza butunligi.

### 3. Zaxira nusxa

**Avtomat:** har kuni tunda 04:00 da bot bazadan nusxa oladi va uni
**Telegram orqali sizga fayl qilib yuboradi** — bepul tashqi zaxira.
Server yonib ketsa ham baza Telegramingizda qoladi. Serverda oxirgi 14 ta
nusxa `backups/` da.

Bot 04:00 da o'chib turgan bo'lsa, ishga tushishi bilan tekshiradi: oxirgi
nusxa 20 soatdan eski bo'lsa darhol yangisini oladi.

**Qo'lda:** `⚙️ Sozlamalar` → `💾 Zaxira nusxa`, yoki `/backup`.

**Sxema o'zgarishidan oldin** ham avtomat zaxira olinadi (`pre-migration`) —
yangilanish xato ketsa qaytadigan joy bo'lsin.

**Nega oddiy fayl nusxasi emas?** Bot ishlab turganda bazaga yozib turiladi
va o'sha paytda ko'chirilgan nusxa yarim yozilgan — ya'ni buzuq — bo'lishi
mumkin. Bot SQLite'ning `VACUUM INTO` buyrug'idan foydalanadi: u tranzaksiya
ichida ishlaydi va **doim butun** nusxa beradi, botni to'xtatmasdan.

### 4. Tiklash

Botni to'xtating (`Ctrl+C`), keyin:

```bash
.venv\Scripts\python.exe restore.py
```

Nusxalar ro'yxatini har birining holati bilan ko'rsatadi. Keyin:

```bash
.venv\Scripts\python.exe restore.py backups\rado_job-20260804-0400.db
```

Skript nusxani **avval tekshiradi** (buzuq bo'lsa tiklamaydi) va hozirgi
bazani **o'chirmaydi** — nomini o'zgartirib chetga oladi.

### 5. Baza buzilishiga qarshi

- **`synchronous=FULL`** — har tranzaksiya diskka kafolatli yoziladi.
  Tok o'chsa ham oxirgi yozuvlar yo'qolmaydi
- **WAL rejimi** — o'qish va yozish bir-birini bloklamaydi
- **Har ishga tushishda `quick_check`** — baza buzilgan bo'lsa darhol
  ogohlantirish keladi. SQLite buzilishi jimgina bo'ladi: xato faqat o'sha
  sahifaga tegilganda, ya'ni oylar keyin chiqadi
- **To'g'ri to'xtash** — `Ctrl+C` da WAL asosiy bazaga ko'chiriladi va
  ulanishlar yopiladi
- **`.gitignore`** da baza bor — tasodifan git'ga tushmaydi
- **Avtomat sxema yangilash** — yangi funksiyada baza o'chirilmaydi

---

## Kim nima qila oladi

### Ishchi
| Tugma | Nima qiladi |
|---|---|
| `🔎 Ish qidirish` | Hudud / ish turi / kun bo'yicha filtr, sahifalash |
| `✅ Yozilish` | Joyni bron qiladi, karta rekvizitlarini beradi |
| `⏳ Navbatga yozilish` | To'lgan e'longa **bepul** navbat |
| `📋 Mening ishlarim` | Barcha arizalar va ularning holati |
| `/kasb` | Qiziqishlar — faqat shu turdagi e'lonlar haqida xabar keladi |
| `/dost` | Do'st chaqirib **bepul yozilish bonusi** olish |
| `/shikoyat` | Muammo yoki savol — adminga boradi |
| `/til` | 🇺🇿 O'zbekcha / 🇷🇺 Русский |
| `/xabar` | Xabarnomani yoqish/o'chirish |

### Ish beruvchi
| Tugma | Nima qiladi |
|---|---|
| `➕ E'lon berish` | E'lon yaratadi va adminga tasdiqqa yuboradi |
| `📢 E'lonlarim` | O'z e'lonlari, tasdiqlangan ishchilar ro'yxati va telefonlari |

### Admin
| Tugma / buyruq | Nima qiladi |
|---|---|
| `➕ Yangi e'lon` / `/newjob` | E'lon yaratadi va darhol joylaydi |
| `💳 To'lovlar` / `/pending` | Tekshirilmagan cheklarni qayta yuboradi |
| `🕓 Tasdiq kutayotgan e'lonlar` / `/review` | Ish beruvchilar yuborgan e'lonlar |
| `📢 Barcha e'lonlar` / `/jobs` | Ro'yxat, yozilganlar, yopish/ochish, takrorlash |
| `📊 Statistika` / `/stats` | Foydalanuvchi, e'lon, tushum |
| `📣 Reklama` / `/reklama` | Reklamani hamma yoki tanlangan guruhga tarqatish |
| `👥 Foydalanuvchilar` / `/users` | ID yoki @username bo'yicha qidirish |
| `/block 123456789` | Bloklash / blokni ochish |
| `⚙️ Sozlamalar` / `/sozlama` | Kanal, karta, summalar |
| `/cancel` | Istalgan jarayonni bekor qilish |

---

## E'lon berishni tezlashtiruvchi narsalar

**♻️ Takrorlash.** Har qanday e'lonni ochib `♻️ Takrorlash` bosing — faqat
sana so'raladi, qolgani o'zgarmaydi. Kunlik ishlar takrorlanadi, shuning
uchun bu eng ko'p vaqt tejaydigan tugma: 10 qadam o'rniga 2 bosish.

**Tugmalar.** Vaqt, ish haqi, kishi soni, sana, to'lov — hammasi tayyor
tugmalarda. Qo'lda yozish faqat matn maydonlarida.

**✏️ Tuzatish.** Oldindan ko'rishda har bir maydonning tuzatish tugmasi bor.
Bitta xato uchun butun jarayonni qaytadan boshlash shart emas.

**Ikki qismli oldindan ko'rish.** «Hamma ko'radigan» va «faqat to'laganlar
ko'radigan» qismlar alohida ko'rsatiladi — manzilni ochiq tavsifga yozib
yuborish xatosi shu yerda ushlanadi.

---

## Ishlash mantiqi

**Bron (hold).** «Yozilish» bosilishi bilan joy belgilangan muddatga
(standart 15 daqiqa) band bo'ladi. Chek kelmasa bot joyni avtomat bo'shatadi
va ishchiga xabar beradi.

**Navbat (waitlist).** E'lon to'lganda `⏳ Navbatga yozilish` chiqadi — bepul,
joy egallamaydi. Kimningdir broni tugasa, cheki rad etilsa yoki o'zi bekor
qilsa — navbatdagi **birinchi** odamga avtomat xabar ketadi va unga qisqaroq
muddat (standart 10 daqiqa) beriladi. Ulgurmasa keyingisiga o'tadi.
Natijada: bo'sh joy zoye ketmaydi va ortiqcha to'lov ham bo'lmaydi.

**Ortiqcha sotilmaydi.** 5 ta joyga 6-chi odam yozila olmaydi. Bir vaqtda
o'nlab odam bossa ham faqat bo'sh joy soniga teng odam o'tadi.

**Avtomat TO'LDI.** Joylar to'lganda kanaldagi post o'zi tahrirlanadi.
Joy bo'shasa post qayta ochiladi. Admin qo'lda hech narsa yozmaydi.

**Maxfiy ma'lumot va lokatsiya.** Manzil, mas'ul odam, telefon va
**xaritadagi nuqta** faqat to'lovi tasdiqlangan ishchiga yuboriladi.
Lokatsiya alohida xabar bo'lib boradi — ishchi uni bosib «Marshrut» ola
oladi. E'lon yaratishda 📎 → Location orqali qo'shiladi, ixtiyoriy.

**Ishonchlilik.** Ish tugagach `👥 Yozilganlar` dan har bir ishchini
`✅ Ishga chiqdi` / `🚷 Chiqmadi` deb belgilaysiz. Keyingi safar chekni
tasdiqlashda adminga «3/5 ishga chiqqan» deb ko'rsatiladi.

---

## Xavfsizlik

**Botni istalgan odam o'z guruhiga qo'sha oladi — bu Telegramda oldini
olib bo'lmaydi.** Shuning uchun bot shunday qurilgan:

- **Bot faqat SHAXSIY yozishmada javob beradi.** Guruhda hech qanday
  buyruqqa javob bermaydi. Yagona istisno — `/id` (u maxfiy narsa ochmaydi
  va sozlash uchun kerak).
- **E'lonlar faqat sozlamalardagi BITTA kanalga** ketadi. Boshqa kanalga
  hech qachon joylanmaydi.
- **Cheklar faqat sozlamalardagi moderatsiya chatiga** yoki
  `ADMIN_IDS` dagi odamlarga shaxsan boradi.
- **Guruhdagi tugmalar faqat adminlar uchun** ishlaydi. E'lon kartasi
  begona guruhga forward qilinsa, «Yozilish» tugmasi u yerda ishlamaydi —
  to'lov rekvizitlari guruhga tushmaydi.
- **Kanal/moderatsiya chatini o'zgartirish** faqat `ADMIN_IDS` dagi odam
  qo'lidan keladi.
- **Begona odam botni biror chatga qo'shsa**, sizga xabar keladi va
  «🚪 Chatdan chiqarish» tugmasi beriladi.
- **Bot ishlatilayotgan kanaldan chiqarib yuborilsa**, darhol ogohlantirish
  keladi.
- Foydalanuvchi kiritgan matn HTML sifatida ekranlanadi — tavsifga teg
  yozib formatlashni buzib bo'lmaydi.

Tekshirish uchun: botni sinov guruhiga qo'shing va u yerda `/sozlama`,
`/stats`, `/users` yozib ko'ring — javob kelmasligi kerak.

---

## Minglab foydalanuvchi uchun qilingan ishlar

- **Tarqatish**: sekundiga 25 xabar, to'plamlab parallel. Telegram cheklovi
  30/sek — unga urilmaymiz. Botni o'chirganlar avtomat belgilanadi va
  keyingi tarqatishlarda o'tkazib yuboriladi.
- **Anti-spam**: bir odamdan minimal interval 0.4 soniya, ogohlantirish
  bir marta beriladi.
- **SQLite WAL rejimi**: o'qish va yozish bir-birini bloklamaydi.
  Busiz e'lon chiqqan zahoti 50 kishi bosganda «database is locked» yog'ilardi.
- **Indekslar**: qidiruv va filtr so'rovlari uchun.
- **Postlarni behuda tahrirlamaslik**: har post uchun matn barmoq izi
  saqlanadi; o'zgarish bo'lmasa Telegramga so'rov ketmaydi. Ko'p kanalda
  bu eng katta tejamkorlik.
- **O'lik kanalni o'chirish**: 5 marta xato bergan kanal to'xtatiladi.
- **Global xato ushlagich**: kutilmagan xato jimgina yo'qolmaydi —
  jurnalga tushadi, foydalanuvchiga tushunarli xabar boradi.
- **Jurnal fayli**: `logs/bot.log`, 5 MB dan oshganda avtomat almashadi.
- **Avtomat sxema yangilash**: yangi funksiya qo'shilganda baza o'chirilmaydi,
  yetishmayotgan ustunlar o'zi qo'shiladi.

PostgreSQL'ga o'tish uchun `.env` da bitta qator:
```
DB_URL=postgresql+asyncpg://user:parol@localhost/rado_job
```

---

## Tekshiruv

Kodga o'zgartirish kiritganingizdan keyin:

```bash
.venv\Scripts\python.exe smoke_test.py
```

Telegramsiz, 3 soniyada 40 ta holatni tekshiradi: joy to'lishi, navbat,
bron muddati, bir vaqtda yozilish, filtrlar, obuna ro'yxati, ish beruvchi
oqimi.

---

## Fayl tuzilishi

```
bot/
  config.py          .env (token, adminlar) + hududlar, kasblar ro'yxati
  texts.py           BARCHA matnlar — tahrirlash shu yerda
  keyboards.py       tugmalar
  callbacks.py       tugma ma'lumotlari
  states.py          ko'p qadamli suhbatlar
  middlewares.py     anti-spam, baza sessiyasi, foydalanuvchi
  scheduler.py       fon vazifalari (bron muddati, navbat, eski e'lonlar)
  utils.py           sana/vaqt/raqam parserlari
  db/
    models.py        settings, users, jobs, bookings
    base.py          ulanish + avtomat sxema yangilash
  services/
    jobs.py          BIZNES MANTIQ — barcha qoidalar
    settings_store.py sozlamalar (bazada + kesh)
    publisher.py     kanal, moderatsiya, chat ID o'zgarishini ushlash
    broadcast.py     ommaviy tarqatish (tezlik cheklovi bilan)
    notifier.py      navbatdan ko'tarish, e'lonni tarqatish
  handlers/
    base.py          /cancel
    common.py        /start, ro'yxatdan o'tish, profil
    worker.py        qidiruv, yozilish, navbat, chek
    jobpost.py       e'lon yaratish (admin + ish beruvchi), takrorlash
    admin.py         panel, to'lovlar, statistika, foydalanuvchilar
    moderation.py    chek va e'lon tasdiqlash
    settings.py      ⚙️ sozlamalar
```

Biznes qoidalari `services/` da, handler'larda emas. Ertaga sayt yoki mobil
ilova qo'shilganda mantiqni qayta yozish kerak bo'lmaydi.

---

## Keyingi bosqichlar (hozir yo'q)

- Click / Payme avtomat to'lov — moderatsiya qadami butunlay yo'qoladi
- Ishchi balansi (bir marta to'ldirib, har ishga bir bosishda yozilish)
- Ishchi reytingini ish beruvchi qo'yishi
- Kunlik/haftalik hisobot
- Rus tili
