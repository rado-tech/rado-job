"""Ishchi tomoni: qidirish, yozilish, navbat, chek yuborish."""

from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot import texts
from bot.callbacks import AttendCB, FeedCB, JobCB, NavCB, PickCB
from bot.config import CATEGORY_NAMES
from bot.db.models import UNLOCKED, Booking, BookingStatus, JobStatus, User, utcnow
from bot.keyboards import (
    BTN_FIND,
    BTN_MY,
    cancel_confirm_kb,
    categories_kb,
    days_kb,
    feed_kb,
    job_view_kb,
    regions_kb,
    report_kb,
)
from bot.services import jobs as svc
from bot.services import notifier, publisher, reports
from bot.services import settings_store as store
from bot.states import Pay, ReportFlow
from bot.utils import clean

log = logging.getLogger(__name__)
router = Router(name="worker")

PER_PAGE = 8


# ================================================================ ro'yxat

async def _filters(state: FSMContext, user: User) -> dict:
    data = await state.get_data()
    return {
        # Kalit umuman qo'yilmagan bo'lsa — foydalanuvchi hududini olamiz.
        # Aynan shu odamga kerakli e'lonlar birinchi ko'rinadi.
        "region": data.get("f_region", user.region or ""),
        "category": data.get("f_cat", ""),
        "day": data.get("f_day", ""),
        "page": int(data.get("f_page", 0)),
    }


async def show_feed(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    *,
    edit: bool = False,
) -> None:
    f = await _filters(state, user)
    day = date.fromisoformat(f["day"]) if f["day"] else None

    jobs, total = await svc.feed(
        session,
        region=f["region"] or None,
        category=f["category"] or None,
        day=day,
        include_full=True,
        offset=f["page"] * PER_PAGE,
        limit=PER_PAGE,
    )

    note = ""
    # Hududda hech nima yo'q bo'lsa — bo'sh ekran ko'rsatmaymiz, avtomat
    # kengaytiramiz. "Bot bo'sh ekan" degan taassurot eng katta yo'qotish.
    if total == 0 and f["region"]:
        jobs, total = await svc.feed(
            session,
            category=f["category"] or None,
            day=day,
            include_full=True,
            offset=0,
            limit=PER_PAGE,
        )
        if total:
            f["region"] = ""
            await state.update_data(f_region="", f_page=0)
            note = "\n<i>Hududingizda e'lon yo'q — barcha hududlar ko'rsatildi.</i>"

    if total == 0:
        text = texts.NO_JOBS
        kb = feed_kb(
            [], page=0, total=0, per_page=PER_PAGE,
            region=f["region"], category=_cat_label(f["category"]), day=_day_label(f["day"]),
        )
    else:
        counts = await svc.taken_counts(session, [j.id for j in jobs])
        rows = [(j, counts.get(j.id, 0)) for j in jobs]
        text = f"🔎 <b>Topildi: {total} ta e'lon</b>\nBatafsil ko'rish uchun bosing 👇{note}"
        kb = feed_kb(
            rows, page=f["page"], total=total, per_page=PER_PAGE,
            region=f["region"], category=_cat_label(f["category"]), day=_day_label(f["day"]),
        )

    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass  # eski xabar o'chirilgan bo'lishi mumkin
    await message.answer(text, reply_markup=kb)


def _cat_label(key: str) -> str:
    if not key:
        return ""
    # Tugmaga sig'ishi uchun emojisiz qisqa nom
    return CATEGORY_NAMES.get(key, key).split(" ", 1)[-1][:14]


def _day_label(iso: str) -> str:
    return texts.short_date(date.fromisoformat(iso)) if iso else ""


