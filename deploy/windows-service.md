# Windowsda botni xizmat (service) qilib qo'yish

Bu — vaqtinchalik yechim. **Jiddiy ishlatish uchun Linux VPS oling**
(pastda sabablari). Lekin sinov davrida Windowsda ham botni doim ishlab
turadigan qilish mumkin.

## Nega oddiy `python -m bot` yetarli emas

| Muammo | Nima bo'ladi |
|---|---|
| Noutbuk qopqog'ini yopdingiz | Bot uxlaydi, hech kim yozila olmaydi |
| Kompyuter o'chdi/qayta yuklandi | Bot ishga tushmaydi, siz bilmaysiz |
| Konsol oynasini yopdingiz | Bot o'ladi |
| Dastur qulab tushdi | Qayta ishga tushmaydi |
| Wi-Fi uzildi | Bot javob bermaydi |

## NSSM bilan xizmat qilish

**1.** [nssm.cc](https://nssm.cc/download) dan yuklab oling, arxivdan
`win64\nssm.exe` ni chiqaring.

**2.** Administrator huquqi bilan PowerShell oching:

```powershell
nssm install RadoJobBot
```

Ochilgan oynada:
- **Path:** `C:\Users\rado\Desktop\rado-job\.venv\Scripts\python.exe`
- **Startup directory:** `C:\Users\rado\Desktop\rado-job`
- **Arguments:** `-m bot`
- **Details → Startup type:** `Automatic`
- **Exit actions → Restart delay:** `10000` (10 soniya)

**3.** Ishga tushirish:

```powershell
nssm start RadoJobBot
```

**Boshqarish:**

```powershell
nssm status RadoJobBot
nssm restart RadoJobBot
nssm stop RadoJobBot
nssm remove RadoJobBot confirm
```

Jurnal loyihaning `logs\bot.log` faylida.

## Windows sozlamalari

Xizmat qilib qo'yganingizdan keyin ham:

1. **Uyqu rejimini o'chiring** — Sozlamalar → Tizim → Quvvat → «Hech qachon»
2. **Avtomat qayta yuklashni o'chiring** — Windows Update tunda kompyuterni
   qayta yuklasa, xizmat o'zi ko'tariladi, lekin bir necha daqiqa uzilish
   bo'ladi
3. **Kompyuterni o'chirmang**

## Baribir Linux VPS yaxshi

| | Windows noutbuk | Linux VPS |
|---|---|---|
| Doimiy ishlash | ❌ uyqu, qayta yuklash, qopqoq | ✅ 24/7 |
| Internet | ❌ Wi-Fi, uy internetiga bog'liq | ✅ ma'lumot markazi |
| Tok | ❌ o'chsa — tamom | ✅ generator + UPS |
| Narxi | 0 | ~$4-6/oy |
| IP o'zgarishi | ❌ | ✅ doimiy |

O'zbekistonda: **Ahost, Uzcloud, Cloud.uz**. Chet elda arzoni:
**Hetzner (~€4)**, **Contabo**, **DigitalOcean ($6)**.

Eng arzon tarif ham yetarli: 1 CPU, 1 GB RAM, 20 GB disk.
Bu bot minglab foydalanuvchida ham 200 MB dan kam RAM ishlatadi.

Linuxga o'tganingizda `deploy/rado-job.service` faylidan foydalaning —
u yerda hammasi tayyor.
