"""Biznes mantiq — botning barcha qoidalari shu yerda.

Handler'lar (tugma bosilganda ishlaydigan funksiyalar) qoidalarni bilmaydi,
ular faqat shu yerdagi funksiyalarni chaqiradi. Shu tufayli ertaga sayt yoki
mobil ilova qo'shilganda mantiqni qayta yozmaymiz — shu faylni API ortiga
qo'yamiz, xolos.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, timedelta
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import settings as env
from bot.db.models import (
    OCCUPYING,
    Booking,
    BookingStatus,
    Job,
    JobStatus,
    Role,
    User,
    utcnow,
)
from bot.services import settings_store as store

# Bir vaqtda ikki kishi oxirgi bitta joyga bosishi mumkin. Ikkalasi ham
# "bo'sh joy bor" deb ko'rib, ikkalasiga ham joy berilishi mumkin edi —
# klassik "race condition". Har bir e'lon uchun alohida qulf: bir e'longa
# yozilish navbatma-navbat bajariladi, boshqa e'lonlar kutmaydi.
_job_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


class ApplyError(Exception):
    """Yozilish rad etildi — sababi foydalanuvchiga ko'rsatiladi."""


# ================================================================ users

async def get_or_create_user(session: AsyncSession, tg_user) -> User:
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            full_name=(tg_user.full_name or "")[:128],
            role=Role.ADMIN if tg_user.id in env.admins else Role.WORKER,
        )
        session.add(user)
        await session.commit()
        return user

    # Odam Telegramda ismini/username'ini o'zgartirgan bo'lishi mumkin.
    # is_active — avval botni bloklab, keyin qaytib kelgan bo'lsa tiklaymiz.
    changed = False
    if user.username != tg_user.username:
        user.username, changed = tg_user.username, True
    if tg_user.full_name and user.full_name != tg_user.full_name:
        user.full_name, changed = tg_user.full_name[:128], True
    if user.id in env.admins and user.role != Role.ADMIN:
        user.role, changed = Role.ADMIN, True
    if not user.is_active:
        user.is_active, changed = True, True
    if changed:
        await session.commit()
    return user


async def set_categories(session: AsyncSession, user: User, keys: Sequence[str]) -> None:
    user.categories = ("|" + "|".join(keys) + "|") if keys else ""
    await session.commit()


async def toggle_category(session: AsyncSession, user: User, key: str) -> bool:
    keys = user.category_keys
    if key in keys:
        keys.remove(key)
        on = False
    else:
        keys.append(key)
        on = True
    await set_categories(session, user, keys)
    return on


async def deactivate(session: AsyncSession, user_id: int) -> None:
    """Foydalanuvchi botni bloklagan — keyingi tarqatishlarda urinmaymiz."""
    user = await session.get(User, user_id)
    if user and user.is_active:
        user.is_active = False
        await session.commit()


# ================================================================ hisoblash

async def taken_count(session: AsyncSession, job_id: int) -> int:
    """Band joylar: tasdiqlangan + tekshiruvdagi + muddati o'tmagan bronlar."""
    now = utcnow()
    stmt = (
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.job_id == job_id,
            Booking.status.in_(OCCUPYING),
            or_(Booking.expires_at.is_(None), Booking.expires_at > now),
        )
    )
    return int((await session.scalar(stmt)) or 0)


async def taken_counts(session: AsyncSession, job_ids: Sequence[int]) -> dict[int, int]:
    """Ro'yxat uchun bitta so'rov — har e'lonni alohida so'ramaymiz (N+1)."""
    if not job_ids:
        return {}
    now = utcnow()
    stmt = (
        select(Booking.job_id, func.count())
        .where(
            Booking.job_id.in_(job_ids),
            Booking.status.in_(OCCUPYING),
            or_(Booking.expires_at.is_(None), Booking.expires_at > now),
        )
        .group_by(Booking.job_id)
    )
    rows = (await session.execute(stmt)).all()
    counts = {jid: 0 for jid in job_ids}
    counts.update({jid: int(c) for jid, c in rows})
    return counts


async def waitlist_count(session: AsyncSession, job_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(Booking)
        .where(Booking.job_id == job_id, Booking.status == BookingStatus.WAITLIST)
    )
    return int((await session.scalar(stmt)) or 0)


async def waitlist_position(session: AsyncSession, booking: Booking) -> int:
    """Navbatda nechanchi ekanini aytadi — bu odamni ushlab turadi."""
    stmt = (
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.job_id == booking.job_id,
            Booking.status == BookingStatus.WAITLIST,
            Booking.queued_at < (booking.queued_at or utcnow()),
        )
    )
    return int((await session.scalar(stmt)) or 0) + 1


