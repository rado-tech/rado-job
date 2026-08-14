"""Admin paneli: e'lonlarni boshqarish, to'lovlar, statistika, foydalanuvchilar."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import AdminJobCB, ReportCB, UserCB, UsersCB
from bot.db.models import UNLOCKED, JobStatus, Role, User
from bot.i18n import use_lang
from bot.keyboards import (
    variants,
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
    user_card_kb,
    users_list_kb,
    worker_actions_kb,
)
from bot.permissions import IsAdmin, IsStaff, is_admin, is_owner
from bot.services import audit, channels, jobs as svc
from bot.services import publisher, ratings, reports
from bot.services import settings_store as store
from bot.states import ReportFlow, Search

log = logging.getLogger(__name__)
router = Router(name="admin")

# Butun router XODIMLAR uchun (admin + moderator). Boshqalar uchun bu
# handler'lar mavjud emasdek — xabar keyingi routerga o'tib ketadi.
# Moliya, foydalanuvchilar va bloklash ichkarida alohida IsAdmin bilan
# chegaralangan.
router.message.filter(IsStaff())
router.callback_query.filter(IsStaff())


@router.message(F.text.in_(variants("admin")))
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
        # Baho faqat shu yerda (xodimlar ko'radigan ro'yxatda) ko'rinadi.
        summary = await ratings.summary_for(session, b.user_id)
        text = (
            f"{i}. {texts.BOOKING_STATUS_LABEL[b.status]}\n"
            f"👤 {b.user.mention}\n"
            f"📱 <code>{b.user.phone or '—'}</code>\n"
            f"📊 {b.user.reliability} · {ratings.line(summary)}"
        )
        # Tugmalar tafsilotlarni olgan hamma uchun ko'rinadi — shu jumladan
        # allaqachon belgilanganlar uchun ham, chunki xato bosilgan qarorni
        # tuzatish imkoni bo'lishi kerak.
        kb = worker_actions_kb(b.id) if b.status in UNLOCKED else None
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
    await audit.log_action(
        session, call.from_user.id,
        "job_close" if callback_data.action == "close" else "job_reopen",
        f"e'lon #{job.id}", job.title,
    )

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
    await call.answer("🆓 Bepul bo'ldi" if new_fee == 0 else f"💳 {texts.money(new_fee)}")
    await audit.log_action(
        session, call.from_user.id, "job_fee", f"e'lon #{job.id}",
        "bepul" if new_fee == 0 else texts.money(new_fee),
    )

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
    """Kanallarga (qayta) joylash — tanlov bilan.

    broadcast=False: obunachilarga bot orqali xabar KETMAYDI — ular buni
    e'lon birinchi chiqqanda allaqachon olishgan, ikkinchi marta yuborish
    spam bo'lardi.
    """
    from bot.handlers.jobpost import offer_publish_choice

    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    if not await offer_publish_choice(call.message, session, job, broadcast=False):
        await call.answer("Kanal ulanmagan", show_alert=True)
        return
    await call.answer()


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
    await audit.log_action(session, user.id, "report_close", f"murojaat #{report.id}")
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
    await audit.log_action(session, user.id, "report_answer", f"murojaat #{report.id}")

    try:
        # Javob murojaat EGASINING tilida ketadi.
        target = await session.get(User, report.user_id)
        with use_lang(target.lang if target else None):
            note = texts.report_answer(answer)
        await bot.send_message(report.user_id, note)
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
        f"💰 Yig'ilgan to'lov: <b>{texts.money(s['revenue'])}</b>\n\n"
        f"<i>Kunlik hisobot har kuni soat 21:00 da keladi. Hoziroq ko'rish "
        f"uchun /hisobot</i>"
    )

    # Qaysi kanal odam olib kelyapti — reklamani qayerga sarflash shundan.
    rows = await svc.channel_attribution(session)
    if rows:
        names = {c.id: c.title or str(c.chat_id) for c in await channels.all_channels(session)}
        lines = []
        for cid, count in rows[:10]:
            label = names.get(cid, "bevosita botdan") if cid else "bevosita botdan"
            lines.append(f"• {label} — <b>{count}</b>")
        await message.answer("📡 <b>Yozilishlar manbasi</b>\n\n" + "\n".join(lines))


@router.message(Command("hisobot"), IsAdmin())
async def daily_report_now(message: Message, session: AsyncSession) -> None:
    """Kunlik hisobotni kutmasdan ko'rish."""
    from datetime import datetime, timedelta, timezone

    from bot.config import TZ

    now = datetime.now(TZ)
    since = (now - timedelta(days=1)).astimezone(timezone.utc)
    summary = await svc.daily_summary(session, since)
    await message.answer(texts.daily_report(summary, now.strftime("%d.%m.%Y")))


# ================================================================ foydalanuvchilar

# Shaxsiy ma'lumotlar (telefon raqamlar) ham faqat adminga.
USERS_PER_PAGE = 10


async def show_users(
    message: Message, state: FSMContext, session: AsyncSession,
    *, page: int = 0, edit: bool = False
) -> None:
    data = await state.get_data()
    only_blocked = bool(data.get("u_blocked"))

    users, total = await svc.list_users(
        session,
        offset=page * USERS_PER_PAGE,
        limit=USERS_PER_PAGE,
        only_blocked=only_blocked,
    )
    if not users:
        text = "🚫 Bloklangan foydalanuvchi yo'q." if only_blocked else "👥 Foydalanuvchi yo'q."
    else:
        head = "🚫 <b>Bloklanganlar</b>" if only_blocked else "👥 <b>Foydalanuvchilar</b>"
        text = f"{head} — jami <b>{total}</b>\n\nBatafsil ko'rish uchun bosing 👇"

    kb = users_list_kb(
        users, page=page, total=total, per_page=USERS_PER_PAGE, only_blocked=only_blocked
    )
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)


