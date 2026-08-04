"""Admin paneli: e'lonlarni boshqarish, to'lovlar, statistika, foydalanuvchilar."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import AdminJobCB, ReportCB, WorkerCB
from bot.config import settings as env
from bot.db.models import BookingStatus, JobStatus, Role, User
from bot.keyboards import (
    BTN_ADMIN,
    BTN_ALL_ADS,
    BTN_MY_ADS,
    BTN_PAYMENTS,
    BTN_REPORTS,
    BTN_REVIEW,
    BTN_STATS,
    BTN_USERS,
    admin_job_kb,
    admin_menu,
    job_review_kb,
    jobs_list_kb,
    report_kb,
    worker_actions_kb,
)
from bot.permissions import IsAdmin, IsStaff, is_admin
from bot.services import jobs as svc
from bot.services import publisher, reports
from bot.services import settings_store as store
from bot.states import ReportFlow, Search
from bot.texts import money

log = logging.getLogger(__name__)
router = Router(name="admin")

# Butun router XODIMLAR uchun (admin + moderator). Boshqalar uchun bu
# handler'lar mavjud emasdek — xabar keyingi routerga o'tib ketadi.
# Moliya, foydalanuvchilar va bloklash ichkarida alohida IsAdmin bilan
# chegaralangan.
router.message.filter(IsStaff())
router.callback_query.filter(IsStaff())


@router.message(F.text == BTN_ADMIN)
@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    title = texts.ADMIN_WELCOME if is_admin(user) else "🛡 <b>Moderator panel</b>"
    await message.answer(title, reply_markup=admin_menu(user))


# ================================================================ e'lonlar

@router.message(F.text == BTN_ALL_ADS)
@router.message(Command("jobs"))
async def list_jobs(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    jobs = await svc.recent_jobs(session)
    if not jobs:
        await message.answer("Hali e'lon yaratilmagan.")
        return
    await message.answer("📢 <b>So'nggi e'lonlar</b>", reply_markup=jobs_list_kb(jobs))


@router.callback_query(AdminJobCB.filter(F.action == "view"))
async def job_view(call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession) -> None:
    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    taken = await svc.taken_count(session, job.id)
    waiting = await svc.waitlist_count(session, job.id)
    await call.message.answer(
        texts.job_card(job, taken, secret=True, waitlist=waiting),
        reply_markup=admin_job_kb(job),
    )
    await call.answer()


@router.callback_query(AdminJobCB.filter(F.action == "workers"))
async def job_workers(call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession) -> None:
    bookings = await svc.job_workers(session, callback_data.job_id)
    if not bookings:
        await call.answer("Hali hech kim yozilmagan.", show_alert=True)
        return

    await call.answer()
    await call.message.answer(f"👥 <b>E'lon #{callback_data.job_id} — yozilganlar</b>")
    for i, b in enumerate(bookings, 1):
        text = (
            f"{i}. {texts.BOOKING_STATUS_LABEL[b.status]}\n"
            f"👤 {b.user.mention}\n"
            f"📱 <code>{b.user.phone or '—'}</code>\n"
            f"📊 {b.user.reliability}"
        )
        # Belgilash tugmalari faqat to'lovi tasdiqlanganlar uchun mantiqiy.
        kb = worker_actions_kb(b.id) if b.status == BookingStatus.CONFIRMED else None
        await call.message.answer(text, reply_markup=kb)


@router.callback_query(AdminJobCB.filter(F.action.in_({"close", "reopen"})))
async def job_toggle(
    call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession, bot: Bot
) -> None:
    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer("Topilmadi", show_alert=True)
        return

    if callback_data.action == "close":
        job.status = JobStatus.CLOSED
    else:
        taken = await svc.taken_count(session, job.id)
        job.status = JobStatus.FULL if taken >= job.slots_total else JobStatus.OPEN
    await session.commit()

    await publisher.sync_job_post(bot, session, job)
    await call.answer("✅ O'zgartirildi")

    taken = await svc.taken_count(session, job.id)
    await call.message.edit_text(
        texts.job_card(job, taken, secret=True), reply_markup=admin_job_kb(job)
    )


@router.callback_query(AdminJobCB.filter(F.action == "fee"))
async def job_toggle_fee(
    call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession, bot: Bot
) -> None:
    """E'lonni bepulga o'tkazish yoki qayta pulli qilish.

    Kimdir allaqachon pul to'lagan bo'lsa narxni o'zgartirmaymiz — bu
    adolatsizlik va janjal keltiradi.
    """
    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    if await svc.has_money_bookings(session, job.id):
        await call.answer(
            "Bu e'londa to'lov qilganlar bor — narxni o'zgartirib bo'lmaydi.",
            show_alert=True,
        )
        return

    new_fee = store.default_fee() if job.fee <= 0 else 0
    await svc.set_fee(session, job, new_fee)
    await call.answer("🆓 Bepul bo'ldi" if new_fee == 0 else f"💳 {money(new_fee)}")

    # Kanallardagi postda ham darhol ko'rinsin.
    await publisher.sync_job_post(bot, session, job)
    taken = await svc.taken_count(session, job.id)
    await call.message.edit_text(
        texts.job_card(job, taken, secret=True), reply_markup=admin_job_kb(job)
    )


@router.callback_query(AdminJobCB.filter(F.action == "repost"))
async def job_repost(
    call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession, bot: Bot
) -> None:
    """Kanalga joylash muvaffaqiyatsiz bo'lgan e'lonni qayta urinish."""
    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    posted, errors = await publisher.publish_job(bot, session, job)
    await call.answer(f"📢 {posted} ta kanalga joylandi" if posted else "Kanal ulanmagan")
    if errors:
        await call.message.answer("⚠️ Xatolar:\n" + "\n".join(errors)[:900])


# ================================================================ to'lovlar

@router.message(F.text == BTN_PAYMENTS)
@router.message(Command("pending"))
async def pending(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await state.set_state(None)
    items = await svc.pending_receipts(session)
    if not items:
        await message.answer("✅ Kutayotgan to'lov yo'q.")
        return
    await message.answer(f"💳 <b>{len(items)} ta to'lov tekshirilmagan</b>")
    for b in items:
        await publisher.send_to_moderation(bot, session, b)


@router.message(F.text == BTN_REVIEW)
@router.message(Command("review"))
async def review(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    jobs = await svc.pending_jobs(session)
    if not jobs:
        await message.answer("✅ Tasdiq kutayotgan e'lon yo'q.")
        return
    await message.answer(f"🕓 <b>{len(jobs)} ta e'lon tasdiq kutmoqda</b>")
    for job in jobs:
        await message.answer(
            texts.job_review_caption(job, job.creator), reply_markup=job_review_kb(job.id)
        )


# ================================================================ murojaatlar

@router.message(F.text == BTN_REPORTS)
@router.message(Command("murojaat"))
async def reports_list(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    items = await reports.open_reports(session)
    if not items:
        await message.answer("✅ Ochiq murojaat yo'q.")
        return
    await message.answer(f"🆘 <b>{len(items)} ta murojaat kutmoqda</b>")
    for r in items:
        await message.answer(texts.report_card(r), reply_markup=report_kb(r.id))


@router.callback_query(ReportCB.filter(F.action == "close"))
async def report_close(
    call: CallbackQuery, callback_data: ReportCB, session: AsyncSession, user: User
) -> None:
    report = await reports.get(session, callback_data.report_id)
    if report is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    await reports.close(session, report, user.id)
    await call.answer("✅ Yopildi")
    try:
        await call.message.edit_text(
            (call.message.text or "") + f"\n\n✅ <b>YOPILDI</b> — {user.full_name}",
            reply_markup=None,
        )
    except Exception:
        pass


@router.callback_query(ReportCB.filter(F.action == "answer"))
async def report_answer_ask(
    call: CallbackQuery, callback_data: ReportCB, state: FSMContext, session: AsyncSession
) -> None:
    report = await reports.get(session, callback_data.report_id)
    if report is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    await state.set_state(ReportFlow.answer)
    await state.update_data(report_id=report.id, src_message_id=call.message.message_id)
    await call.message.answer(texts.ASK_REPORT_ANSWER)
    await call.answer()


@router.message(ReportFlow.answer, F.text)
async def report_answer_send(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    data = await state.get_data()
    await state.set_state(None)

    report = await reports.get(session, data.get("report_id", 0))
    if report is None:
        await message.answer("Murojaat topilmadi.")
        return

    answer = message.text.strip()[:2000]
    await reports.answer(session, report, user.id, answer)

    try:
        await bot.send_message(report.user_id, texts.report_answer(answer))
        await message.answer(f"✅ Javob yuborildi (murojaat #{report.id}).")
    except Exception as e:
        await message.answer(f"⚠️ Javob yetib bormadi: {e}"[:300])

    if src := data.get("src_message_id"):
        try:
            await bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=src, reply_markup=None
            )
        except Exception:
            pass


# ================================================================ statistika

# Moliyaviy ma'lumot faqat adminga — moderator tushumni ko'rmaydi.
@router.message(F.text == BTN_STATS, IsAdmin())
@router.message(Command("stats"), IsAdmin())
async def stats(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    s = await svc.stats(session)
    open_reports = await reports.open_count(session)
    done = s["completed"]
    total_marked = done + s["no_show"]
    rate = f"{done * 100 // total_marked}%" if total_marked else "—"

    await message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👤 Foydalanuvchi: <b>{s['users']}</b> (faol: {s['active']})\n"
        f"   🔎 ishchi: {s['workers']} · 🏢 ish beruvchi: {s['employers']}\n\n"
        f"📢 Jami e'lon: <b>{s['jobs']}</b>\n"
        f"   🟢 ochiq: {s['open_jobs']} · 🕓 tasdiq kutmoqda: {s['review_jobs']}\n\n"
        f"✅ Tasdiqlangan: <b>{s['confirmed']}</b>\n"
        f"🏁 Ishga chiqqan: <b>{done}</b> · 🚷 chiqmagan: <b>{s['no_show']}</b>\n"
        f"📈 Chiqish darajasi: <b>{rate}</b>\n"
        f"🔎 Tekshiruvda: {s['waiting']} · ⏳ navbatda: {s['waitlist']}\n"
        f"🎁 Bonus bilan: {s['credits_used']}\n"
        f"🆘 Ochiq murojaat: <b>{open_reports}</b>\n\n"
        f"💰 Yig'ilgan to'lov: <b>{money(s['revenue'])}</b>"
    )


# ================================================================ foydalanuvchilar

# Shaxsiy ma'lumotlar (telefon raqamlar) ham faqat adminga.
@router.message(F.text == BTN_USERS, IsAdmin())
@router.message(Command("users"), IsAdmin())
async def users_cmd(message: Message, state: FSMContext) -> None:
    await state.set_state(Search.user_query)
    await message.answer(
        "👥 <b>Foydalanuvchi qidirish</b>\n\n"
        "Telegram ID yoki @username yuboring.\n\n"
        "Bekor qilish: /cancel"
    )


@router.message(Search.user_query, F.text, IsAdmin())
async def users_find(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    found = await svc.find_user(session, message.text)
    if found is None:
        await message.answer("❌ Topilmadi. ID yoki @username to'g'ri ekaniga ishonch hosil qiling.")
        return

    bookings = await svc.my_bookings(session, found.id, limit=5)
    lines = "\n".join(texts.my_booking_line(b) for b in bookings) or "— hali yozilmagan"
    await message.answer(
        f"👤 <b>{found.full_name}</b>\n"
        f"{'@' + found.username if found.username else '—'}\n"
        f"📱 <code>{found.phone or '—'}</code>\n"
        f"📍 {found.region or '—'} · {found.role.value}\n"
        f"📊 {found.reliability}\n"
        f"{'🚫 BLOKLANGAN' if found.is_blocked else '✅ Faol'}\n"
        f"🆔 <code>{found.id}</code>\n\n"
        f"<b>So'nggi arizalar:</b>\n{lines}\n\n"
        f"Bloklash/ochish: /block {found.id}"
    )


@router.message(Command("block"), IsAdmin())
async def block_user(message: Message, command, session: AsyncSession) -> None:  # noqa: ANN001
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Ishlatilishi: <code>/block 123456789</code>")
        return
    target = await session.get(User, int(arg))
    if target is None:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return
    if target.id in env.admins:
        await message.answer("❗️ Administratorni bloklab bo'lmaydi.")
        return

    target.is_blocked = not target.is_blocked
    await session.commit()
    await message.answer(
        f"{'🚫 Bloklandi' if target.is_blocked else '✅ Blok olib tashlandi'}: "
        f"{target.mention}"
    )


@router.callback_query(WorkerCB.filter())
async def worker_action(
    call: CallbackQuery, callback_data: WorkerCB, session: AsyncSession, bot: Bot, user: User
) -> None:
    """Ish tugagach ishchini belgilash: chiqdi / chiqmadi / bloklash.

    Bu reyting tizimining poydevori: keyingi safar chekni tasdiqlashda
    adminga «3/5 ishga chiqqan» deb ko'rsatiladi.
    """
    from bot.db.models import Booking

    booking = await session.get(Booking, callback_data.booking_id)
    if booking is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    target = await session.get(User, booking.user_id)

    if callback_data.action == "done":
        await svc.mark_completed(session, booking)
        await call.answer("✅ Belgilandi")
        suffix = "✅ Ishga chiqdi"
    elif callback_data.action == "noshow":
        await svc.mark_no_show(session, booking)
        await call.answer("🚷 Belgilandi")
        suffix = "🚷 Ishga chiqmadi"
        try:
            await bot.send_message(
                booking.user_id,
                "🚷 Siz yozilgan ishga chiqmagansiz deb belgilandingiz.\n\n"
                "Bu profilingizda ko'rinadi. Xato bo'lsa administratorga yozing.",
            )
        except Exception:
            pass
    else:
        # Bloklash — jiddiy va qaytarish qiyin amal, faqat admin qiladi.
        if not is_admin(user):
            await call.answer("Bloklash faqat administrator qo'lidan keladi.", show_alert=True)
            return
        if target and target.id not in env.admins:
            target.is_blocked = True
            await session.commit()
        await call.answer("🚫 Bloklandi")
        suffix = "🚫 Bloklandi"

    try:
        await call.message.edit_text(
            (call.message.text or "") + f"\n\n<b>{suffix}</b>", reply_markup=None
        )
    except Exception:
        pass
