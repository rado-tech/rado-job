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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import TZ
from bot.config import settings as env
from bot.db.models import (
    OCCUPYING,
    UNLOCKED,
    Booking,
    BookingStatus,
    Job,
    JobStatus,
    Role,
    User,
    utcnow,
)
from bot.services import settings_store as store
from bot.utils import local_now_hhmm, local_today

# Bir vaqtda ikki kishi oxirgi bitta joyga bosishi mumkin. Ikkalasi ham
# "bo'sh joy bor" deb ko'rib, ikkalasiga ham joy berilishi mumkin edi —
# klassik "race condition". Har bir e'lon uchun alohida qulf: bir e'longa
# yozilish navbatma-navbat bajariladi, boshqa e'lonlar kutmaydi.
_job_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


class ApplyError(Exception):
    """Yozilish rad etildi — sababi foydalanuvchiga ko'rsatiladi."""


def not_started():  # noqa: ANN201
    """SQL sharti: ish hali BOSHLANMAGAN.

    Ilgari faqat sana tekshirilardi (`work_date >= bugun`). Natijada
    bugun soat 08:00 dagi ish kechqurun 18:00 da ham ro'yxatda turardi va
    odam allaqachon o'tib ketgan ishga pul to'lay olardi.

    Endi bugungi kun uchun vaqt ham hisobga olinadi. start_time doim
    "HH:MM" ko'rinishida nol bilan to'ldirilgani uchun matn taqqoslash
    to'g'ri ishlaydi.
    """
    today = local_today()
    return or_(
        Job.work_date > today,
        and_(Job.work_date == today, Job.start_time > local_now_hhmm()),
    )


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
    conditions = [Job.status.in_(statuses), not_started()]
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

async def apply_to_job(
    session: AsyncSession, job_id: int, user_id: int, *, use_credit: bool = False
) -> Booking:
    """Joyni bron qilish. Butun mantiqning yuragi.

    Uch xil yakun:
      * BEPUL e'lon        -> darhol CONFIRMED, tafsilotlar o'sha zahoti
      * BONUS bilan        -> darhol CONFIRMED, bir bonus sarflanadi
      * PULLI e'lon        -> PENDING_PAYMENT, joy bron qilinadi, chek kutiladi
    """
    async with _job_locks[job_id]:
        job = await _fresh_job(session, job_id)
        if job.status != JobStatus.OPEN:
            raise ApplyError("Bu e'longa yozilish yopilgan.")
        if job.starts_at <= utcnow():
            raise ApplyError("Bu ish allaqachon boshlangan.")

        existing = await get_booking(session, job_id, user_id)
        if existing and _is_alive(existing):
            raise ApplyError("Siz bu ishga allaqachon yozilgansiz.")

        user = await session.get(User, user_id)
        free_for_user = job.fee <= 0
        if use_credit:
            if job.fee <= 0:
                use_credit = False  # bepul ishga bonus sarflash — bekorchilik
            elif user is None or user.free_credits <= 0:
                raise ApplyError("Sizda bepul yozilish bonusi yo'q.")
            else:
                free_for_user = True

        await _check_no_show_limit(session, job, user, free_for_user)

        if await taken_count(session, job_id) >= job.slots_total:
            job.status = JobStatus.FULL
            await session.commit()
            raise ApplyError("Afsus, joylar to'ldi. Navbatga yozilishingiz mumkin.")

        booking = _revive(session, existing, job_id, user_id)
        booking.queued_at = None
        booking.used_credit = use_credit
        if free_for_user:
            booking.status = BookingStatus.CONFIRMED
            booking.expires_at = None
            booking.decided_at = utcnow()
            if use_credit and user:
                user.free_credits -= 1
        else:
            booking.status = BookingStatus.PENDING_PAYMENT
            booking.expires_at = utcnow() + timedelta(minutes=store.hold_minutes())
        await session.commit()

        await _sync_status(session, job)
        return booking


