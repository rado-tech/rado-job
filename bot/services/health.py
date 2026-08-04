"""Bot tirikligini kuzatish.

Muammo: bot server o'chgani, internet uzilgani yoki dastur qulagani uchun
to'xtab qolsa — buni HECH KIM bilmaydi. Foydalanuvchilar «bot ishlamayapti»
deb ketaveradi, siz esa ertasi kuni bilasiz.

Yechim: bot har daqiqada bazaga «men tirikman» belgisini yozadi. Qayta
ishga tushganda o'sha belgiga qarab QANCHA VAQT o'chib turganini hisoblab,
sizga xabar beradi. Tashqi xizmat, pul, sozlash kerak emas.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services import settings_store as store

log = logging.getLogger(__name__)

# Shundan qisqa uzilish e'tiborga olinmaydi (oddiy qayta ishga tushirish).
NOTABLE_DOWNTIME = timedelta(minutes=5)

started_at: datetime = datetime.now(timezone.utc)


async def heartbeat(session: AsyncSession) -> None:
    await store.set_value(
        session, "last_seen", datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


def _parse(raw: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def downtime(session: AsyncSession) -> timedelta | None:
    """Bot qancha muddat o'chib turgan edi. None — birinchi ishga tushish."""
    last = _parse(store.get("last_seen"))
    if last is None:
        return None
    gap = datetime.now(timezone.utc) - last
    return gap if gap > NOTABLE_DOWNTIME else None


def uptime() -> timedelta:
    return datetime.now(timezone.utc) - started_at


def human(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} kun")
    if hours:
        parts.append(f"{hours} soat")
    if minutes or not parts:
        parts.append(f"{minutes} daqiqa")
    return " ".join(parts)
