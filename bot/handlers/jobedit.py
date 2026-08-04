"""Joylangan e'lonni tahrirlash va bekor qilish.

Nega kerak? Manzilda bitta harf xato bo'lsa, ilgari e'lonni yopib
qaytadan yaratishdan boshqa yo'l yo'q edi — lekin odamlar allaqachon
eski manzilni olgan bo'lardi va o'sha yerga borardi.

Eng muhim qism — TAFSILOT o'zgarganda tafsilotni olganlarga xabar berish.
O'zgarish jimgina bo'lsa, tahrirlashning ma'nosi yo'q.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import AdminJobCB, JobEditCB
from bot.config import CATEGORY_NAMES
from bot.db.models import UNLOCKED, Job, JobStatus, User
from bot.keyboards import (
    admin_job_kb,
    categories_kb,
    dates_kb,
    edit_job_kb,
    regions_kb,
    salaries_kb,
    skip_kb,
    slots_kb,
    times_kb,
)
from bot.permissions import is_staff
from bot.services import jobs as svc
from bot.services import notifier, publisher
from bot.states import EditJob
from bot.utils import clean, local_today, parse_date, parse_int, parse_time

log = logging.getLogger(__name__)
router = Router(name="jobedit")

# Tafsilot maydonlari: bular o'zgarsa ishchilarga XABAR berish shart,
# chunki ular allaqachon eski ma'lumot bilan yo'lga chiqqan bo'lishi mumkin.
CRITICAL = {"secret", "location", "work_date", "start_time", "region", "salary"}

FIELD_LABEL = {
    "category": "🧰 Ish turi",
    "title": "📝 Nom",
    "description": "📄 Tavsif",
    "secret": "🔒 Maxfiy ma'lumot",
    "location": "🗺 Lokatsiya",
    "region": "📍 Hudud",
    "work_date": "📅 Sana",
    "start_time": "🕗 Vaqt",
    "salary": "💰 Ish haqi",
    "slots": "👥 Kishi soni",
}

PROMPTS = {
    "category": ("Yangi ish turini tanlang:", lambda: categories_kb("ejcat")),
    "title": ("Yangi nomni yozing:", None),
    "description": ("Yangi tavsifni yozing:", None),
    "secret": ("Yangi maxfiy ma'lumotni yozing (manzil, mas'ul, telefon):", None),
    "location": ("Yangi lokatsiyani yuboring (📎 → Location):", lambda: skip_kb("ejloc")),
    "region": ("Yangi hududni tanlang:", lambda: regions_kb("ejreg")),
    "work_date": ("Yangi sanani tanlang:", lambda: dates_kb("ejdate")),
    "start_time": ("Yangi vaqtni tanlang yoki yozing:", times_kb),
    "salary": ("Yangi ish haqini tanlang yoki yozing:", salaries_kb),
    "slots": ("Nechta kishi kerak?", slots_kb),
}


async def _load(session: AsyncSession, job_id: int, user: User) -> Job | None:
    """E'lonni oladi va huquqni tekshiradi."""
    job = await svc.get_job(session, job_id)
    if job is None:
        return None
    if is_staff(user) or job.created_by == user.id:
        return job
    return None


# ================================================================ tahrirlash

@router.callback_query(AdminJobCB.filter(F.action == "edit"))
async def edit_menu(
    call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession, user: User
) -> None:
    job = await _load(session, callback_data.job_id, user)
    if job is None:
        await call.answer("Topilmadi yoki ruxsat yo'q", show_alert=True)
        return
    await call.message.answer(
        f"✏️ <b>«{job.title}» e'lonini tahrirlash</b>\n\n"
        f"Qaysi maydonni o'zgartiramiz?\n\n"
        f"<i>Manzil, sana, vaqt yoki haq o'zgarsa — yozilganlarga avtomat "
        f"xabar beriladi.</i>",
        reply_markup=edit_job_kb(job.id),
    )
    await call.answer()