async def _check_no_show_limit(
    session: AsyncSession, job: Job, user: User | None, free_for_user: bool
) -> None:
    """Bepul ishlarda "yozilib qo'yaman, borsam boraman" muammosini jilovlaydi.

    Pul to'langanda odam albatta boradi — puli ketgan. Bepul bo'lganda esa
    bu tabiiy tiyilish yo'qoladi va joylar bekorga band bo'ladi. Shuning
    uchun chegara FAQAT to'lovsiz yozilishga qo'llanadi (bepul e'lon yoki
    bonus): pulli ishga baribir yozilaverishi mumkin.
    """
    if not free_for_user:
        return
    limit = store.max_no_show()
    if limit <= 0 or user is None:
        return
    if user.no_show_count >= limit:
        raise ApplyError(
            f"Siz {user.no_show_count} marta yozilib, ishga chiqmagansiz. "
            f"Shuning uchun to'lovsiz yozila olmaysiz. "
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
        if job.starts_at <= utcnow():
            raise ApplyError("Bu ish allaqachon boshlangan.")

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


def is_late_cancel(job: Job, booking: Booking) -> bool:
    """Bekor qilish "kech" hisoblanadimi?

    Faqat tasdiqlangan ariza uchun mantiqiy: odam joyni egallab turgan va
    oxirgi daqiqada voz kechsa, o'rniga boshqa odam topib bo'lmaydi.
    To'lov kutayotgan yoki navbatdagilarga bu qo'llanmaydi.
    """
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED):
        return False
    window = store.cancel_window_minutes()
    if window <= 0:
        return False
    return job.starts_at - utcnow() < timedelta(minutes=window)


async def cancel_booking(session: AsyncSession, booking: Booking, *, late: bool = False) -> None:
    """Arizani bekor qiladi.

    Kech bekor qilishda ham joyni BO'SHATAMIZ — bu bizga foydali, chunki
    navbatdagi odam o'rnini egallashi mumkin. Lekin bu "kelmagan" deb
    hisoblanadi, aks holda oxirgi daqiqada voz kechish jazosiz bo'lardi.

    Muhim nuqta: odam ogohlantirishni OLDINDAN ko'radi va o'zi tanlaydi.
    Aytmasdan kelmaslikdan ko'ra, aytib bekor qilish baribir yaxshiroq.
    """
    # LATE_CANCEL joyni EGALLAMAYDI (OCCUPYING ro'yxatida yo'q) — shu tufayli
    # joy darhol bo'shaydi va navbatdagi odam chaqiriladi. NO_SHOW esa
    # egallaydi: u odam kelmagani ish tugagandan keyin bilinadi, joy allaqachon
    # sarflangan bo'ladi.
    booking.status = BookingStatus.LATE_CANCEL if late else BookingStatus.CANCELLED
    booking.expires_at = None
    booking.queued_at = None
    await session.commit()

    if late:
        user = await session.get(User, booking.user_id)
        if user:
            user.no_show_count += 1
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
    """Ishga chiqmagan. Joy qaytarilmaydi — u yozilgan, lekin bormagan."""
    if booking.status == BookingStatus.NO_SHOW:
        return
    was_completed = booking.status == BookingStatus.COMPLETED
    booking.status = BookingStatus.NO_SHOW
    await session.commit()
    user = await session.get(User, booking.user_id)
    if user:
        user.no_show_count += 1
        if was_completed and user.completed_count > 0:
            user.completed_count -= 1  # avvalgi belgi noto'g'ri ekan
        await session.commit()


async def mark_completed(session: AsyncSession, booking: Booking) -> None:
    """Ishga chiqdi.

    Bir ariza ikki marta sanalmasligi kerak: ishchi o'zi tasdiqlaydi, keyin
    ish beruvchi ham bosishi mumkin.
    """
    if booking.status == BookingStatus.COMPLETED:
        return
    was_no_show = booking.status == BookingStatus.NO_SHOW
    booking.status = BookingStatus.COMPLETED
    await session.commit()
    user = await session.get(User, booking.user_id)
    if user:
        user.completed_count += 1
        if was_no_show and user.no_show_count > 0:
            user.no_show_count -= 1
        await session.commit()


# ================================================================ referal