@router.message(F.text == BTN_USERS, IsAdmin())
@router.message(Command("users"), IsAdmin())
async def users_cmd(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    await state.update_data(u_blocked=False)
    await show_users(message, state, session, page=0)


@router.callback_query(UsersCB.filter(), IsAdmin())
async def users_nav(
    call: CallbackQuery, callback_data: UsersCB, state: FSMContext, session: AsyncSession
) -> None:
    if callback_data.action == "search":
        await state.set_state(Search.user_query)
        await call.message.answer(
            "🔎 <b>Qidirish</b>\n\n"
            "ID, @username yoki <b>ismning bir qismini</b> yozing.\n"
            "<i>To'liq yozish shart emas.</i>\n\n"
            "Bekor qilish: /cancel"
        )
        await call.answer()
        return

    if callback_data.action in ("blocked", "all"):
        await state.update_data(u_blocked=callback_data.action == "blocked")
        await show_users(call.message, state, session, page=0, edit=True)
        await call.answer()
        return

    await show_users(call.message, state, session, page=callback_data.page, edit=True)
    await call.answer()


async def show_user_card(message: Message, session: AsyncSession, target: User) -> None:
    bookings = await svc.my_bookings(session, target.id, limit=5)
    lines = "\n".join(texts.my_booking_line(b) for b in bookings) or "— hali yozilmagan"
    role_name = {
        Role.WORKER: "👷 Ish qidiruvchi",
        Role.EMPLOYER: "🏢 Ish beruvchi",
        Role.MODERATOR: "🛡 Moderator",
        Role.ADMIN: "👑 Administrator",
    }[target.role]
    # O'zaro baholar natijasi FAQAT shu yerda (admin kartochkasida) ko'rinadi.
    summary = await ratings.summary_for(session, target.id)

    await message.answer(
        f"{'🚫 <b>BLOKLANGAN</b>' if target.is_blocked else '✅ Faol'}\n\n"
        f"👤 <b>{target.full_name or '—'}</b>\n"
        f"{'@' + target.username if target.username else '—'}\n"
        f"📱 <code>{target.phone or '—'}</code>\n"
        f"📍 {target.region or '—'}\n"
        f"🎭 {role_name}\n"
        f"📊 {target.reliability} · {ratings.line(summary)}\n"
        f"🎫 Bonus: {target.free_credits or 0} · 👥 chaqirgan: {target.invited_count or 0}\n"
        f"🆔 <code>{target.id}</code>\n\n"
        f"<b>So'nggi arizalar:</b>\n{lines}",
        reply_markup=user_card_kb(target, is_owner_account=is_owner(target.id)),
    )


@router.message(Search.user_query, F.text, IsAdmin())
async def users_find(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    found = await svc.search_users(session, message.text)

    if not found:
        await message.answer("❌ Topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return
    if len(found) == 1:
        await show_user_card(message, session, found[0])
        return

    await message.answer(
        f"🔎 <b>Topildi: {len(found)} ta</b>",
        reply_markup=users_list_kb(
            found, page=0, total=len(found), per_page=USERS_PER_PAGE, only_blocked=False
        ),
    )


@router.callback_query(UserCB.filter(), IsAdmin())
async def user_action(
    call: CallbackQuery, callback_data: UserCB, session: AsyncSession, bot: Bot
) -> None:
    target = await session.get(User, callback_data.user_id)
    if target is None:
        await call.answer("Topilmadi", show_alert=True)
        return

    action = callback_data.action
    if action != "view" and is_owner(target.id):
        await call.answer("Asosiy adminga tegib bo'lmaydi.", show_alert=True)
        return

    if action == "block":
        await svc.set_blocked(session, target, True)
        await call.answer("🚫 Bloklandi")
        await audit.log_action(session, call.from_user.id, "user_block", target.mention)
    elif action == "unblock":
        await svc.set_blocked(session, target, False)
        await call.answer("✅ Blokdan chiqarildi")
        await audit.log_action(session, call.from_user.id, "user_unblock", target.mention)
        try:
            with use_lang(target.lang):
                note = texts.ACCOUNT_UNBLOCKED
            await bot.send_message(target.id, note)
        except Exception:
            pass
    elif action in ("mod", "unmod"):
        target.role = Role.MODERATOR if action == "mod" else Role.WORKER
        await session.commit()
        await call.answer("🛡 Moderator" if action == "mod" else "🗑 Moderator emas")
        await audit.log_action(
            session, call.from_user.id,
            "user_mod" if action == "mod" else "user_unmod", target.mention,
        )
        try:
            await bot.send_message(
                target.id,
                "🛡 <b>Sizga moderator huquqi berildi.</b>\n\n/start bosib menyuni yangilang."
                if action == "mod"
                else "ℹ️ Moderator huquqingiz olib tashlandi.",
            )
        except Exception:
            pass
    else:
        await call.answer()

    await session.refresh(target)
    await show_user_card(call.message, session, target)


# Eslatma: WorkerCB (ishga chiqdi/chiqmadi/bloklash) handler'i endi
# handlers/common.py da. Sababi: bu tugmalar ISH BERUVCHIGA ham yuboriladi
# (davomat so'rovi), bu router esa faqat xodimlarga ochiq — ish beruvchi
# bosganda hech narsa bo'lmasdi.