# ================================================================ ro'yxat

async def feed(
    session: AsyncSession,
    *,
    region: str | None = None,
    category: str | None = None,
    day: date | None = None,
    include_full: bool = False,
    offset: int = 0,
    limit: int = 8,
) -> tuple[list[Job], int]:
    """Ishchi ko'radigan e'lonlar ro'yxati + umumiy soni (sahifalash uchun)."""
    statuses = [JobStatus.OPEN, JobStatus.FULL] if include_full else [JobStatus.OPEN]
    conditions = [Job.status.in_(statuses), Job.work_date >= date.today()]
    if region:
        conditions.append(Job.region == region)
    if category:
        conditions.append(Job.category == category)
    if day:
        conditions.append(Job.work_date == day)

    total = int(
        (await session.scalar(select(func.count()).select_from(Job).where(*conditions))) or 0
    )
    stmt = (
        select(Job)
        .where(*conditions)
        .order_by(Job.work_date, Job.start_time, Job.id)
        .offset(offset)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all()), total


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def get_booking(session: AsyncSession, job_id: int, user_id: int) -> Booking | None:
    stmt = (
        select(Booking)
        .where(Booking.job_id == job_id, Booking.user_id == user_id)
        # Xotiradagi eski nusxa emas, bazadagi ayni damdagi holat kerak.
        .execution_options(populate_existing=True)
    )
    return await session.scalar(stmt)


async def active_booking(session: AsyncSession, job_id: int, user_id: int) -> Booking | None:
    """Faqat 'tirik' ariza: band qilgan yoki navbatda turgan."""
    b = await get_booking(session, job_id, user_id)
    if b is None:
        return None
    if b.status == BookingStatus.WAITLIST:
        return b
    if b.status in OCCUPYING:
        if b.expires_at and b.expires_at <= utcnow():
            return None
        return b
    return None


# ================================================================ yozilish

async def apply_to_job(session: AsyncSession, job_id: int, user_id: int) -> Booking:
    """Joyni bron qilish. Butun mantiqning yuragi.

    Ikki xil yakun bo'ladi:
      * PULLI e'lon  -> PENDING_PAYMENT, joy vaqtincha bron qilinadi va
                        ishchidan chek kutiladi
      * BEPUL e'lon  -> darhol CONFIRMED, maxfiy ma'lumot o'sha zahoti
                        beriladi. Chek ham, moderatsiya ham, bron muddati
                        ham kerak emas.
    """
    async with _job_locks[job_id]:
        job = await _fresh_job(session, job_id)
        if job.status != JobStatus.OPEN:
            raise ApplyError("Bu e'longa yozilish yopilgan.")
        if job.work_date < date.today():
            raise ApplyError("Bu ishning sanasi o'tib ketgan.")

        existing = await get_booking(session, job_id, user_id)
        if existing and _is_alive(existing):
            raise ApplyError("Siz bu ishga allaqachon yozilgansiz.")

        await _check_no_show_limit(session, job, user_id)

        if await taken_count(session, job_id) >= job.slots_total:
            job.status = JobStatus.FULL
            await session.commit()
            raise ApplyError("Afsus, joylar to'ldi. Navbatga yozilishingiz mumkin.")

        booking = _revive(session, existing, job_id, user_id)
        booking.queued_at = None
        _set_after_apply(booking, job)
        await session.commit()

        await _sync_status(session, job)
        return booking


def _set_after_apply(booking: Booking, job: Job) -> None:
    """Pulli/bepul e'longa qarab arizaning holatini belgilaydi."""
    if job.fee <= 0:
        booking.status = BookingStatus.CONFIRMED
        booking.expires_at = None
        booking.decided_at = utcnow()
    else:
        booking.status = BookingStatus.PENDING_PAYMENT
        booking.expires_at = utcnow() + timedelta(minutes=store.hold_minutes())


async def _check_no_show_limit(session: AsyncSession, job: Job, user_id: int) -> None:
    """Bepul ishlarda "yozilib qo'yaman, borsam boraman" muammosini jilovlaydi.

    Pul to'langanda odam albatta boradi — puli ketgan. Bepul bo'lganda esa
    bu tabiiy tiyilish yo'qoladi va joylar bekorga band bo'ladi. Shuning
    uchun ishga chiqmaslik chegarasi FAQAT bepul ishlarga qo'llanadi:
    pulli ishga baribir yozilaverishi mumkin.
    """
    if job.fee > 0:
        return
    limit = store.max_no_show()
    if limit <= 0:
        return
    user = await session.get(User, user_id)
    if user and user.no_show_count >= limit:
        raise ApplyError(
            f"Siz {user.no_show_count} marta yozilib, ishga chiqmagansiz. "
            f"Shuning uchun bepul ishlarga yozila olmaysiz. "
            f"Administrator bilan bog'laning."
        )


