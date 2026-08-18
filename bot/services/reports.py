"""Shikoyatlar va murojaatlar.

Nega kerak? Real pul aylanganda muammo albatta chiqadi: «ish e'londagidek
emas edi», «manzilda hech kim yo'q», «pul to'lanmadi». Bot ichida shikoyat
yo'li bo'lmasa, odam buni ochiq kanalga yozadi va obro'ingizga zarar yetadi.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Report, ReportStatus, utcnow


async def create(
    session: AsyncSession, user_id: int, text: str, job_id: int | None = None
) -> Report:
    report = Report(user_id=user_id, text=text[:2000], job_id=job_id)
    session.add(report)
    await session.commit()
    return report


async def get(session: AsyncSession, report_id: int) -> Report | None:
    return await session.scalar(
        select(Report)
        .options(selectinload(Report.user), selectinload(Report.job))
        .where(Report.id == report_id)
    )


async def open_reports(session: AsyncSession, limit: int = 20) -> list[Report]:
    stmt = (
        select(Report)
        .options(selectinload(Report.user), selectinload(Report.job))
        .where(Report.status == ReportStatus.OPEN)
        .order_by(Report.created_at)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def open_count(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Report).where(Report.status == ReportStatus.OPEN)
    return int((await session.scalar(stmt)) or 0)


async def answer(session: AsyncSession, report: Report, staff_id: int, text: str) -> None:
    report.answer = text[:2000]
    report.status = ReportStatus.ANSWERED
    report.handled_by = staff_id
    report.handled_at = utcnow()
    await session.commit()


async def close(session: AsyncSession, report: Report, staff_id: int) -> None:
    report.status = ReportStatus.CLOSED
    report.handled_by = staff_id
    report.handled_at = utcnow()
    await session.commit()