@router.message(F.text == BTN_FIND)
@router.message(Command("ishlar"))
async def feed_cmd(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.set_state(None)
    await state.update_data(f_page=0)
    await show_feed(message, state, session, user)


@router.callback_query(NavCB.filter(F.to == "feed"))
async def nav_feed(call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await show_feed(call.message, state, session, user)
    await call.answer()


@router.callback_query(FeedCB.filter(F.action == "page"))
async def feed_page(
    call: CallbackQuery, callback_data: FeedCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    await state.update_data(f_page=callback_data.page)
    await show_feed(call.message, state, session, user, edit=True)
    await call.answer()


@router.callback_query(FeedCB.filter(F.action == "reset"))
async def feed_reset(call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.update_data(f_region="", f_cat="", f_day="", f_page=0)
    await show_feed(call.message, state, session, user, edit=True)
    await call.answer("♻️ Filtr tozalandi")


@router.callback_query(FeedCB.filter(F.action == "filter"))
async def feed_filter(call: CallbackQuery, callback_data: FeedCB) -> None:
    if callback_data.value == "region":
        await call.message.answer("📍 Hududni tanlang:", reply_markup=regions_kb("freg", with_all=True))
    elif callback_data.value == "category":
        await call.message.answer("🧰 Ish turini tanlang:", reply_markup=categories_kb("fcat", with_all=True))
    else:
        await call.message.answer("📅 Kunni tanlang:", reply_markup=days_kb())
    await call.answer()


@router.callback_query(PickCB.filter(F.field.in_({"freg", "fcat", "fday"})))
async def feed_set_filter(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    value = "" if callback_data.value == "*" else callback_data.value
    key = {"freg": "f_region", "fcat": "f_cat", "fday": "f_day"}[callback_data.field]
    await state.update_data(**{key: value, "f_page": 0})
    await call.message.delete()
    await show_feed(call.message, state, session, user)
    await call.answer()


# ================================================================ bitta e'lon

async def show_job(message: Message, session: AsyncSession, user: User, job_id: int) -> None:
    job = await svc.get_job(session, job_id)
    if job is None:
        await message.answer("❗️ Bunday e'lon topilmadi.")
        return

    taken = await svc.taken_count(session, job.id)
    waiting = await svc.waitlist_count(session, job.id)
    booking = await svc.get_booking(session, job.id, user.id)

    # Tafsilotlar ochilgan bo'lsa — maxfiy ma'lumot va lokatsiya bilan.
    if booking and booking.status in UNLOCKED:
        still_open = booking.status == BookingStatus.CONFIRMED
        await message.answer(
            texts.job_card(job, taken, secret=True, show_slots=False),
            reply_markup=job_view_kb(
                job, taken=taken, mine=True, can_wait=False, confirmed=still_open
            ),
        )
        if job.lat is not None and job.lon is not None:
            try:
                await message.answer_location(latitude=job.lat, longitude=job.lon)
            except Exception:
                pass
        return

    active = await svc.active_booking(session, job.id, user.id)
    header = ""
    if active and active.status == BookingStatus.WAITLIST:
        pos = await svc.waitlist_position(session, active)
        header = f"⏳ <b>Siz navbatdasiz — {pos}-o'rin</b>\n\n"
    elif active:
        header = f"{texts.BOOKING_STATUS_LABEL[active.status]}\n\n"

    await message.answer(
        header + texts.job_card(job, taken, waitlist=waiting),
        reply_markup=job_view_kb(
            job, taken=taken, mine=active is not None, can_wait=True,
            credits=user.free_credits,
        ),
    )


@router.callback_query(JobCB.filter(F.action == "view"))
async def job_view(
    call: CallbackQuery, callback_data: JobCB, session: AsyncSession, user: User
) -> None:
    await show_job(call.message, session, user, callback_data.job_id)
    await call.answer()


# ================================================================ yozilish

@router.callback_query(JobCB.filter(F.action.in_({"apply", "credit"})))
async def job_apply(
    call: CallbackQuery, callback_data: JobCB, state: FSMContext,
    session: AsyncSession, user: User, bot: Bot
) -> None:
    if not user.is_registered:
        await call.answer("Avval /start bosib ro'yxatdan o'ting.", show_alert=True)
        return
    if not store.is_payment_ready():
        await call.answer("To'lov rekvizitlari sozlanmagan. Adminga xabar bering.", show_alert=True)
        return

    use_credit = callback_data.action == "credit"
    try:
        booking = await svc.apply_to_job(
            session, callback_data.job_id, user.id, use_credit=use_credit
        )
    except svc.ApplyError as e:
        await call.answer(str(e), show_alert=True)
        await show_job(call.message, session, user, callback_data.job_id)
        return

    job = await svc.get_job(session, callback_data.job_id)

    if booking.status == BookingStatus.CONFIRMED:
        # BEPUL yoki BONUS — chek ham, moderatsiya ham kerak emas.
        # Maxfiy ma'lumot va lokatsiya o'sha zahoti beriladi.
        if booking.used_credit:
            await call.message.answer(texts.credit_used(user.free_credits))
        await notifier.send_secret(bot, user.id, job)
        await notifier.reward_referrer_if_first(bot, session, user.id)
        await call.answer("🎉 Yozildingiz!")
    else:
        # PULLI e'lon — chek kutish holatiga o'tamiz va ariza ID sini eslab
        # qolamiz: keyingi rasm aynan shu arizaga bog'lanadi.
        await state.set_state(Pay.receipt)
        await state.update_data(booking_id=booking.id)
        await call.message.answer(
            texts.payment_instruction(
                job, store.hold_minutes(), store.card_number(), store.card_holder()
            )
        )
        await call.answer("✅ Joy band qilindi")

    if job and job.status == JobStatus.FULL:
        await publisher.sync_job_post(bot, session, job)


@router.callback_query(JobCB.filter(F.action == "wait"))
async def job_wait(
    call: CallbackQuery, callback_data: JobCB, session: AsyncSession, user: User
) -> None:
    if not user.is_registered:
        await call.answer("Avval /start bosib ro'yxatdan o'ting.", show_alert=True)
        return
    try:
        booking = await svc.join_waitlist(session, callback_data.job_id, user.id)
    except svc.ApplyError as e:
        await call.answer(str(e), show_alert=True)
        return

    job = await svc.get_job(session, callback_data.job_id)
    position = await svc.waitlist_position(session, booking)
    await call.message.answer(texts.waitlist_joined(job, position))
    await call.answer("⏳ Navbatga yozildingiz")


@router.callback_query(JobCB.filter(F.action == "cancel"))
async def job_cancel(
    call: CallbackQuery, callback_data: JobCB, session: AsyncSession, user: User
) -> None:
    """Bekor qilish. Ishga oz vaqt qolgan bo'lsa avval ogohlantiramiz.

    Ilgari tasdiqlangan arizani umuman bekor qilib bo'lmasdi — natijada odam
    shunchaki bormay qo'yardi va joy zoye ketardi. Endi bekor qila oladi,
    lekin oqibatini OLDINDAN ko'radi va o'zi tanlaydi.
    """
    booking = await svc.active_booking(session, callback_data.job_id, user.id)
    if booking is None:
        await call.answer("Faol arizangiz yo'q.", show_alert=True)
        return

    job = await svc.get_job(session, callback_data.job_id)
    if job and svc.is_late_cancel(job, booking):
        minutes_left = max(int((job.starts_at - utcnow()).total_seconds() // 60), 0)
        await call.message.answer(
            texts.cancel_warning(job, minutes_left), reply_markup=cancel_confirm_kb(job.id)
        )
        await call.answer()
        return

    await _do_cancel(call, session, user, booking, late=False)


@router.callback_query(JobCB.filter(F.action == "cancelyes"))
async def job_cancel_confirm(
    call: CallbackQuery, callback_data: JobCB, session: AsyncSession, user: User
) -> None:
    booking = await svc.active_booking(session, callback_data.job_id, user.id)
    if booking is None:
        await call.answer("Faol arizangiz yo'q.", show_alert=True)
        return
    job = await svc.get_job(session, callback_data.job_id)
    late = bool(job and svc.is_late_cancel(job, booking))
    await _do_cancel(call, session, user, booking, late=late)


async def _do_cancel(
    call: CallbackQuery, session: AsyncSession, user: User, booking, late: bool
) -> None:  # noqa: ANN001
    job_id = booking.job_id
    await svc.cancel_booking(session, booking, late=late)
    await call.answer("🚫 Bekor qilindi")
    await call.message.answer(texts.CANCEL_LATE_DONE if late else texts.CANCEL_DONE)

    job = await svc.get_job(session, job_id)
    if job:
        await publisher.sync_job_post(call.bot, session, job)
        # Joy bo'shadi — navbatdagi birinchi odamga taklif yuboramiz.
        await notifier.promote_and_notify(call.bot, session, job.id)
        await show_job(call.message, session, user, job.id)


# ================================================================ davomat

@router.callback_query(AttendCB.filter())
async def attendance_answer(
    call: CallbackQuery, callback_data: AttendCB, session: AsyncSession, user: User
) -> None:
    """Ishchining «chiqdingizmi?» so'roviga javobi.

    Bu o'z-o'zini baholash — odam yolg'on aytishi mumkin. Shuning uchun ish
    muallifiga ham ro'yxat yuboriladi va uning qarori ustun turadi.
    """
    booking = await session.get(Booking, callback_data.booking_id)
    if booking is None or booking.user_id != user.id:
        await call.answer("Ariza topilmadi.", show_alert=True)
        return
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED,
                              BookingStatus.NO_SHOW):
        await call.answer("Bu ariza bo'yicha belgilash mumkin emas.", show_alert=True)
        return

    if callback_data.action == "yes":
        await svc.mark_completed(session, booking)
        text = texts.ATTENDANCE_THANKS
    else:
        await svc.mark_no_show(session, booking)
        text = texts.ATTENDANCE_NOSHOW

    await call.answer("✅ Belgilandi")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(text)


# ================================================================ shikoyat

@router.callback_query(JobCB.filter(F.action == "report"))
async def report_start(
    call: CallbackQuery, callback_data: JobCB, state: FSMContext
) -> None:
    await state.set_state(ReportFlow.text)
    await state.update_data(report_job_id=callback_data.job_id)
    await call.message.answer(texts.ASK_REPORT)
    await call.answer()


@router.message(Command("shikoyat"))
async def report_command(message: Message, state: FSMContext) -> None:
    await state.set_state(ReportFlow.text)
    await state.update_data(report_job_id=None)
    await message.answer(texts.ASK_REPORT)


@router.message(ReportFlow.text, F.text)
async def report_text(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    text = clean(message.text, 2000)
    if len(text) < 10:
        await message.answer("❗️ Juda qisqa. Muammoni batafsilroq yozing.")
        return

    data = await state.get_data()
    await state.set_state(None)
    report = await reports.create(session, user.id, text, data.get("report_job_id"))

    await message.answer(texts.REPORT_SENT)

    full = await reports.get(session, report.id)
    if full:
        await publisher.notify_staff(
            bot, session, texts.report_card(full), reply_markup=report_kb(full.id)
        )


# ================================================================ chek

@router.message(Pay.receipt, F.photo)
async def got_receipt(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    data = await state.get_data()
    booking_id = data.get("booking_id")
    booking = await session.get(Booking, booking_id) if booking_id else None

    if booking is None or booking.user_id != user.id:
        await state.set_state(None)
        await message.answer("❗️ Ariza topilmadi. Qaytadan yozilishga urinib ko'ring.")
        return

    if booking.status == BookingStatus.EXPIRED:
        await state.set_state(None)
        await message.answer(
            "⌛️ Afsus, vaqt tugadi va joy bo'shatildi.\n\n"
            "E'lon hali ochiq bo'lsa qaytadan yozilishingiz mumkin. "
            "Pulni o'tkazib bo'lgan bo'lsangiz administratorga yozing."
        )
        return

    if booking.status != BookingStatus.PENDING_PAYMENT:
        await state.set_state(None)
        await message.answer("Bu ariza bo'yicha chek allaqachon yuborilgan.")
        return

    # photo — turli o'lchamdagi ro'yxat, oxirgisi eng sifatlisi.
    await svc.attach_receipt(session, booking, message.photo[-1].file_id)
    await state.set_state(None)
    await message.answer(texts.RECEIPT_RECEIVED)

    # job va user bog'lanishlarini oldindan yuklaymiz: async rejimda
    # "lazy load" ishlamaydi va caption yasashda xato chiqadi.
    full = await session.scalar(
        select(Booking)
        .options(selectinload(Booking.job), selectinload(Booking.user))
        .where(Booking.id == booking.id)
    )
    if full and not await publisher.send_to_moderation(bot, session, full):
        log.error("Chek hech kimga yetib bormadi! booking=%s", full.id)
        await message.answer(
            "⚠️ Texnik nosozlik: chek administratorga yetmadi. "
            "Iltimos, administrator bilan bog'laning."
        )


@router.message(Pay.receipt, F.document)
async def receipt_as_file(message: Message) -> None:
    await message.answer(texts.NOT_A_PHOTO)


@router.message(Pay.receipt)
async def receipt_wrong(message: Message) -> None:
    await message.answer(
        "📸 Chek <b>skrinshotini</b> yuboring (rasm ko'rinishida).\n\n"
        "Bekor qilish uchun /start bosing."
    )


# ================================================================ mening ishlarim

@router.message(F.text == BTN_MY)
@router.message(Command("mening"))
async def my_jobs(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.set_state(None)
    bookings = await svc.my_bookings(session, user.id)
    if not bookings:
        await message.answer("📭 Siz hali hech qaysi ishga yozilmagansiz.")
        return

    lines = [texts.my_booking_line(b) for b in bookings]
    await message.answer(
        "📋 <b>Mening ishlarim</b>\n\n" + "\n\n".join(lines) + "\n\n"
        "<i>Tasdiqlangan ishning manzilini ko'rish uchun «🔎 Ish qidirish» → "
        "kerakli e'lonni oching.</i>"
    )