async def join_waitlist(session: AsyncSession, job_id: int, user_id: int) -> Booking:
    """Navbatga yozilish — BEPUL, joy egallamaydi.

    Bu bron modelining yagona kamchiligini yopadi: joy bo'shaganda u zoye
    ketmaydi, chunki navbatdagi odamga darhol xabar ketadi. Ayni paytda
    ortiqcha to'lov ham bo'lmaydi — navbatda turgan pul to'lamaydi.
    """
    async with _job_locks[job_id]:
        job = await _fresh_job(session, job_id)
        if job.status not in (JobStatus.OPEN, JobStatus.FULL):
            raise ApplyError("Bu e'lon yopilgan.")
        if job.work_date < date.today():
            raise ApplyError("Bu ishning sanasi o'tib ketgan.")

        existing = await get_booking(session, job_id, user_id)
        if existing and _is_alive(existing):
            raise ApplyError("Siz allaqachon ro'yxatdasiz.")

        booking = _revive(session, existing, job_id, user_id)
        booking.status = BookingStatus.WAITLIST
        booking.queued_at = utcnow()
        booking.expires_at = None
        await session.commit()
        return booking


async def promote_from_waitlist(session: AsyncSession, job_id: int) -> Booking | None:
    """Joy bo'shadi — navbatdagi birinchi odamga taklif qiladi.

    Unga oddiy brondan qisqaroq (waitlist_minutes) vaqt beriladi: u allaqachon
    navbatda kutgan, demak tayyor. Vaqtida ulgurmasa — keyingisiga o'tadi.
    """
    job = await _fresh_job(session, job_id)
    if job.status != JobStatus.OPEN:
        return None
    if await taken_count(session, job_id) >= job.slots_total:
        return None

    stmt = (
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(Booking.job_id == job_id, Booking.status == BookingStatus.WAITLIST)
        .order_by(Booking.queued_at)
        .limit(1)
    )
    nxt = await session.scalar(stmt)
    if nxt is None:
        return None

    if job.fee <= 0:
        # Bepul e'lon: to'lov kutish ma'nosiz — joy darhol beriladi.
        nxt.status = BookingStatus.CONFIRMED
        nxt.expires_at = None
        nxt.decided_at = utcnow()
    else:
        nxt.status = BookingStatus.PENDING_PAYMENT
        nxt.expires_at = utcnow() + timedelta(minutes=store.waitlist_minutes())
    await session.commit()
    await _sync_status(session, job)
    return nxt


async def set_fee(session: AsyncSession, job: Job, fee: int) -> None:
    """E'lonni bepulga o'tkazish yoki qayta pulli qilish."""
    job.fee = max(fee, 0)
    await session.commit()


async def has_money_bookings(session: AsyncSession, job_id: int) -> bool:
    """Shu e'lon bo'yicha kimdir allaqachon pul to'laganmi?

    To'lagan odam bo'lsa narxni o'zgartirish adolatsizlik va janjal
    keltiradi — shuning uchun bunday e'lonni pulli/bepulga aylantirmaymiz.
    """
    stmt = (
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.job_id == job_id,
            Booking.status.in_(
                [BookingStatus.RECEIPT_SENT, BookingStatus.CONFIRMED, BookingStatus.NO_SHOW]
            ),
            Booking.receipt_file_id.is_not(None),
        )
    )
    return bool((await session.scalar(stmt)) or 0)


async def cancel_booking(session: AsyncSession, booking: Booking) -> None:
    booking.status = BookingStatus.CANCELLED
    booking.expires_at = None
    booking.queued_at = None
    await session.commit()
    job = await session.get(Job, booking.job_id)
    if job:
        await _sync_status(session, job)


async def attach_receipt(session: AsyncSession, booking: Booking, file_id: str) -> None:
    """Chek keldi — bron muddati olib tashlanadi, admin qarorini kutamiz."""
    booking.receipt_file_id = file_id
    booking.status = BookingStatus.RECEIPT_SENT
    booking.expires_at = None
    await session.commit()


async def confirm_booking(session: AsyncSession, booking: Booking, admin_id: int) -> None:
    booking.status = BookingStatus.CONFIRMED
    booking.expires_at = None
    booking.decided_by = admin_id
    booking.decided_at = utcnow()
    await session.commit()
    job = await session.get(Job, booking.job_id)
    if job:
        await _sync_status(session, job)