async def register_referral(session: AsyncSession, user: User, inviter_id: int) -> bool:
    """Kim chaqirganini yozib qo'yadi. Mukofot hali berilmaydi."""
    if user.invited_by is not None or user.id == inviter_id:
        return False
    inviter = await session.get(User, inviter_id)
    if inviter is None:
        return False
    user.invited_by = inviter_id
    inviter.invited_count += 1
    await session.commit()
    return True


async def reward_referrer(session: AsyncSession, user_id: int) -> tuple[User, int] | None:
    """Chaqirilgan odam birinchi marta ishga yozilganda mukofot beradi.

    Nega darhol emas, balki birinchi yozilishdan keyin? Aks holda soxta
    akkauntlar bilan bonus yig'ish mumkin bo'lardi. Telefon raqami majburiy
    bo'lgani ustiga bu ikkinchi to'siq.
    """
    reward = store.referral_reward()
    if reward <= 0:
        return None
    user = await session.get(User, user_id)
    if user is None or user.invited_by is None or user.referral_rewarded:
        return None

    inviter = await session.get(User, user.invited_by)
    if inviter is None or inviter.is_blocked:
        return None

    user.referral_rewarded = True
    inviter.free_credits += reward
    await session.commit()
    return inviter, reward


# ================================================================ eslatmalar

async def bookings_needing_reminder(session: AsyncSession, kind: str) -> list[Booking]:
    """Eslatma yuborilishi kerak bo'lgan arizalar.

    kind="evening" — ish oldingi kuni kechqurun
    kind="soon"    — ishgacha bir necha soat qolganda
    """
    now = utcnow()
    flag = Booking.reminded_evening if kind == "evening" else Booking.reminded_soon

    stmt = (
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .join(Job, Job.id == Booking.job_id)
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            flag.is_(False),
            Job.work_date >= local_today(),
            Job.status.in_([JobStatus.OPEN, JobStatus.FULL]),
        )
        .limit(500)
    )
    candidates = list((await session.scalars(stmt)).all())

    result = []
    for b in candidates:
        starts = b.job.starts_at
        if starts <= now:
            continue
        if kind == "evening":
            # Faqat ERTAGAgi ishlar uchun, va faqat belgilangan soatdan keyin.
            local_now = now.astimezone(TZ)
            if b.job.work_date != local_now.date() + timedelta(days=1):
                continue
            if local_now.hour < store.remind_evening_hour():
                continue
        else:
            minutes_left = (starts - now).total_seconds() / 60
            if minutes_left > store.remind_before_minutes():
                continue
        result.append(b)
    return result


async def mark_reminded(session: AsyncSession, bookings: list[Booking], kind: str) -> None:
    for b in bookings:
        if kind == "evening":
            b.reminded_evening = True
        else:
            b.reminded_soon = True
    if bookings:
        await session.commit()


async def jobs_needing_attendance(session: AsyncSession) -> list[Job]:
    """Tugagan, lekin yozilganlari hali belgilanmagan ishlar."""
    now = utcnow()
    stmt = (
        select(Job)
        .where(Job.attendance_asked.is_(False), Job.work_date <= local_today())
        .limit(100)
    )
    jobs = list((await session.scalars(stmt)).all())
    after = timedelta(hours=store.attendance_after_hours())
    return [j for j in jobs if j.starts_at + after <= now]