@router.callback_query(JobEditCB.filter())
async def edit_field(
    call: CallbackQuery, callback_data: JobEditCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    job = await _load(session, callback_data.job_id, user)
    if job is None:
        await call.answer("Topilmadi yoki ruxsat yo'q", show_alert=True)
        return
    field = callback_data.field
    if field not in PROMPTS:
        await call.answer()
        return

    await state.set_state(EditJob.value)
    await state.update_data(edit_job_id=job.id, edit_field=field)

    prompt, kb_factory = PROMPTS[field]
    current = _current_value(job, field)
    await call.message.answer(
        f"{FIELD_LABEL[field]}\n\n<b>Hozirgi:</b> {current}\n\n{prompt}\n\n"
        f"Bekor qilish: /cancel",
        reply_markup=kb_factory() if kb_factory else None,
    )
    await call.answer()


def _current_value(job: Job, field: str) -> str:
    if field == "category":
        return CATEGORY_NAMES.get(job.category, job.category)
    if field == "work_date":
        return texts.fmt_date(job.work_date)
    if field == "salary":
        return texts.money(job.salary)
    if field == "slots":
        return f"{job.slots_total} kishi"
    if field == "location":
        return "bor ✅" if job.lat is not None else "yo'q"
    if field == "secret":
        return f"\n<i>{job.secret_details}</i>"
    if field == "description":
        return f"\n<i>{job.description}</i>"
    return str(getattr(job, {"title": "title", "region": "region",
                             "start_time": "start_time"}[field]))


# ---------------------------------------------------------------- qiymat qabul qilish

@router.message(EditJob.value, F.location)
async def got_location(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    await _apply(message, state, session, user, bot,
                 lat=message.location.latitude, lon=message.location.longitude)


@router.callback_query(EditJob.value)
async def got_choice(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    """Tugma orqali tanlangan qiymat (hudud, sana, vaqt, haq, kishi, tur)."""
    from bot.callbacks import PickCB

    try:
        picked = PickCB.unpack(call.data)
    except Exception:
        await call.answer()
        return

    data = await state.get_data()
    field = data.get("edit_field")
    value = picked.value

    if value == "__skip__":
        await call.answer()
        await _apply(call.message, state, session, user, bot, lat=None, lon=None)
        return

    parsed = _parse(field, value)
    if parsed is None:
        await call.answer("Qiymatni tushunmadim", show_alert=True)
        return
    await call.answer()
    await _apply(call.message, state, session, user, bot, value=parsed)


@router.message(EditJob.value, F.text)
async def got_text(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    data = await state.get_data()
    field = data.get("edit_field")
    parsed = _parse(field, message.text)
    if parsed is None:
        await message.answer("❗️ Qiymatni tushunmadim. Qaytadan urinib ko'ring yoki /cancel")
        return
    await _apply(message, state, session, user, bot, value=parsed)


def _parse(field: str, raw: str):  # noqa: ANN201
    """Matn yoki tugma qiymatini maydon turiga o'giradi."""
    raw = (raw or "").strip()
    if field in ("title", "description", "secret"):
        value = clean(raw, 128 if field == "title" else 1500)
        min_len = 3 if field == "title" else 10
        return value if len(value) >= min_len else None
    if field == "category":
        return raw if raw in CATEGORY_NAMES else None
    if field == "region":
        return raw or None
    if field == "work_date":
        d = parse_date(raw) or (date.fromisoformat(raw) if _iso(raw) else None)
        return d if d and d >= local_today() else None
    if field == "start_time":
        return parse_time(raw)
    if field in ("salary", "slots"):
        v = parse_int(raw)
        if v is None or v <= 0:
            return None
        return v if field == "salary" else (v if 1 <= v <= 500 else None)
    return None


def _iso(raw: str) -> bool:
    try:
        date.fromisoformat(raw)
        return True
    except ValueError:
        return False


async def _apply(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot,
    *, value=None, lat=None, lon=None,  # noqa: ANN001
) -> None:
    data = await state.get_data()
    await state.set_state(None)

    job = await _load(session, data.get("edit_job_id", 0), user)
    if job is None:
        await message.answer("E'lon topilmadi.")
        return

    field = data.get("edit_field")
    old = _current_value(job, field)

    if field == "location":
        job.lat, job.lon = lat, lon
    elif field == "secret":
        job.secret_details = value
    elif field == "slots":
        job.slots_total = value
    elif field == "work_date":
        job.work_date = value
    else:
        setattr(job, field, value)
    await session.commit()

    # Joy soni o'zgargan bo'lsa OPEN/FULL holati qayta hisoblansin.
    await svc.recompute_status(session, job)
    await publisher.sync_job_post(bot, session, job)

    new = _current_value(job, field)
    await message.answer(
        f"✅ <b>{FIELD_LABEL[field]}</b> o'zgartirildi.\n\n"
        f"Eski: {old}\nYangi: {new}"
    )

    if field in CRITICAL:
        sent = await _notify_workers(bot, session, job, field, new)
        if sent:
            await message.answer(f"📨 {sent} ta ishchiga o'zgarish haqida xabar berildi.")

    taken = await svc.taken_count(session, job.id)
    await message.answer(
        texts.job_card(job, taken, secret=True), reply_markup=admin_job_kb(job)
    )


async def _notify_workers(
    bot: Bot, session: AsyncSession, job: Job, field: str, new_value: str
) -> int:
    """Tafsilotni olganlarga o'zgarish haqida xabar."""
    bookings = await svc.job_workers(session, job.id)
    targets = [b for b in bookings if b.status in UNLOCKED]
    if not targets:
        return 0

    text = (
        f"⚠️ <b>ISH MA'LUMOTI O'ZGARDI</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {texts.fmt_date(job.work_date)} · 🕗 {job.start_time}\n\n"
        f"<b>{FIELD_LABEL[field]}</b> yangilandi:\n{new_value}\n\n"
        f"👇 To'liq ma'lumot:"
    )
    sent = 0
    for b in targets:
        try:
            await bot.send_message(b.user_id, text)
            await notifier.send_secret(bot, b.user_id, job)
            sent += 1
        except Exception as e:
            log.debug("O'zgarish xabari yetmadi (%s): %s", b.user_id, e)
        await asyncio.sleep(0.05)
    return sent


# ================================================================ bekor qilish

@router.callback_query(AdminJobCB.filter(F.action == "cancel"))
async def cancel_ask(
    call: CallbackQuery, callback_data: AdminJobCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    job = await _load(session, callback_data.job_id, user)
    if job is None:
        await call.answer("Topilmadi yoki ruxsat yo'q", show_alert=True)
        return
    if job.status == JobStatus.CANCELLED:
        await call.answer("Bu e'lon allaqachon bekor qilingan.", show_alert=True)
        return

    taken = await svc.taken_count(session, job.id)
    await state.set_state(EditJob.cancel_reason)
    await state.update_data(cancel_job_id=job.id)
    await call.message.answer(
        f"❌ <b>«{job.title}» ishini bekor qilish</b>\n\n"
        f"👥 <b>{taken} ta ishchiga</b> «ishga bormang» degan xabar boradi.\n\n"
        f"Sababini yozing (ishchilarga ko'rinadi).\n"
        f"Sababsiz: /skip · Bekor qilish: /cancel"
    )
    await call.answer()


@router.message(EditJob.cancel_reason, F.text)
async def cancel_do(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    data = await state.get_data()
    reason = None if message.text.strip() == "/skip" else clean(message.text, 250)
    await state.set_state(None)

    job = await _load(session, data.get("cancel_job_id", 0), user)
    if job is None:
        await message.answer("E'lon topilmadi.")
        return

    sent = await notifier.cancel_job(bot, session, job, reason)
    await message.answer(
        f"❌ <b>E'lon bekor qilindi.</b>\n\n"
        f"📨 {sent} ta ishchiga xabar berildi."
    )