async def reject_booking(
    session: AsyncSession, booking: Booking, admin_id: int, reason: str | None
) -> None:
    booking.status = BookingStatus.REJECTED
    booking.expires_at = None
    booking.reject_reason = reason
    booking.decided_by = admin_id
    booking.decided_at = utcnow()
    await session.commit()
    job = await session.get(Job, booking.job_id)
    if job:
        await _sync_status(session, job)


async def mark_no_show(session: AsyncSession, booking: Booking) -> None:
    """Ishga chiqmagan. Joy qaytarilmaydi — u to'lagan, lekin bormagan."""
    booking.status = BookingStatus.NO_SHOW
    await session.commit()
    user = await session.get(User, booking.user_id)
    if user:
        user.no_show_count += 1
        await session.commit()


async def mark_completed(session: AsyncSession, booking: Booking) -> None:
    user = await session.get(User, booking.user_id)
    if user:
        user.completed_count += 1
        await session.commit()


# ================================================================ fon

async def expire_holds(session: AsyncSession) -> list[Booking]:
    """Vaqtida chek yubormaganlarning bronini bekor qiladi."""
    now = utcnow()
    stmt = (
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(
            Booking.status == BookingStatus.PENDING_PAYMENT,
            Booking.expires_at.is_not(None),
            Booking.expires_at <= now,
        )
    )
    expired = list((await session.scalars(stmt)).all())
    for b in expired:
        b.status = BookingStatus.EXPIRED
        b.expires_at = None
    if expired:
        await session.commit()
        for job in {b.job for b in expired}:
            await _sync_status(session, job)
    return expired


async def close_past_jobs(session: AsyncSession) -> list[Job]:
    stmt = select(Job).where(
        Job.status.in_([JobStatus.OPEN, JobStatus.FULL, JobStatus.PENDING_REVIEW]),
        Job.work_date < date.today(),
    )
    jobs = list((await session.scalars(stmt)).all())
    for j in jobs:
        j.status = JobStatus.CLOSED
    if jobs:
        await session.commit()
    return jobs


async def jobs_needing_promotion(session: AsyncSession) -> list[int]:
    """Bo'sh joyi ham, navbati ham bor e'lonlar."""
    stmt = (
        select(Booking.job_id)
        .join(Job, Job.id == Booking.job_id)
        .where(Booking.status == BookingStatus.WAITLIST, Job.status == JobStatus.OPEN)
        .distinct()
    )
    return list((await session.scalars(stmt)).all())


# ================================================================ ro'yxatlar

async def my_bookings(session: AsyncSession, user_id: int, limit: int = 15) -> list[Booking]:
    stmt = (
        select(Booking)
        .options(selectinload(Booking.job))
        .where(Booking.user_id == user_id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def pending_receipts(session: AsyncSession) -> list[Booking]:
    stmt = (
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(Booking.status == BookingStatus.RECEIPT_SENT)
        .order_by(Booking.created_at)
    )
    return list((await session.scalars(stmt)).all())


async def pending_jobs(session: AsyncSession) -> list[Job]:
    """Ish beruvchilar yuborgan, admin tasdig'ini kutayotgan e'lonlar."""
    stmt = (
        select(Job)
        .options(selectinload(Job.creator))
        .where(Job.status == JobStatus.PENDING_REVIEW)
        .order_by(Job.created_at)
    )
    return list((await session.scalars(stmt)).all())


async def job_workers(session: AsyncSession, job_id: int) -> list[Booking]:
    stmt = (
        select(Booking)
        .options(selectinload(Booking.user))
        .where(
            Booking.job_id == job_id,
            Booking.status.in_([*OCCUPYING, BookingStatus.WAITLIST]),
        )
        .order_by(Booking.created_at)
    )
    return list((await session.scalars(stmt)).all())


async def jobs_by_author(session: AsyncSession, user_id: int, limit: int = 20) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.created_by == user_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def recent_jobs(session: AsyncSession, limit: int = 20) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def find_user(session: AsyncSession, query: str) -> User | None:
    q = query.strip().lstrip("@")
    if q.isdigit():
        return await session.get(User, int(q))
    stmt = select(User).where(func.lower(User.username) == q.lower()).limit(1)
    return await session.scalar(stmt)


async def stats(session: AsyncSession) -> dict:
    async def count(model, *where) -> int:
        return int((await session.scalar(select(func.count()).select_from(model).where(*where))) or 0)

    revenue = await session.scalar(
        select(func.coalesce(func.sum(Job.fee), 0))
        .select_from(Booking)
        .join(Job, Job.id == Booking.job_id)
        .where(Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.NO_SHOW]))
    )
    return {
        "users": await count(User),
        "active": await count(User, User.is_active.is_(True)),
        "workers": await count(User, User.role == Role.WORKER),
        "employers": await count(User, User.role == Role.EMPLOYER),
        "jobs": await count(Job),
        "open_jobs": await count(Job, Job.status == JobStatus.OPEN),
        "review_jobs": await count(Job, Job.status == JobStatus.PENDING_REVIEW),
        "confirmed": await count(Booking, Booking.status == BookingStatus.CONFIRMED),
        "waiting": await count(Booking, Booking.status == BookingStatus.RECEIPT_SENT),
        "waitlist": await count(Booking, Booking.status == BookingStatus.WAITLIST),
        "revenue": int(revenue or 0),
    }


