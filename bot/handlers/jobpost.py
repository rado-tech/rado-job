"""E'lon yaratish — admin va ish beruvchi uchun BITTA umumiy jarayon.

Farqi faqat oxirida: admin bosganda e'lon darhol chiqadi, ish beruvchi
bosganda tasdiqqa yuboriladi. Ikkita alohida nusxa yozish — ikkita alohida
xato manbai demak, shuning uchun jarayon yagona.

Soddalashtirish uchun qilingan ishlar:
  * har qadamda tayyor tugmalar (vaqt, haq, kishi soni, sana) — yozish shart emas
  * oldindan ko'rishdan istalgan maydonni alohida tuzatish (avval hammasini
    boshidan qaytadan qilish kerak edi)
  * ♻️ Takrorlash — eski e'londan nusxa olib, faqat sanani so'raydi
"""

from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import AdminJobCB, EditCB, PickCB
from bot.config import CATEGORY_NAMES, category_name
from bot.db.models import UNLOCKED, Job, JobStatus, Role, User
from bot.keyboards import (
    BTN_NEW_JOB,
    variants,
    admin_job_kb,
    categories_kb,
    dates_kb,
    fee_kb,
    job_review_kb,
    jobs_list_kb,
    preview_kb,
    publish_choice_kb,
    regions_kb,
    salaries_kb,
    skip_kb,
    slots_kb,
    times_kb,
)
from bot.permissions import is_staff
from bot.services import channels as ch
from bot.services import jobs as svc
from bot.services import publisher
from bot.services import settings_store as store
from bot.states import NewJob
from bot import tg
from bot.utils import clean, local_today, parse_date, parse_int, parse_time

log = logging.getLogger(__name__)
router = Router(name="jobpost")

# Qadamlar ketma-ketligi. Tahrirlashda shu ro'yxatdan foydalanamiz.
ORDER = [
    "category", "title", "description", "secret", "location", "region",
    "work_date", "start_time", "salary", "slots", "fee",
]
STATE_OF = {
    "category": NewJob.category,
    "title": NewJob.title,
    "description": NewJob.description,
    "secret": NewJob.secret,
    "location": NewJob.location,
    "region": NewJob.region,
    "work_date": NewJob.work_date,
    "start_time": NewJob.start_time,
    "salary": NewJob.salary,
    "slots": NewJob.slots,
    "fee": NewJob.fee,
}


def _can_post(user: User) -> bool:
    return is_staff(user) or user.role == Role.EMPLOYER


# ================================================================ boshlash

@router.message(F.text.in_({BTN_NEW_JOB} | variants("post")))
@router.message(Command("newjob"))
async def start_new(message: Message, state: FSMContext, user: User) -> None:
    if not _can_post(user):
        return
    if not store.is_payment_ready() and is_staff(user):
        await message.answer(texts.PAYMENT_NOT_READY)
        return
    await state.clear()
    await state.update_data(fee=0 if store.free_mode() else store.default_fee())

    # Ish beruvchi to'lov masalasini umuman ko'rmaydi: ishchilar to'laydimi
    # yoki yo'qmi — bu bizning tarifimiz, uning ishi emas. Unga faqat
    # xodimlar uchun mo'ljallangan eslatma ham chiqmaydi.
    if store.free_mode() and is_staff(user):
        await message.answer(
            "🆓 <b>Bepul rejim yoqilgan</b> — bu e'lon bepul bo'ladi.\n"
            "<i>Faqat shu e'lonni pulli qilmoqchi bo'lsangiz, oxirida "
            "«✏️ To'lov» tugmasidan foydalaning.</i>"
        )
    await _ask(message, state, "category")


