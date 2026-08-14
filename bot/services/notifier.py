"""Foydalanuvchilarga xabar berish bilan bog'liq murakkab holatlar.

Nega alohida fayl? Chunki bu amallar bir nechta joydan chaqiriladi
(ishchi bekor qilganda, admin rad etganda, fon vazifasida) va ularning
mantiqi bir xil bo'lishi shart.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import BookingStatus, User
from bot.i18n import use_lang
from bot.services import broadcast, jobs as svc
from bot.services import publisher
from bot.services import settings_store as store

log = logging.getLogger(__name__)

MAX_PROMOTE_ATTEMPTS = 5

# MUHIM: bu fayldagi funksiyalar fon vazifalaridan ham chaqiriladi, u yerda
# middleware til o'rnatmaydi. Shuning uchun har xabar QABUL QILUVCHINING
# tilida render qilinadi — use_lang(user.lang) bilan. Busiz ruscha tanlagan
# odamga o'zbekcha eslatma borardi.


async def send_secret(bot: Bot, chat_id: int, job, lang: str | None = None) -> None:  # noqa: ANN001
    """To'lovi tasdiqlangan ishchiga maxfiy ma'lumot + xarita nuqtasi.

    Lokatsiya alohida xabar bo'lib ketadi — Telegram uni xaritada
    ko'rsatadi va «Marshrut» tugmasini beradi. Matn ichidagi manzildan
    ancha foydali, ayniqsa mo'ljal tushunarsiz bo'lganda.

    lang berilsa matn o'sha tilda ketadi (fon vazifalarida joriy til
    qabul qiluvchiniki emas).
    """
    with use_lang(lang) if lang else nullcontext():
        text = texts.booking_confirmed(job)
    await bot.send_message(chat_id, text)
    if job.lat is not None and job.lon is not None:
        try:
            await bot.send_location(chat_id, latitude=job.lat, longitude=job.lon)
        except Exception as e:
            log.warning("Lokatsiya yuborilmadi (%s): %s", chat_id, e)


async def promote_and_notify(bot: Bot, session: AsyncSession, job_id: int) -> bool:
    """Joy bo'shadi — navbatdagi birinchi odamga taklif yuboradi.

    Agar u botni bloklab qo'ygan bo'lsa, taklif havoga uchmasligi kerak:
    darhol keyingisiga o'tamiz. Aks holda bo'sh joy 10 daqiqa o'lik turadi.
    """
    for _ in range(MAX_PROMOTE_ATTEMPTS):
        booking = await svc.promote_from_waitlist(session, job_id)
        if booking is None:
            return False

        # Xabar navbatdagi ODAMNING tilida ketishi kerak.
        recipient = await session.get(User, booking.user_id)
        lang = recipient.lang if recipient else None

        try:
            if booking.job.fee <= 0:
                # Bepul e'lon: to'lov kutilmaydi, tafsilotlar darhol beriladi.
                with use_lang(lang):
                    note = texts.waitlist_promoted_free(booking.job)
                await bot.send_message(booking.user_id, note)
                await send_secret(bot, booking.user_id, booking.job, lang=lang)
            else:
                with use_lang(lang):
                    note = texts.waitlist_promoted(
                        booking.job,
                        store.waitlist_minutes(),
                        store.card_number(),
                        store.card_holder(),
                    )
                await bot.send_message(booking.user_id, note)
        except TelegramForbiddenError:
            # Odam botni bloklagan — uni o'tkazib yuboramiz.
            await svc.deactivate(session, booking.user_id)
            booking.status = BookingStatus.EXPIRED
            booking.expires_at = None
            await session.commit()
            continue
        except Exception as e:
            log.warning("Navbat xabari yetmadi (%s): %s", booking.user_id, e)

        job = await svc.get_job(session, job_id)
        if job:
            await publisher.sync_job_post(bot, session, job)
        return True
    return False


async def reward_referrer_if_first(bot: Bot, session: AsyncSession, user_id: int) -> None:
    """Chaqirilgan odam birinchi marta ishga yozildi — chaqiruvchiga bonus.

    Har ariza tasdiqlanganda chaqiriladi, lekin ichkarida «bir marta»
    tekshiruvi bor, shuning uchun takror bermaydi.
    """
    result = await svc.reward_referrer(session, user_id)
    if result is None:
        return
    inviter, reward = result
    friend = await session.get(svc.User, user_id)
    name = friend.full_name if friend else "Do'stingiz"
    try:
        # Chaqiruvchining o'z tilida.
        with use_lang(inviter.lang):
            note = texts.referral_rewarded(name, reward, inviter.free_credits)
        await bot.send_message(inviter.id, note)
    except Exception as e:
        log.debug("Referal xabari yetmadi (%s): %s", inviter.id, e)


async def notify_author_new_worker(bot: Bot, session: AsyncSession, booking) -> None:  # noqa: ANN001
    """Ish muallifiga: yangi ishchi tasdiqlandi.

    Ilgari ish beruvchi o'zi kirib tekshirishi kerak edi — natijada u
    nechta odam yig'ilganini bilmasdi va ishonchsizlik paydo bo'lardi.
    """
    job = booking.job
    if job is None or job.created_by == booking.user_id:
        return
    taken = await svc.taken_count(session, job.id)
    author = await session.get(User, job.created_by)
    try:
        # Ish beruvchining O'Z tilida — u ruschani tanlagan bo'lishi mumkin.
        with use_lang(author.lang if author else None):
            note = texts.new_worker_note(job, booking.user, taken)
        await bot.send_message(job.created_by, note)
    except Exception as e:
        log.debug("Muallifga xabar bormadi (%s): %s", job.created_by, e)


async def cancel_job(bot: Bot, session: AsyncSession, job, reason: str | None = None) -> int:
    """Ishni bekor qiladi va tafsilotlarni olgan HAMMAGA xabar beradi.

    Eng muhim qismi — xabar berish. Yomg'ir yog'di, ish qoldi: agar
    ishchilarga aytilmasa, ular ertalab manzilga borib, hech kimni
    topmaydi. Bu bir marta bo'lsa ham ishonchni yo'qotadi.
    """
    from bot.db.models import JobStatus

    job.status = JobStatus.CANCELLED
    await session.commit()

    bookings = await svc.job_workers(session, job.id)
    sent = 0
    for b in bookings:
        try:
            # Har kimga o'z tilida — matn qabul qiluvchi bo'yicha yasaladi.
            with use_lang(b.user.lang if b.user else None):
                text = texts.job_cancelled_note(job, reason)
            await bot.send_message(b.user_id, text)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)

    await publisher.sync_job_post(bot, session, job)
    return sent


async def send_reminders(bot: Bot, session: AsyncSession, kind: str) -> int:
    """Ish oldidan eslatma. No-show'ni eng ko'p kamaytiradigan narsa."""
    bookings = await svc.bookings_needing_reminder(session, kind)
    sent = []
    for b in bookings:
        try:
            recipient = await session.get(User, b.user_id)
            with use_lang(recipient.lang if recipient else None):
                if kind == "evening":
                    text = texts.remind_evening(b.job)
                else:
                    minutes = int((b.job.starts_at - svc.utcnow()).total_seconds() // 60)
                    text = texts.remind_soon(b.job, max(minutes, 1))
            await bot.send_message(b.user_id, text)
            if b.job.lat is not None and b.job.lon is not None:
                await bot.send_location(b.user_id, latitude=b.job.lat, longitude=b.job.lon)
            sent.append(b)
        except TelegramForbiddenError:
            await svc.deactivate(session, b.user_id)
            sent.append(b)  # qayta urinmaymiz
        except Exception as e:
            log.debug("Eslatma yetmadi (%s): %s", b.user_id, e)
        await asyncio.sleep(0.05)

    await svc.mark_reminded(session, sent, kind)
    return len(sent)


async def ask_attendance(bot: Bot, session: AsyncSession) -> int:
    """Ish tugagach «chiqdingizmi?» so'raydi.

    Ikki tomonga: ishchiga (o'zi javob beradi) va ish muallifiga (uning
    qarori ustun turadi). Ilgari faqat admin qo'lda belgilardi — u esa
    unutardi va reyting o'lik qolardi.
    """
    from bot.keyboards import attendance_kb, worker_actions_kb

    jobs = await svc.jobs_needing_attendance(session)
    asked = 0

    for job in jobs:
        bookings = await svc.bookings_to_ask(session, job.id)

        for b in bookings:
            try:
                # Har ishchiga o'z tilida (matn ham, tugmalar ham).
                with use_lang(b.user.lang if b.user else None):
                    text = texts.ask_attendance(job)
                    kb = attendance_kb(b.id)
                await bot.send_message(b.user_id, text, reply_markup=kb)
                asked += 1
            except Exception as e:
                log.debug("Davomat so'rovi yetmadi (%s): %s", b.user_id, e)
            b.attendance_asked = True
            await asyncio.sleep(0.05)

        # Ish muallifiga ro'yxat — u tasdiqlaydi yoki to'g'rilaydi.
        # Muallif xodim bo'lmasa bloklash tugmasini ko'rsatmaymiz — u
        # baribir ishlamaydi (faqat admin bloklaydi).
        if bookings:
            from bot.permissions import is_staff

            author = await session.get(User, job.created_by)
            author_is_staff = author is not None and is_staff(author)
            try:
                with use_lang(author.lang if author else None):
                    intro = texts.attendance_author_intro(job)
                    cards = [
                        (
                            f"👤 {b.user.mention}\n📱 <code>{b.user.phone or '—'}</code>",
                            worker_actions_kb(b.id, can_block=author_is_staff),
                        )
                        for b in bookings
                    ]
                await bot.send_message(job.created_by, intro)
                for text, kb in cards:
                    await bot.send_message(job.created_by, text, reply_markup=kb)
                    await asyncio.sleep(0.05)
            except Exception as e:
                log.debug("Muallifga davomat ro'yxati yetmadi: %s", e)

        job.attendance_asked = True
        await session.commit()

    return asked


async def broadcast_job(bot: Bot, job_id: int, report_to: int | None = None) -> None:
    """Yangi e'lonni obunachilarga tarqatadi.

    Har safar YANGI baza sessiyasi ochamiz: bu funksiya fon rejimida uzoq
    ishlaydi (minglab xabar), handler sessiyasini shuncha vaqt ushlab
    turish mumkin emas.
    """
    from bot.db.base import SessionMaker
    from bot.keyboards import job_view_kb

    # Har til uchun matn va tugmalar ALOHIDA yasaladi — ruscha tanlaganlar
    # ruscha e'lon oladi. Ikki tarqatish emas: har guruh o'z navbatida
    # ketadi, umumiy tezlik o'zgarmaydi.
    async with SessionMaker() as session:
        job = await svc.get_job(session, job_id)
        if job is None:
            return
        rows = await svc.subscribers_for_job(session, job)
        taken = await svc.taken_count(session, job.id)

        by_lang: dict[str, list[int]] = {}
        for uid, lang in rows:
            by_lang.setdefault(lang if lang in ("uz", "ru") else "uz", []).append(uid)

        rendered: dict[str, tuple[str, object]] = {}
        for lang in by_lang:
            with use_lang(lang):
                rendered[lang] = (
                    texts.NEW_JOB_BROADCAST_HEADER + "\n\n" + texts.job_card(job, taken),
                    job_view_kb(job, taken=taken, mine=False, can_wait=False),
                )

    sent_total, failed_total, blocked_all = 0, 0, []
    for lang, ids in by_lang.items():
        text, kb = rendered[lang]
        result = await broadcast.send_bulk(bot, ids, text, reply_markup=kb)
        sent_total += result.sent
        failed_total += result.failed
        blocked_all.extend(result.blocked)

    if blocked_all:
        # Botni o'chirganlarni belgilab qo'yamiz — keyingi tarqatishlar
        # shuncha tezroq bo'ladi.
        async with SessionMaker() as session:
            for uid in blocked_all:
                await svc.deactivate(session, uid)

    log.info(
        "E'lon #%s tarqatildi: %s yuborildi, %s bloklagan, %s xato",
        job_id, sent_total, len(blocked_all), failed_total,
    )
    if report_to:
        try:
            await bot.send_message(
                report_to,
                f"📨 E'lon <code>#{job_id}</code> tarqatildi:\n"
                f"✅ {sent_total} ta yetdi\n"
                f"🚫 {len(blocked_all)} ta botni o'chirgan\n"
                f"⚠️ {failed_total} ta xato",
            )
        except Exception:
            pass