async def audience(
    session: AsyncSession,
    *,
    region: str | None = None,
    category: str | None = None,
    only_workers: bool = True,
) -> list[int]:
    """Reklama yoki e'lon uchun qabul qiluvchilar ro'yxati.

    Botni o'chirganlar va bloklanganlar chiqarib tashlanadi — ularga
    urinish behuda vaqt.
    """
    conditions = [
        User.is_blocked.is_(False),
        User.is_active.is_(True),
        User.phone.is_not(None),
    ]
    if only_workers:
        conditions.append(User.role == Role.WORKER)
    if region:
        conditions.append(User.region == region)
    if category:
        conditions.append(User.categories.like(f"%|{category}|%"))
    return list((await session.scalars(select(User.id).where(*conditions))).all())


async def subscribers_for_job(session: AsyncSession, job: Job) -> list[int]:
    """Yangi e'lon haqida kimga xabar berish kerak.

    Shartlar: bloklanmagan, botni o'chirmagan, xabarnomani yoqib qo'ygan,
    hududi mos (yoki "Boshqa hudud" tanlagan) va kasbga obuna bo'lgan
    (yoki umuman kasb tanlamagan — unda hammasi keladi).
    """
    stmt = select(User.id).where(
        User.is_blocked.is_(False),
        User.is_active.is_(True),
        User.notify.is_(True),
        User.role == Role.WORKER,
        User.phone.is_not(None),
        or_(User.region == job.region, User.region == "Boshqa hudud"),
        or_(User.categories == "", User.categories.like(f"%|{job.category}|%")),
    )
    return list((await session.scalars(stmt)).all())


# ================================================================ ichki

def _is_alive(b: Booking) -> bool:
    if b.status == BookingStatus.WAITLIST:
        return True
    if b.status not in OCCUPYING:
        return False
    return not (b.expires_at and b.expires_at <= utcnow())


def _revive(session: AsyncSession, existing: Booking | None, job_id: int, user_id: int) -> Booking:
    """Eski arizani qayta ishlatamiz.

    unique(job_id, user_id) cheklovi bor, shuning uchun bekor qilgan odam
    qayta yozilganda yangi qator ochmasdan eskisini tozalab ishlatamiz.
    """
    if existing is None:
        booking = Booking(job_id=job_id, user_id=user_id)
        session.add(booking)
        return booking
    existing.receipt_file_id = None
    existing.reject_reason = None
    existing.decided_at = None
    existing.decided_by = None
    return existing


async def _fresh_job(session: AsyncSession, job_id: int) -> Job:
    """E'lonni bazadan qayta o'qiydi.

    commit() (rollback emas!) tranzaksiyani yopadi va keyingi so'rov yangi
    "surat" oladi. rollback obyektlarni eskirgan deb belgilaydi va async
    muhitda oddiy `user.region` murojaati MissingGreenlet bilan yiqiladi.
    populate_existing esa xotiradagi eski nusxani bazadagi bilan almashtiradi.
    """
    await session.commit()
    job = await session.get(Job, job_id, populate_existing=True)
    if job is None:
        raise ApplyError("E'lon topilmadi.")
    return job


async def _sync_status(session: AsyncSession, job: Job) -> bool:
    """Band joylarga qarab OPEN <-> FULL ni avtomat almashtiradi."""
    if job.status in (JobStatus.CLOSED, JobStatus.CANCELLED, JobStatus.DECLINED,
                      JobStatus.PENDING_REVIEW):
        return False
    taken = await taken_count(session, job.id)
    new = JobStatus.FULL if taken >= job.slots_total else JobStatus.OPEN
    if new != job.status:
        job.status = new
        await session.commit()
        return True
    return False
