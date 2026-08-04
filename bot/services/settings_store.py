"""Bot sozlamalari — bazada saqlanadi, xotirada keshlanadi.

Nega kesh? Har xabarda karta raqamini bazadan so'rash — behuda yuk.
Sozlamalar kamdan-kam o'zgaradi, shuning uchun bir marta o'qib xotirada
ushlaymiz va o'zgartirilganda yangilaymiz.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as env
from bot.db.models import Setting

log = logging.getLogger(__name__)

# Kalit -> (standart qiymat, tavsif)
DEFAULTS: dict[str, str] = {
    "channel_id": "",
    "moderation_chat_id": "",
    "card_number": "",
    "card_holder": "",
    "default_fee": "10000",
    "hold_minutes": "15",
    "waitlist_minutes": "10",
    "support_username": "",
    # Bepul rejim: yangi e'lonlar avtomat BEPUL bo'ladi. Loyihaning
    # boshida auditoriya yig'ish uchun. Keyin bir tugma bilan o'chiriladi
    # va e'lonlar pulli bo'ladi — eski e'lonlarga tegmaydi.
    "free_mode": "1",
    # Bepul ishga yozilib, chiqmaganlar uchun chegara. Pul to'lanmaganda
    # "yozilib qo'yaman, borsam boraman" muammosi kuchayadi — bu uni
    # jilovlaydi. 0 = cheklov yo'q.
    "max_no_show": "2",
    # Bot "tirikligi" belgisi — har daqiqada yangilanadi. Ishga tushganda
    # shu vaqtga qarab bot qancha muddat o'chib turganini hisoblaymiz.
    "last_seen": "",
    # Oxirgi marta zaxira Telegramga yuborilgan vaqt — kuniga bir marta
    # yuborishni ta'minlash uchun.
    "last_backup_sent": "",
}

_cache: dict[str, str] = {}


async def load(session: AsyncSession) -> None:
    """Ishga tushishda bir marta chaqiriladi.

    Birinchi ishga tushishda .env dagi qiymatlarni bazaga ko'chiradi —
    shunda eski sozlamalaringiz yo'qolmaydi.
    """
    rows = (await session.scalars(select(Setting))).all()
    _cache.clear()
    _cache.update(DEFAULTS)
    _cache.update({r.key: (r.value or "") for r in rows})

    # .env dan bir martalik ko'chirish (faqat bazada bo'sh bo'lsa).
    seed = {
        "channel_id": env.channel_id,
        "moderation_chat_id": env.moderation_chat_id,
        "card_number": env.card_number,
        "card_holder": env.card_holder,
        "default_fee": str(env.default_fee),
        "hold_minutes": str(env.hold_minutes),
    }
    for key, value in seed.items():
        if value and not _cache.get(key):
            await set_value(session, key, value)
            log.info(".env dan ko'chirildi: %s", key)


async def set_value(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.commit()
    _cache[key] = value


def get(key: str, default: str = "") -> str:
    return _cache.get(key) or DEFAULTS.get(key) or default


def get_int(key: str, default: int = 0) -> int:
    raw = get(key)
    return int(raw) if raw.lstrip("-").isdigit() else default


def chat_id(key: str) -> int | str | None:
    """'-1001234567890' -> int, '@kanal' -> str, bo'sh -> None

    Qo'lda kiritishda uchraydigan xatolarga chidamli: ortiqcha minus,
    bo'shliqlar, `@` unutilgani. `int('--100...')` xato beradi va butun
    moderatsiya oqimini to'xtatib qo'yardi.
    """
    raw = get(key).strip().replace(" ", "")
    if not raw:
        return None
    if raw.startswith("@"):
        return raw

    digits = raw.lstrip("-")
    if digits.isdigit():
        return -int(digits) if raw.startswith("-") else int(digits)
    return f"@{raw}"


# ---------------------------------------------------------------- qulaylik

def channel() -> int | str | None:
    return chat_id("channel_id")


def moderation_chat() -> int | str | None:
    return chat_id("moderation_chat_id")


def card_number() -> str:
    return get("card_number") or "— (sozlanmagan)"


def card_holder() -> str:
    return get("card_holder") or "—"


def default_fee() -> int:
    return get_int("default_fee", 10_000)


def hold_minutes() -> int:
    return get_int("hold_minutes", 15)


def waitlist_minutes() -> int:
    return get_int("waitlist_minutes", 10)


def free_mode() -> bool:
    return get("free_mode") == "1"


def max_no_show() -> int:
    return get_int("max_no_show", 2)


def is_payment_ready() -> bool:
    """Karta rekvizitlari kerakmi?

    Bepul rejimda kerak emas — hech kim to'lov qilmaydi. Shu tufayli
    loyihani karta rekvizitisiz ham bugunoq ishga tushirish mumkin.
    """
    if free_mode():
        return True
    return bool(get("card_number") and get("card_holder"))
