"""E'lon joylanadigan kanal/guruhlar ro'yxati."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Channel, Job, JobPost
from bot.services import settings_store as store

log = logging.getLogger(__name__)


async def all_channels(session: AsyncSession, *, only_active: bool = False) -> list[Channel]:
    stmt = select(Channel).order_by(Channel.id)
    if only_active:
        stmt = stmt.where(Channel.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def targets_for(session: AsyncSession, job: Job) -> list[Channel]:
    """Shu e'lon qaysi kanallarga borishi kerak."""
    channels = await all_channels(session, only_active=True)
    return [c for c in channels if c.accepts(job.region, job.category)]


async def get_by_chat(session: AsyncSession, chat_id: int) -> Channel | None:
    return await session.scalar(select(Channel).where(Channel.chat_id == chat_id))


async def add(session: AsyncSession, chat_id: int, title: str, kind: str) -> Channel:
    existing = await get_by_chat(session, chat_id)
    if existing:
        existing.title = title or existing.title
        existing.is_active = True
        existing.fail_count = 0
        existing.last_error = None
        await session.commit()
        return existing
    channel = Channel(chat_id=chat_id, title=title[:128], kind=kind)
    session.add(channel)
    await session.commit()
    return channel


async def remove(session: AsyncSession, channel_id: int) -> None:
    channel = await session.get(Channel, channel_id)
    if channel:
        await session.delete(channel)
        await session.commit()


async def toggle(session: AsyncSession, channel_id: int) -> Channel | None:
    channel = await session.get(Channel, channel_id)
    if channel:
        channel.is_active = not channel.is_active
        if channel.is_active:
            channel.fail_count = 0
            channel.last_error = None
        await session.commit()
    return channel


async def set_filter(
    session: AsyncSession, channel_id: int, field: str, values: list[str]
) -> Channel | None:
    channel = await session.get(Channel, channel_id)
    if channel is None:
        return None
    packed = ("|" + "|".join(values) + "|") if values else ""
    setattr(channel, field, packed)
    await session.commit()
    return channel


async def note_failure(session: AsyncSession, channel: Channel, error: str) -> None:
    """Kanalga joylab bo'lmadi.

    Ketma-ket 5 marta xato bo'lsa kanalni o'chirib qo'yamiz. Aks holda
    bot har e'londa o'sha o'lik kanalga urinib, vaqt va so'rov sarflaydi.
    """
    channel.fail_count += 1
    channel.last_error = error[:256]
    if channel.fail_count >= 5:
        channel.is_active = False
        log.warning("Kanal o'chirildi (5 marta xato): %s", channel.title)
    await session.commit()


async def note_success(session: AsyncSession, channel: Channel) -> None:
    if channel.fail_count or channel.last_error:
        channel.fail_count = 0
        channel.last_error = None
        await session.commit()


async def migrate_legacy(session: AsyncSession) -> None:
    """Eski bitta-kanal sozlamasini yangi jadvalga ko'chiradi.

    Avval kanal `settings.channel_id` da, post ID esa `jobs.channel_message_id`
    da turardi. Yangilanishdan keyin eski e'lonlar postini yo'qotmaslik uchun
    ularni bir marta ko'chirib olamiz.
    """
    raw = store.get("channel_id")
    if not raw or not raw.lstrip("-").isdigit():
        return
    chat_id = int(raw)

    if await get_by_chat(session, chat_id) is None:
        session.add(Channel(chat_id=chat_id, title="Asosiy kanal", kind="channel"))
        await session.commit()
        log.info("Eski kanal yangi ro'yxatga ko'chirildi: %s", chat_id)

    stmt = select(Job).where(Job.channel_message_id.is_not(None))
    moved = 0
    for job in (await session.scalars(stmt)).all():
        exists = await session.scalar(
            select(JobPost).where(JobPost.job_id == job.id, JobPost.chat_id == chat_id)
        )
        if exists is None:
            session.add(
                JobPost(job_id=job.id, chat_id=chat_id, message_id=job.channel_message_id)
            )
            moved += 1
    if moved:
        await session.commit()
        log.info("%s ta eski post ko'chirildi", moved)
