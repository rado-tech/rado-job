"""Kichik yordamchi funksiyalar."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from bot.config import TZ


def local_today() -> date:
    """Bugungi sana — TOSHKENT bo'yicha.

    Nega oddiy date.today() emas? U server soatiga qaraydi. Server esa
    (Railway, ko'pchilik VPS) UTC da ishlaydi. Toshkentda soat 00:30
    bo'lganda UTC hali kechagi kun — natijada e'lonlar bir kun kech
    yopiladi va «Bugun/Ertaga» yorliqlari xato chiqadi.

    Foydalanuvchi Toshkentda yashaydi, demak "bugun" ham Toshkent bo'yicha.
    """
    return datetime.now(TZ).date()


def parse_int(text: str) -> int | None:
    """'200 000', '200.000', '200000 so'm' -> 200000"""
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None


def parse_time(text: str) -> str | None:
    """'8:00', '8.00', '08-00' -> '08:00'"""
    t = (text or "").strip().replace(".", ":").replace("-", ":").replace(" ", "")
    if not re.fullmatch(r"\d{1,2}:\d{2}", t):
        return None
    h, m = t.split(":")
    if int(h) > 23 or int(m) > 59:
        return None
    return f"{int(h):02d}:{m}"


def parse_date(text: str) -> date | None:
    """Bir nechta ko'rinishni tushunadi — admin tez yozadi, format o'ylamaydi."""
    t = (text or "").strip().lower()
    today = local_today()
    if t in ("bugun", "bugun."):
        return today
    if t in ("ertaga", "erta"):
        return today + timedelta(days=1)
    if t in ("indinga", "indin"):
        return today + timedelta(days=2)

    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    # "05.08" — yil yozilmagan bo'lsa joriy yil, o'tib ketgan bo'lsa keyingisi
    try:
        d = datetime.strptime(t, "%d.%m").date().replace(year=today.year)
        return d if d >= today else d.replace(year=today.year + 1)
    except ValueError:
        return None


def clean(text: str, limit: int = 4000) -> str:
    """Foydalanuvchi matnini xavfsiz holga keltiradi.

    HTML rejimida ishlayotganimiz uchun `<` va `&` belgilarini ekranlash
    shart — aks holda odam tavsifga `<b>` yozsa xabar umuman yuborilmaydi
    yoki formatlash buziladi.
    """
    text = (text or "").strip()[:limit]
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
