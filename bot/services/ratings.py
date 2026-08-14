"""Ish yakunidagi o'zaro baho (ishchi ↔ ish beruvchi).

Natijani FAQAT admin/moderator ko'radi. Ishchi va ish beruvchiga bir-birining
bahosi ko'rsatilmaydi — hozircha bu ichki sifat nazorati vositasi: past baho
yig'ayotgan odamni administratsiya erta payqaydi.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Rating


async def add(
    session: AsyncSession, *, job_id: int, rater_id: int, target_id: int, stars: int
) -> Rating:
    """Baho qo'yadi. Qayta bosilsa YANGILAYDI, ikkinchi qator ochmaydi.

    Shu tufayli bir odam bir ish bo'yicha bahoni «to'plab» berolmaydi —
    oxirgi bosgani hisobda qoladi.
    """
    stars = max(1, min(5, stars))
    existing = await session.scalar(
        select(Rating).where(
            Rating.job_id == job_id,
            Rating.rater_id == rater_id,
            Rating.target_id == target_id,
        )
    )
    if existing is not None:
        existing.stars = stars
        await session.commit()
        return existing
    rating = Rating(job_id=job_id, rater_id=rater_id, target_id=target_id, stars=stars)
    session.add(rating)
    await session.commit()
    return rating


async def summary_for(session: AsyncSession, user_id: int) -> tuple[float, int] | None:
    """Foydalanuvchi OLGAN baholar: (o'rtacha, nechta). Yo'q bo'lsa None."""
    row = (
        await session.execute(
            select(func.avg(Rating.stars), func.count()).where(Rating.target_id == user_id)
        )
    ).one()
    if not row[1]:
        return None
    return float(row[0]), int(row[1])


def line(summary: tuple[float, int] | None) -> str:
    """Admin kartochkasi uchun bitta qator: «⭐ 4.5 (12 ta baho)»."""
    if summary is None:
        return "⭐ baho yo'q"
    avg, count = summary
    return f"⭐ {avg:.1f} ({count} ta baho)"