async def bookings_to_ask(session: AsyncSession, job_id: int) -> list[Booking]:
    stmt = (
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(
            Booking.job_id == job_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.attendance_asked.is_(False),
        )
    )
    return list((await session.scalars(stmt)).all())


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
    """Boshlangan ishlarni yopadi.

    Sana emas, aynan BOSHLANISH VAQTI bo'yicha: bugun 08:00 dagi ish
    soat 08:01 da yopilishi kerak, kechqurun emas.
    """
    stmt = select(Job).where(
        Job.status.in_([JobStatus.OPEN, JobStatus.FULL, JobStatus.PENDING_REVIEW]),
        ~not_started(),
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


async def pending_payment_booking(session: AsyncSession, user_id: int) -> Booking | None:
    """Foydalanuvchining to'lov kutayotgan (muddati o'tmagan) arizasi.

    Nima uchun kerak? Bot qayta ishga tushganda FSM holati xotiradan
    yo'qoladi. Odam pulni o'tkazib, chekni yuboradi — lekin bot uni
    "chek kutayotgan holat" da emas deb hisoblab, umuman javob bermaydi.
    Bu esa eng yomon ssenariy: puli ketgan, javob yo'q.

    Shu funksiya orqali chekni holatga tayanmasdan, bazadagi arizaga
    bog'laymiz.
    """
    stmt = (
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(
            Booking.user_id == user_id,
            Booking.status == BookingStatus.PENDING_PAYMENT,
            or_(Booking.expires_at.is_(None), Booking.expires_at > utcnow()),
        )
        .order_by(Booking.created_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


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

    # Tushum: faqat HAQIQIY to'lovlar. Bepul e'lonlar (fee=0) va bonus
    # hisobiga yozilganlar hisobga olinmaydi.
    revenue = await session.scalar(
        select(func.coalesce(func.sum(Job.fee), 0))
        .select_from(Booking)
        .join(Job, Job.id == Booking.job_id)
        .where(
            Booking.status.in_(
                [BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW]
            ),
            Booking.used_credit.is_(False),
        )
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
        "completed": await count(Booking, Booking.status == BookingStatus.COMPLETED),
        "no_show": await count(
            Booking,
            Booking.status.in_([BookingStatus.NO_SHOW, BookingStatus.LATE_CANCEL]),
        ),
        "waiting": await count(Booking, Booking.status == BookingStatus.RECEIPT_SENT),
        "waitlist": await count(Booking, Booking.status == BookingStatus.WAITLIST),
        "credits_used": await count(Booking, Booking.used_credit.is_(True)),
        "revenue": int(revenue or 0),
    }


async def daily_summary(session: AsyncSession, since) -> dict:  # noqa: ANN001
    """Kunlik hisobot uchun raqamlar.

    `since` — hisobot boshlanish momenti (UTC). Undan keyingi harakatlar
    sanaladi.
    """

    async def count(model, *where) -> int:
        return int((await session.scalar(select(func.count()).select_from(model).where(*where))) or 0)

    revenue = await session.scalar(
        select(func.coalesce(func.sum(Job.fee), 0))
        .select_from(Booking)
        .join(Job, Job.id == Booking.job_id)
        .where(
            Booking.decided_at >= since,
            Booking.status.in_(
                [BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW]
            ),
            Booking.used_credit.is_(False),
        )
    )

    # Ertangi ishlar bo'yicha to'lmagan joylar — eng foydali ma'lumot:
    # bugun kechqurun nimaga e'tibor berish kerakligini ko'rsatadi.
    tomorrow = local_today() + timedelta(days=1)
    open_tomorrow = list(
        (await session.scalars(
            select(Job).where(Job.work_date == tomorrow, Job.status == JobStatus.OPEN)
        )).all()
    )
    gaps = []
    for job in open_tomorrow:
        taken = await taken_count(session, job.id)
        if taken < job.slots_total:
            gaps.append((job, job.slots_total - taken))

    return {
        "new_users": await count(User, User.created_at >= since),
        "new_jobs": await count(Job, Job.created_at >= since),
        "confirmed": await count(
            Booking, Booking.decided_at >= since,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED]),
        ),
        "rejected": await count(
            Booking, Booking.decided_at >= since, Booking.status == BookingStatus.REJECTED
        ),
        "completed": await count(
            Booking, Booking.status == BookingStatus.COMPLETED, Booking.decided_at >= since
        ),
        "no_show": await count(
            Booking,
            Booking.status.in_([BookingStatus.NO_SHOW, BookingStatus.LATE_CANCEL]),
            Booking.created_at >= since,
        ),
        "revenue": int(revenue or 0),
        "waiting": await count(Booking, Booking.status == BookingStatus.RECEIPT_SENT),
        "review_jobs": await count(Job, Job.status == JobStatus.PENDING_REVIEW),
        "gaps": gaps,
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


async def recompute_status(session: AsyncSession, job: Job) -> bool:
    """Tashqaridan chaqirish uchun (masalan joy soni tahrirlanganda)."""
    return await _sync_status(session, job)


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
