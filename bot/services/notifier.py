"""Foydalanuvchilarga xabar berish bilan bog'liq murakkab holatlar.

Nega alohida fayl? Chunki bu amallar bir nechta joydan chaqiriladi
(ishchi bekor qilganda, admin rad etganda, fon vazifasida) va ularning
mantiqi bir xil bo'lishi shart.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import BookingStatus
from bot.services import broadcast, jobs as svc
from bot.services import publisher
from bot.services import settings_store as store

log = logging.getLogger(__name__)

MAX_PROMOTE_ATTEMPTS = 5


async def send_secret(bot: Bot, chat_id: int, job) -> None:  # noqa: ANN001
    """To'lovi tasdiqlangan ishchiga maxfiy ma'lumot + xarita nuqtasi.

    Lokatsiya alohida xabar bo'lib ketadi — Telegram uni xaritada
    ko'rsatadi va «Marshrut» tugmasini beradi. Matn ichidagi manzildan
    ancha foydali, ayniqsa mo'ljal tushunarsiz bo'lganda.
    """
    await bot.send_message(chat_id, texts.booking_confirmed(job))
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

        try:
            if booking.job.fee <= 0:
                # Bepul e'lon: to'lov kutilmaydi, tafsilotlar darhol beriladi.
                await bot.send_message(
                    booking.user_id, texts.waitlist_promoted_free(booking.job)
                )
                await send_secret(bot, booking.user_id, booking.job)
            else:
                await bot.send_message(
                    booking.user_id,
                    texts.waitlist_promoted(
                        booking.job,
                        store.waitlist_minutes(),
                        store.card_number(),
                        store.card_holder(),
                    ),
                )
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


async def broadcast_job(bot: Bot, job_id: int, report_to: int | None = None) -> None:
    """Yangi e'lonni obunachilarga tarqatadi.

    Har safar YANGI baza sessiyasi ochamiz: bu funksiya fon rejimida uzoq
    ishlaydi (minglab xabar), handler sessiyasini shuncha vaqt ushlab
    turish mumkin emas.
    """
    from bot.db.base import SessionMaker
    from bot.keyboards import job_view_kb

    async with SessionMaker() as session:
        job = await svc.get_job(session, job_id)
        if job is None:
            return
        user_ids = await svc.subscribers_for_job(session, job)
        taken = await svc.taken_count(session, job.id)
        text = "🆕 <b>Yangi ish e'loni!</b>\n\n" + texts.job_card(job, taken)
        kb = job_view_kb(job, taken=taken, mine=False, can_wait=False)

    result = await broadcast.send_bulk(bot, user_ids, text, reply_markup=kb)

    if result.blocked:
        # Botni o'chirganlarni belgilab qo'yamiz — keyingi tarqatishlar
        # shuncha tezroq bo'ladi.
        async with SessionMaker() as session:
            for uid in result.blocked:
                await svc.deactivate(session, uid)

    log.info(
        "E'lon #%s tarqatildi: %s yuborildi, %s bloklagan, %s xato",
        job_id, result.sent, len(result.blocked), result.failed,
    )
    if report_to:
        try:
            await bot.send_message(
                report_to,
                f"📨 E'lon <code>#{job_id}</code> tarqatildi:\n"
                f"✅ {result.sent} ta yetdi\n"
                f"🚫 {len(result.blocked)} ta botni o'chirgan\n"
                f"⚠️ {result.failed} ta xato",
            )
        except Exception:
            pass