@router.message(F.text.in_(variants("myads")))
async def my_ads(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    """Ish beruvchining o'z e'lonlari."""
    await state.set_state(None)
    jobs = await svc.jobs_by_author(session, user.id)
    if not jobs:
        await message.answer(texts.MY_ADS_EMPTY)
        return
    await message.answer(texts.MY_ADS_TITLE, reply_markup=jobs_list_kb(jobs))


@router.callback_query(AdminJobCB.filter(F.action == "view"))
async def owner_job_view(
    call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession, user: User
) -> None:
    """Ish beruvchi o'z e'lonini ko'radi (admin uchun alohida handler bor)."""
    job = await svc.get_job(session, callback_data.job_id)
    if job is None or job.created_by != user.id:
        await call.answer(texts.NOT_FOUND, show_alert=True)
        return
    taken = await svc.taken_count(session, job.id)
    # Ish beruvchi yozilish to'lovini ko'rmaydi — bu bizning tarifimiz.
    text = texts.job_card(job, taken, secret=True, show_fee=is_staff(user))
    if job.status == JobStatus.DECLINED and job.decline_reason:
        text += f"\n\n🚫 Rad etish sababi: <i>{job.decline_reason}</i>"
    await call.message.answer(text, reply_markup=admin_job_kb(job, owner_view=True))
    await call.answer()


@router.callback_query(AdminJobCB.filter(F.action == "workers"))
async def owner_job_workers(
    call: CallbackQuery, callback_data: AdminJobCB, session: AsyncSession, user: User
) -> None:
    job = await svc.get_job(session, callback_data.job_id)
    if job is None or job.created_by != user.id:
        await call.answer(texts.NOT_FOUND, show_alert=True)
        return
    bookings = await svc.job_workers(session, job.id)
    # UNLOCKED = tafsilotlarni olgan hamma: tasdiqlangan, ishga chiqqan va
    # chiqmagan. Ilgari faqat CONFIRMED sanalardi va «ishga chiqdi» deb
    # belgilangach ishchi ro'yxatdan YO'QOLARDI.
    confirmed = [b for b in bookings if b.status in UNLOCKED]
    if not confirmed:
        await call.answer(texts.NO_WORKERS_YET, show_alert=True)
        return
    lines = [
        f"{i}. {texts.BOOKING_STATUS_LABEL[b.status]}\n"
        f"    <b>{b.user.full_name}</b> · 📱 <code>{b.user.phone}</code>\n"
        f"    📊 {b.user.reliability}"
        for i, b in enumerate(confirmed, 1)
    ]
    await call.message.answer(
        texts.job_workers_title(job) + "\n\n" + "\n".join(lines)
    )
    await call.answer()


# ================================================================ qadamlar

# DIQQAT: bu yerda matnning O'ZI emas, NOMI saqlanadi.
#
# Agar `texts.NEW_JOB_TITLE` deb yozsak, qiymat modul yuklanganda bir marta
# hisoblanadi va o'zbekchaga QOTIB qoladi — ruscha foydalanuvchi baribir
# o'zbekcha ko'radi. Nomni saqlab, har chaqiruvda getattr qilamiz.
PROMPT_ATTR = {
    "category": "NEW_JOB_CATEGORY",
    "title": "NEW_JOB_TITLE",
    "description": "NEW_JOB_DESC",
    "secret": "NEW_JOB_SECRET",
    "location": "NEW_JOB_LOCATION",
    "region": "NEW_JOB_REGION",
    "work_date": "NEW_JOB_DATE",
    "start_time": "NEW_JOB_TIME",
    "salary": "NEW_JOB_SALARY",
    "slots": "NEW_JOB_SLOTS",
    "fee": "NEW_JOB_FEE",
}

KB_FACTORY = {
    "category": lambda: categories_kb("njcat"),
    "location": lambda: skip_kb("njloc"),
    "region": lambda: regions_kb("njreg"),
    "work_date": lambda: dates_kb("njdate"),
    "start_time": times_kb,
    "salary": salaries_kb,
    "slots": slots_kb,
    "fee": lambda: fee_kb(store.default_fee()),
}


def prompt_for(field: str) -> str:
    """Qadam matni — joriy tilda."""
    return getattr(texts, PROMPT_ATTR[field])


async def _ask(message: Message, state: FSMContext, field: str) -> None:
    await state.set_state(STATE_OF[field])
    factory = KB_FACTORY.get(field)
    await message.answer(
        prompt_for(field), reply_markup=factory() if factory else None
    )


async def _next(message: Message, state: FSMContext, field: str, user: User) -> None:
    """Qiymat saqlangach: tahrirlash rejimida bo'lsak — oldindan ko'rishga,
    aks holda keyingi qadamga."""
    data = await state.get_data()
    if data.get("editing"):
        await state.update_data(editing=False)
        await send_preview(message, state, user)
        return
    idx = ORDER.index(field)
    if idx + 1 >= len(ORDER):
        await send_preview(message, state, user)
        return

    nxt = ORDER[idx + 1]
    # To'lov qadami quyidagi hollarda so'ralmaydi:
    #   * bepul rejim yoqilgan — e'lon avtomat bepul
    #   * e'lonni ISH BERUVCHI berayotgan — narxni biz belgilaymiz
    # Xodim kerak bo'lsa oldindan ko'rishdagi «✏️ To'lov» bilan o'zgartiradi.
    if nxt == "fee" and (store.free_mode() or not is_staff(user)):
        await state.update_data(fee=0 if store.free_mode() else store.default_fee())
        await send_preview(message, state, user)
        return

    await _ask(message, state, nxt)


@router.callback_query(NewJob.category, PickCB.filter(F.field == "njcat"))
async def s_category(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    await state.update_data(category=callback_data.value)
    await call.message.edit_text(texts.SAVED_CATEGORY.format(v=category_name(callback_data.value)))
    await call.answer()
    await _next(call.message, state, "category", user)


@router.message(NewJob.title, F.text)
async def s_title(message: Message, state: FSMContext, user: User) -> None:
    value = clean(message.text, 128)
    if len(value) < 3:
        await message.answer(texts.TOO_SHORT.format(n=3))
        return
    await state.update_data(title=value)
    await _next(message, state, "title", user)


@router.message(NewJob.description, F.text)
async def s_desc(message: Message, state: FSMContext, user: User) -> None:
    value = clean(message.text, 1500)
    if len(value) < 10:
        await message.answer(texts.TOO_SHORT.format(n=10))
        return
    await state.update_data(description=value)
    await _next(message, state, "description", user)


@router.message(NewJob.secret, F.text)
async def s_secret(message: Message, state: FSMContext, user: User) -> None:
    value = clean(message.text, 1000)
    if len(value) < 10:
        await message.answer(texts.TOO_SHORT.format(n=10))
        return
    await state.update_data(secret=value)
    await _next(message, state, "secret", user)


@router.message(NewJob.location, F.location)
async def s_location(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await message.answer(texts.SAVED_LOCATION)
    await _next(message, state, "location", user)


@router.message(NewJob.location, F.venue)
async def s_venue(message: Message, state: FSMContext, user: User) -> None:
    """Telegram «Venue» — nomlangan joy. Undan ham koordinata olamiz."""
    await state.update_data(
        lat=message.venue.location.latitude, lon=message.venue.location.longitude
    )
    await message.answer(texts.SAVED_LOCATION_NAMED.format(v=message.venue.title))
    await _next(message, state, "location", user)


@router.callback_query(NewJob.location, PickCB.filter(F.field == "njloc"))
async def s_location_skip(call: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(lat=None, lon=None)
    await call.message.edit_text(texts.SKIPPED_LOCATION)
    await call.answer()
    await _next(call.message, state, "location", user)


@router.message(NewJob.location, F.text)
async def s_location_wrong(message: Message) -> None:
    await message.answer(
        "❗️ Bu lokatsiya emas.\n\n"
        "📎 → <b>Location</b> → xaritada joyni tanlang → yuboring.\n"
        "Yoki yuqoridagi «⏭ O'tkazib yuborish» tugmasini bosing."
    )


@router.callback_query(NewJob.region, PickCB.filter(F.field == "njreg"))
async def s_region(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    await state.update_data(region=callback_data.value)
    await call.message.edit_text(texts.SAVED_REGION.format(v=callback_data.value))
    await call.answer()
    await _next(call.message, state, "region", user)


@router.callback_query(NewJob.work_date, PickCB.filter(F.field == "njdate"))
async def s_date_btn(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    d = date.fromisoformat(callback_data.value)
    await state.update_data(work_date=d.isoformat())
    await call.message.edit_text(texts.SAVED_DATE.format(v=texts.fmt_date(d)))
    await call.answer()
    await _next(call.message, state, "work_date", user)


@router.message(NewJob.work_date, F.text)
async def s_date_text(message: Message, state: FSMContext, user: User) -> None:
    d = parse_date(message.text)
    if d is None:
        await message.answer(texts.BAD_DATE)
        return
    if d < local_today():
        await message.answer(texts.BAD_PAST_DATE)
        return
    await state.update_data(work_date=d.isoformat())
    await _next(message, state, "work_date", user)


@router.callback_query(NewJob.start_time, PickCB.filter(F.field == "time"))
async def s_time_btn(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    value = parse_time(callback_data.value) or "08:00"
    await state.update_data(start_time=value)
    await call.message.edit_text(texts.SAVED_TIME.format(v=value))
    await call.answer()
    await _next(call.message, state, "start_time", user)


@router.message(NewJob.start_time, F.text)
async def s_time_text(message: Message, state: FSMContext, user: User) -> None:
    t = parse_time(message.text)
    if t is None:
        await message.answer(texts.BAD_TIME)
        return
    await state.update_data(start_time=t)
    await _next(message, state, "start_time", user)


@router.callback_query(NewJob.salary, PickCB.filter(F.field == "salary"))
async def s_salary_btn(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    await state.update_data(salary=int(callback_data.value))
    await call.message.edit_text(texts.SAVED_SALARY.format(v=texts.money(int(callback_data.value))))
    await call.answer()
    await _next(call.message, state, "salary", user)


@router.message(NewJob.salary, F.text)
async def s_salary_text(message: Message, state: FSMContext, user: User) -> None:
    v = parse_int(message.text)
    if v is None or v <= 0:
        await message.answer(texts.BAD_NUMBER)
        return
    await state.update_data(salary=v)
    await _next(message, state, "salary", user)


@router.callback_query(NewJob.slots, PickCB.filter(F.field == "slots"))
async def s_slots_btn(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    await state.update_data(slots=int(callback_data.value))
    await call.message.edit_text(texts.SAVED_SLOTS.format(v=callback_data.value))
    await call.answer()
    await _next(call.message, state, "slots", user)


@router.message(NewJob.slots, F.text)
async def s_slots_text(message: Message, state: FSMContext, user: User) -> None:
    v = parse_int(message.text)
    if v is None or not (1 <= v <= 500):
        await message.answer(texts.BAD_SLOTS)
        return
    await state.update_data(slots=v)
    await _next(message, state, "slots", user)


@router.callback_query(NewJob.fee, PickCB.filter(F.field == "fee"))
async def s_fee_btn(call: CallbackQuery, callback_data: PickCB, state: FSMContext, user: User) -> None:
    await state.update_data(fee=int(callback_data.value))
    await call.message.edit_text(texts.SAVED_FEE.format(v=texts.money(int(callback_data.value))))
    await call.answer()
    await _next(call.message, state, "fee", user)


@router.message(NewJob.fee, F.text)
async def s_fee_text(message: Message, state: FSMContext, user: User) -> None:
    v = parse_int(message.text)
    if v is None:
        await message.answer(texts.BAD_NUMBER)
        return
    await state.update_data(fee=v)
    await _next(message, state, "fee", user)


# ================================================================ tahrirlash

@router.callback_query(NewJob.preview, EditCB.filter())
async def edit_field(call: CallbackQuery, callback_data: EditCB, state: FSMContext) -> None:
    """Oldindan ko'rishdan bitta maydonni tuzatish.

    `editing` bayrog'i qo'yiladi — javob kelgach keyingi qadamga emas,
    to'g'ridan-to'g'ri oldindan ko'rishga qaytamiz.
    """
    await state.update_data(editing=True)
    await _ask(call.message, state, callback_data.field)
    await call.answer()


# ================================================================ ko'rish

def build_job(data: dict, user_id: int, status: JobStatus) -> Job:
    return Job(
        category=data.get("category", "boshqa"),
        title=data["title"],
        description=data["description"],
        secret_details=data["secret"],
        lat=data.get("lat"),
        lon=data.get("lon"),
        region=data["region"],
        work_date=date.fromisoformat(data["work_date"]),
        start_time=data["start_time"],
        salary=data["salary"],
        fee=data.get("fee", store.default_fee()),
        slots_total=data["slots"],
        status=status,
        created_by=user_id,
    )


async def send_preview(message: Message, state: FSMContext, user: User) -> None:
    """Bazaga yozishdan oldin xuddi kanalda ko'rinadigan holida ko'rsatamiz.

    Ochiq va maxfiy qismlar ALOHIDA ko'rsatiladi — eng ko'p uchraydigan xato
    manzilni ochiq tavsifga yozib yuborish, va uni faqat shu yerda ushlash
    mumkin.
    """
    data = await state.get_data()
    preview = build_job(data, user.id, JobStatus.OPEN)
    preview.id = 0
    staff = is_staff(user)

    await state.set_state(NewJob.preview)
    # Sarlavhalar «to'lov» atamasisiz: e'lon bepul ham bo'lishi mumkin, va
    # ish beruvchiga to'lov masalasi umuman aloqador emas — u faqat ishchi
    # oladi. Bo'linish MAZMUN bo'yicha: e'londa ko'rinadigan va faqat
    # yozilganlarga ochiladigan qism.
    await message.answer(
        texts.PREVIEW_PUBLIC + "\n\n" + texts.job_card(preview, 0, show_fee=staff)
    )
    secret_block = (
        texts.PREVIEW_SECRET + "\n\n" + data["secret"]
    )
    if data.get("lat") is not None:
        secret_block += "\n\n" + texts.LOC_ATTACHED
    else:
        secret_block += "\n\n" + texts.LOC_NONE

    await message.answer(
        secret_block + "\n\n" + texts.PREVIEW_CONFIRM,
        reply_markup=preview_kb(is_admin=staff),
    )


# ================================================================ yakunlash

@router.callback_query(NewJob.preview, PickCB.filter(F.field == "confirm"))
async def confirm(
    call: CallbackQuery,
    callback_data: PickCB,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    if callback_data.value == "no":
        await state.clear()
        await call.message.edit_text(texts.NEW_JOB_CANCELLED)
        await call.answer()
        return

    data = await state.get_data()
    await state.clear()

    staff = is_staff(user)
    job = build_job(data, user.id, JobStatus.OPEN if staff else JobStatus.PENDING_REVIEW)
    session.add(job)
    await session.commit()

    await tg.edit_markup(call.message, None)
    await tg.answer_cb(call)

    if staff:
        # Kanal ulanmagan bo'lsa tanlov o'rniga darhol e'lon qilamiz —
        # obunachilarga tarqatish baribir ishlaydi.
        if not await offer_publish_choice(call.message, session, job, broadcast=True):
            await publish_and_notify(bot, session, job, report_to=call.from_user.id)
    else:
        await call.message.answer(texts.NEW_JOB_SENT_TO_REVIEW)
        # Tasdiqlashni istalgan xodim qila oladi — admin band bo'lsa
        # e'lon kutib qolmaydi.
        await publisher.notify_staff(
            bot, session,
            texts.job_review_caption(job, user),
            reply_markup=job_review_kb(job.id),
        )


async def offer_publish_choice(
    message: Message, session: AsyncSession, job: Job, *, broadcast: bool
) -> bool:
    """Kanal tanlovini ko'rsatadi: mos / barcha / qo'lda / joylamaslik.

    Kanal umuman ulanmagan bo'lsa tanlashning ma'nosi yo'q — False
    qaytaradi, chaqiruvchi to'g'ridan-to'g'ri joylashga o'tadi.
    """
    active = await ch.all_channels(session, only_active=True)
    if not active:
        return False
    matching = await ch.targets_for(session, job)
    await message.answer(
        f"📡 <b>E'lon <code>#{job.id}</code> qayerga joylansin?</b>\n\n"
        f"Teglarga mos: <b>{len(matching)}</b> ta · Jami faol kanal: <b>{len(active)}</b> ta\n\n"
        f"<i>«Mos kanallarga» — hudud/kasb filtri shu e'longa to'g'ri "
        f"keladigan kanallarga. Filtri bo'sh kanal hammasini qabul qiladi.</i>",
        reply_markup=publish_choice_kb(
            job.id, len(matching), len(active), broadcast=broadcast
        ),
    )
    return True


async def publish_and_notify(
    bot: Bot,
    session: AsyncSession,
    job: Job,
    *,
    report_to: int,
    targets=None,  # noqa: ANN001 — Channel ro'yxati yoki None (teglar bo'yicha)
    with_broadcast: bool = True,
) -> None:
    """Kanallarga joylaydi va (kerak bo'lsa) obunachilarga tarqatadi.

    Tarqatish uzoq davom etadi (minglab odam), shuning uchun uni FON rejimida
    qo'yib yuboramiz — admin panel qotib turmaydi. Qayta joylashda
    with_broadcast=False — obunachilarga ikkinchi marta xabar ketmaydi.
    """
    import asyncio

    from bot.services.notifier import broadcast_job

    lines = [f"{texts.NEW_JOB_PUBLISHED} <code>#{job.id}</code>"]
    posted, errors = await publisher.publish_job(bot, session, job, targets=targets)
    if posted:
        lines.append(f"📢 {posted} ta kanalga joylandi.")
    elif not errors:
        lines.append("ℹ️ Mos kanal yo'q — e'lon faqat botda ko'rinadi.")
    if errors:
        lines.append("⚠️ Joylanmadi:\n" + "\n".join(errors))

    try:
        await bot.send_message(report_to, "\n".join(lines)[:3500])
    except Exception:
        pass

    if with_broadcast:
        asyncio.create_task(broadcast_job(bot, job.id, report_to))


# ================================================================ takrorlash

@router.callback_query(AdminJobCB.filter(F.action == "clone"))
async def clone_job(
    call: CallbackQuery, callback_data: AdminJobCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    """Eski e'londan nusxa. Kunlik ishlar takrorlanadi — bu eng katta
    tejamkorlik: 10 qadam o'rniga 2 bosish."""
    job = await svc.get_job(session, callback_data.job_id)
    if job is None:
        await call.answer(texts.NOT_FOUND, show_alert=True)
        return
    if not _can_post(user) or (user.role != Role.ADMIN and job.created_by != user.id):
        await call.answer(texts.NO_ACCESS, show_alert=True)
        return

    await state.clear()
    await state.update_data(
        category=job.category,
        title=job.title,
        description=job.description,
        secret=job.secret_details,
        region=job.region,
        start_time=job.start_time,
        salary=job.salary,
        slots=job.slots_total,
        fee=job.fee,
    )
    await call.answer("♻️ Nusxa olindi")
    await call.message.answer(
        f"♻️ <b>«{job.title}»</b> e'loni nusxalandi.\n\n"
        f"Faqat <b>sanani</b> tanlang — qolgani o'zgarmaydi. "
        f"Xohlasangiz keyin istalgan maydonni tuzatasiz.",
        reply_markup=dates_kb("njdate"),
    )
    await state.set_state(NewJob.work_date)
    await state.update_data(editing=True)  # sana tanlangach darrov ko'rishga
