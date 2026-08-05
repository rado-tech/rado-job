"""To'lov cheklarini va ish beruvchi e'lonlarini tasdiqlash / rad etish.

Bu — tizimdagi eng muhim tugma. Admin chekni ko'radi va bir bosishda hal
qiladi; qolgan hamma narsa (maxfiy ma'lumotni yuborish, joyni bo'shatish,
navbatdagini chaqirish, kanaldagi postni yangilash) avtomat bajariladi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot import texts
from bot.callbacks import JobModCB, ModCB, RejCB
from bot.db.models import Booking, BookingStatus, JobStatus, User
from bot.keyboards import REJECT_REASONS, reject_reasons_kb, undo_kb
from bot.permissions import IsStaff
from bot.services import jobs as svc
from bot.services import notifier, publisher
from bot.states import Moderation

log = logging.getLogger(__name__)
router = Router(name="moderation")

# Chek tekshirish — moderatorlar ham qila oladi.
router.message.filter(IsStaff())
router.callback_query.filter(IsStaff())


async def _load(session: AsyncSession, booking_id: int) -> Booking | None:
    return await session.scalar(
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(Booking.id == booking_id)
    )


async def _mark_done(call: CallbackQuery, suffix: str, *, booking_id: int | None = None) -> None:
    """Chek rasmining tagidagi yozuvni yangilaydi.

    Tasdiqlash/rad etish tugmalari olib tashlanadi (ikkinchi moderator
    qayta ko'rib chiqmasligi uchun), o'rniga «↩️ Qaytarish» qo'yiladi —
    xato bosilgan qarorni tuzatish imkoni bo'lsin.
    """
    markup = undo_kb(booking_id) if booking_id else None
    try:
        if call.message.caption is not None:
            await call.message.edit_caption(
                caption=call.message.caption + suffix, reply_markup=markup
            )
        else:
            await call.message.edit_text(
                (call.message.text or "") + suffix, reply_markup=markup
            )
    except Exception as e:
        log.debug("Xabar yangilanmadi: %s", e)


# ================================================================ chek

@router.callback_query(ModCB.filter(F.action == "ok"))
async def approve(
    call: CallbackQuery, callback_data: ModCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    booking = await _load(session, callback_data.booking_id)
    if booking is None:
        await call.answer("Ariza topilmadi.", show_alert=True)
        return
    if booking.status != BookingStatus.RECEIPT_SENT:
        await call.answer(
            f"Allaqachon ko'rib chiqilgan: {texts.BOOKING_STATUS_LABEL[booking.status]}",
            show_alert=True,
        )
        await _mark_done(call, "")
        return

    await svc.confirm_booking(session, booking, user.id)

    # Ishchiga maxfiy ma'lumot + xarita nuqtasi — mana shu uchun u pul to'lagan.
    try:
        await notifier.send_secret(bot, booking.user_id, booking.job)
    except Exception as e:
        log.warning("Ishchiga xabar yuborilmadi %s: %s", booking.user_id, e)
        await call.message.answer(
            f"⚠️ Tasdiqlandi, lekin ishchiga xabar bormadi (botni bloklagan "
            f"bo'lishi mumkin).\n📱 <code>{booking.user.phone}</code>"
        )

    await _mark_done(
        call, f"\n\n✅ <b>TASDIQLANDI</b> — {user.full_name}", booking_id=booking.id
    )
    await call.answer("✅ Tasdiqlandi")
    await publisher.sync_job_post(bot, session, booking.job)
    # Bu odam kimningdir havolasi orqali kelgan bo'lsa — chaqiruvchiga bonus.
    await notifier.reward_referrer_if_first(bot, session, booking.user_id)
    # Ish beruvchi kim yig'ilayotganini bilib tursin.
    await notifier.notify_author_new_worker(bot, session, booking)


@router.callback_query(ModCB.filter(F.action == "no"))
async def reject_ask(
    call: CallbackQuery, callback_data: ModCB, state: FSMContext, session: AsyncSession
) -> None:
    booking = await _load(session, callback_data.booking_id)
    if booking is None:
        await call.answer("Ariza topilmadi.", show_alert=True)
        return
    if booking.status != BookingStatus.RECEIPT_SENT:
        await call.answer("Allaqachon ko'rib chiqilgan.", show_alert=True)
        await _mark_done(call, "")
        return

    # Avval tayyor sabablarni taklif qilamiz — guruhda matn yozishdan
    # ko'ra tugma bosish tez va xatosiz.
    await state.update_data(booking_id=booking.id, mod_message_id=call.message.message_id)
    await call.message.answer(
        texts.CHOOSE_REJECT_REASON, reply_markup=reject_reasons_kb(booking.id)
    )
    await call.answer()


@router.callback_query(RejCB.filter())
async def reject_reason_picked(
    call: CallbackQuery, callback_data: RejCB, state: FSMContext,
    session: AsyncSession, user: User, bot: Bot
) -> None:
    if callback_data.key == "back":
        await state.set_state(None)
        await call.message.edit_text("Bekor qilindi.")
        await call.answer()
        return

    if callback_data.key == "other":
        await state.set_state(Moderation.reject_reason)
        await state.update_data(booking_id=callback_data.booking_id)
        await call.message.edit_text(texts.ASK_REJECT_REASON)
        await call.answer()
        return

    reason = REJECT_REASONS.get(callback_data.key)
    await state.update_data(booking_id=callback_data.booking_id)
    await call.message.edit_text(f"❌ Sabab: <i>{reason}</i>")
    await call.answer()
    await _do_reject(call.message, state, session, user, bot, reason=reason)


# Filtrni DEKORATORGA yozamiz, handler ichida "if state != ..." tekshirmaymiz.
# Sababi: aiogram'da handler bir marta ishga tushsa, xabar boshqa
# handler'larga umuman o'tmaydi — ichkarida `return` qilsak admin yozgan
# har qanday matn shu yerda yo'qolib ketardi.
@router.message(Moderation.reject_reason, Command("skip"))
async def reject_no_reason(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await _do_reject(message, state, session, user, bot, reason=None)


@router.message(Moderation.reject_reason, F.text)
async def reject_with_reason(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await _do_reject(message, state, session, user, bot, reason=message.text.strip()[:250])


async def _do_reject(
    message: Message, state: FSMContext, session: AsyncSession,
    user: User, bot: Bot, reason: str | None,
) -> None:
    data = await state.get_data()
    await state.set_state(None)

    booking = await _load(session, data.get("booking_id", 0))
    if booking is None or booking.status != BookingStatus.RECEIPT_SENT:
        await message.answer("Ariza topilmadi yoki allaqachon hal qilingan.")
        return

    await svc.reject_booking(session, booking, user.id, reason)

    try:
        await bot.send_message(booking.user_id, texts.booking_rejected(booking.job, reason))
    except Exception as e:
        log.warning("Rad etish xabari yetmadi %s: %s", booking.user_id, e)

    await message.answer(
        f"❌ Ariza #{booking.id} rad etildi. Joy bo'shatildi."
        + (f"\nSabab: <i>{reason}</i>" if reason else "")
    )

    if mod_msg_id := data.get("mod_message_id"):
        try:
            await bot.edit_message_reply_markup(
                chat_id=message.chat.id,
                message_id=mod_msg_id,
                reply_markup=undo_kb(booking.id),
            )
        except Exception:
            pass

    await publisher.sync_job_post(bot, session, booking.job)
    # Joy bo'shadi — navbatdagi birinchi odamga taklif ketadi.
    await notifier.promote_and_notify(bot, session, booking.job_id)


# ================================================================ qaytarish

@router.callback_query(ModCB.filter(F.action == "undo"))
async def undo(
    call: CallbackQuery, callback_data: ModCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    """Xato bosilgan qarorni qaytaradi — ariza yana tekshiruvga tushadi."""
    booking = await _load(session, callback_data.booking_id)
    if booking is None:
        await call.answer("Ariza topilmadi.", show_alert=True)
        return

    was = booking.status
    try:
        await svc.undo_decision(session, booking)
    except svc.UndoError as e:
        await call.answer(str(e), show_alert=True)
        return

    await call.answer("↩️ Qaytarildi")
    await _mark_done_undo(call, user.full_name)

    # Ishchiga ham aytamiz — u allaqachon qarorni ko'rgan.
    try:
        if was == BookingStatus.CONFIRMED:
            note = texts.undo_after_confirm(booking.job)
        else:
            note = texts.undo_after_reject(booking.job)
        await bot.send_message(booking.user_id, note)
    except Exception as e:
        log.debug("Qaytarish xabari yetmadi (%s): %s", booking.user_id, e)

    await publisher.sync_job_post(bot, session, booking.job)
    # Ariza yana navbatda — moderatorlarga qayta ko'rsatamiz.
    await publisher.send_to_moderation(bot, session, booking)


async def _mark_done_undo(call: CallbackQuery, who: str) -> None:
    suffix = f"\n\n↩️ <b>QAROR QAYTARILDI</b> — {who}"
    try:
        if call.message.caption is not None:
            await call.message.edit_caption(
                caption=call.message.caption + suffix, reply_markup=None
            )
        else:
            await call.message.edit_text(
                (call.message.text or "") + suffix, reply_markup=None
            )
    except Exception as e:
        log.debug("Xabar yangilanmadi: %s", e)


# ================================================================ e'lon tasdiqlash

@router.callback_query(JobModCB.filter(F.action == "ok"))
async def approve_job(
    call: CallbackQuery, callback_data: JobModCB, session: AsyncSession, bot: Bot
) -> None:
    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer("E'lon topilmadi.", show_alert=True)
        return
    if job.status != JobStatus.PENDING_REVIEW:
        await call.answer("Bu e'lon allaqachon ko'rib chiqilgan.", show_alert=True)
        await _mark_done(call, "")
        return

    job.status = JobStatus.OPEN
    await session.commit()

    await _mark_done(call, "\n\n✅ <b>TASDIQLANDI</b>")
    await call.answer("✅ Tasdiqlandi")

    try:
        await bot.send_message(
            job.created_by,
            f"✅ <b>«{job.title}»</b> e'loningiz tasdiqlandi va joylandi!",
        )
    except Exception:
        pass

    from bot.handlers.jobpost import publish_and_notify

    await publish_and_notify(bot, session, job, report_to=call.from_user.id)


@router.callback_query(JobModCB.filter(F.action == "no"))
async def decline_job_ask(
    call: CallbackQuery, callback_data: JobModCB, state: FSMContext, session: AsyncSession
) -> None:
    job = await svc.get_job(session, callback_data.job_id)
    if job is None or job.status != JobStatus.PENDING_REVIEW:
        await call.answer("E'lon topilmadi yoki hal qilingan.", show_alert=True)
        return
    await state.set_state(Moderation.decline_reason)
    await state.update_data(job_id=job.id, mod_message_id=call.message.message_id)
    await call.message.answer(texts.ASK_DECLINE_REASON)
    await call.answer()


@router.message(Moderation.decline_reason, Command("skip"))
async def decline_no_reason(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    await _do_decline(message, state, session, bot, None)


@router.message(Moderation.decline_reason, F.text)
async def decline_with_reason(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    await _do_decline(message, state, session, bot, message.text.strip()[:250])


async def _do_decline(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot, reason: str | None
) -> None:
    data = await state.get_data()
    await state.set_state(None)

    job = await svc.get_job(session, data.get("job_id", 0))
    if job is None or job.status != JobStatus.PENDING_REVIEW:
        await message.answer("E'lon topilmadi yoki allaqachon hal qilingan.")
        return

    job.status = JobStatus.DECLINED
    job.decline_reason = reason
    await session.commit()

    try:
        text = f"❌ <b>«{job.title}»</b> e'loningiz rad etildi."
        if reason:
            text += f"\n\nSabab: <i>{reason}</i>"
        await bot.send_message(job.created_by, text)
    except Exception:
        pass

    await message.answer(f"❌ E'lon #{job.id} rad etildi.")
    if mod_msg_id := data.get("mod_message_id"):
        try:
            await bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=mod_msg_id, reply_markup=None
            )
        except Exception:
            pass
