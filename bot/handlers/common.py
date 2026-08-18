"""/start, ro'yxatdan o'tish, profil, navigatsiya."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import NavCB, PickCB, ProfCB, RateCB, WorkerCB
from bot.config import CATEGORY_NAMES, settings as env
from bot.db.models import Booking, BookingStatus, Job, Role, User
from bot.i18n import LANGS, set_lang, use_lang
from bot.keyboards import (
    categories_multi_kb,
    lang_kb,
    main_menu,
    phone_kb,
    profile_kb,
    rate_kb,
    regions_kb,
    role_kb,
    variants,
)
from bot import runtime
from bot.permissions import is_admin, is_staff
from bot.services import audit, jobs as svc
from bot.services import ratings
from bot.services import settings_store as store
from bot.states import Reg, ReportFlow
from bot import tg

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    await state.clear()

    # Kanaldagi tugma https://t.me/bot?start=job_12 ni ochadi. Shu raqamni
    # eslab qolamiz — ro'yxatdan o'tgach aynan o'sha e'lonni ko'rsatamiz.
    # Kanaldagi tugma: job_12 yoki job_12_c3 (c3 — qaysi kanaldan kelgani).
    payload = (command.args or "").strip()
    pending_job: int | None = None
    src_channel: int | None = None
    if payload.startswith("job_"):
        parts = payload[4:].split("_c")
        if parts[0].isdigit():
            pending_job = int(parts[0])
        if len(parts) > 1 and parts[1].isdigit():
            src_channel = int(parts[1])

    # Referal havolasi: https://t.me/bot?start=ref_123456789
    # Faqat YANGI foydalanuvchi uchun ishlaydi va o'zini o'zi chaqira olmaydi.
    if payload.startswith("ref_") and payload[4:].isdigit():
        if await svc.register_referral(session, user, int(payload[4:])):
            await message.answer(
                "🎁 Do'stingizning havolasi orqali kirdingiz.\n"
                "<i>Birinchi ishga yozilganingizda unga bonus beriladi.</i>"
            )

    # Kanal belgisini eslab qolamiz — yozilganda arizaga yoziladi.
    if src_channel:
        await state.update_data(src_channel=src_channel)

    if not user.is_registered:
        if pending_job:
            await state.update_data(pending_job=pending_job)
        # Til birinchi so'raladi — undan keyingi hamma savol o'sha tilda.
        await state.set_state(Reg.lang)
        await message.answer(
            "Tilni tanlang / Выберите язык", reply_markup=lang_kb()
        )
        return

    await message.answer(texts.MAIN_MENU, reply_markup=main_menu(user))

    if pending_job:
        from bot.handlers.worker import show_job

        await show_job(message, session, user, pending_job)
    elif payload == "feed":
        from bot.handlers.worker import show_feed

        await show_feed(message, state, session, user)


# ================================================================ ro'yxatdan o'tish

@router.callback_query(PickCB.filter(F.field == "lang"))
async def pick_lang(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    user.lang = callback_data.value if callback_data.value in LANGS else "uz"
    await session.commit()
    # Shu xabardan boshlab hamma matn yangi tilda bo'lsin.
    set_lang(user.lang)

    await call.message.edit_text(f"✅ {LANGS[user.lang]}")
    await call.answer()

    if user.is_registered:
        await call.message.answer(texts.MAIN_MENU, reply_markup=main_menu(user))
        return

    await state.set_state(Reg.role)
    await call.message.answer(texts.CHOOSE_ROLE, reply_markup=role_kb())


@router.message(Command("til"))
@router.message(Command("язык"))
async def change_lang(message: Message) -> None:
    await message.answer("Tilni tanlang / Выберите язык", reply_markup=lang_kb())


@router.callback_query(Reg.role, PickCB.filter(F.field == "role"))
async def pick_role(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    # Xodim roli hech qachon pastga tushmasin.
    if not is_staff(user):
        user.role = Role.EMPLOYER if callback_data.value == "employer" else Role.WORKER
        await session.commit()

    await tg.edit_markup(call.message, None)
    await tg.answer_cb(call)

    # Allaqachon ro'yxatdan o'tgan bo'lsa — telefonni QAYTA so'ramaymiz.
    # Ilgari /rol bosgan odamdan raqam yana so'ralardi: keraksiz va chalkash.
    if user.is_registered:
        await state.set_state(None)
        await call.message.answer(
            texts.ROLE_CHANGED_EMPLOYER
            if user.role == Role.EMPLOYER
            else texts.ROLE_CHANGED_WORKER,
            reply_markup=main_menu(user),
        )
        return

    intro = texts.START_EMPLOYER if callback_data.value == "employer" else texts.START_WORKER
    # Bu HAQIQIY ro'yxatdan o'tish. Profil orqali hudud/kasb o'zgartirilganda
    # ham xuddi shu holatlar ishlatiladi — belgisiz ikkalasi aralashib
    # ketardi va sozlamani o'zgartirgan odam «Tayyor! Birinchi e'loningizni
    # joylang» degan mos kelmaydigan xabarni ko'rardi.
    await state.update_data(reg_flow=True)
    await state.set_state(Reg.phone)
    await call.message.answer(intro, reply_markup=phone_kb())


@router.message(Reg.phone, F.contact)
async def got_contact(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    # Boshqa odamning kontaktini yuborib qo'yishi mumkin.
    if message.contact.user_id != message.from_user.id:
        await message.answer(
            "❗️ Bu sizning raqamingiz emas. O'z raqamingizni yuboring.",
            reply_markup=phone_kb(),
        )
        return

    user.phone = message.contact.phone_number
    if not user.full_name:
        user.full_name = (message.from_user.full_name or "")[:128]
    await session.commit()

    await state.set_state(Reg.region)
    await message.answer("✅ Raqam saqlandi.", reply_markup=ReplyKeyboardRemove())
    await message.answer(texts.ASK_REGION, reply_markup=regions_kb("rregion"))


@router.message(Reg.phone)
async def phone_wrong(message: Message) -> None:
    await message.answer(texts.ASK_PHONE_BUTTON_ONLY, reply_markup=phone_kb())


@router.callback_query(Reg.region, PickCB.filter(F.field == "rregion"))
async def got_region(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    user.region = callback_data.value
    await session.commit()
    await call.message.edit_text(f"📍 Hudud: <b>{callback_data.value}</b>")
    await call.answer()

    data = await state.get_data()
    # Profil orqali FAQAT hududni o'zgartirmoqchi bo'lgan odamdan qiziqishlar
    # ham so'ralishi kerak emas — u so'ramagan savolga javob berib o'tiradi.
    # Qiziqishlar ketma-ketligi faqat ro'yxatdan o'tishda mantiqiy.
    if user.role == Role.EMPLOYER or not data.get("reg_flow"):
        await _finish_registration(call.message, state, session, user)
        return

    await state.set_state(Reg.categories)
    await call.message.answer(
        texts.ASK_CATEGORIES, reply_markup=categories_multi_kb(user.category_keys)
    )


@router.callback_query(Reg.categories, PickCB.filter(F.field == "cat"))
async def pick_categories(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    if callback_data.value == "__done__":
        await tg.edit_markup(call.message, None)
        await tg.answer_cb(call)
        await _finish_registration(call.message, state, session, user)
        return

    await svc.toggle_category(session, user, callback_data.value)
    await tg.edit_markup(call.message, categories_multi_kb(user.category_keys))
    await tg.answer_cb(call)


async def _finish_registration(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    was_registration = bool(data.get("reg_flow"))
    await state.clear()

    if was_registration:
        text = (
            texts.REGISTERED_EMPLOYER if user.role == Role.EMPLOYER
            else texts.REGISTERED_WORKER
        )
    else:
        # Profil orqali sozlama o'zgartirildi — tabriklash o'rinsiz.
        text = texts.SETTINGS_SAVED
    await message.answer(text, reply_markup=main_menu(user))

    if job_id := data.get("pending_job"):
        from bot.handlers.worker import show_job

        await show_job(message, session, user, job_id)


# ================================================================ profil

@router.message(F.text.in_(variants("profile")))
@router.message(Command("profil"))
async def profile(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    role_name = {
        Role.WORKER: "🔎 Ish qidiruvchi",
        Role.EMPLOYER: "🏢 Ish beruvchi",
        Role.MODERATOR: "🛡 Moderator",
        Role.ADMIN: "🛠 Administrator",
    }[user.role]
    cats = ", ".join(CATEGORY_NAMES.get(k, k) for k in user.category_keys) or "barchasi"

    text = (
        f"👤 <b>Profil</b>\n\n"
        f"Kim: <b>{role_name}</b>\n"
        f"Ism: <b>{user.full_name}</b>\n"
        f"Telefon: <code>{user.phone or '—'}</code>\n"
        f"Hudud: <b>{user.region or '—'}</b>\n"
    )
    if user.role == Role.WORKER:
        text += (
            f"Qiziqishlar: {cats}\n"
            f"Xabarnoma: {'🔔 yoqilgan' if user.notify else '🔕 o‘chirilgan'}\n"
            f"Ishonchlilik: <b>{user.reliability}</b>\n"
            f"🎫 Bepul yozilish bonusi: <b>{user.free_credits}</b>\n"
        )
    text += (
        f"🌐 Til: <b>{LANGS.get(user.lang, LANGS['uz'])}</b>\n"
        f"\nID: <code>{user.id}</code>\n\n"
        f"{texts.PROFILE_HINT}"
    )
    await message.answer(text, reply_markup=profile_kb(user))


async def show_referral(message: Message, user: User) -> None:
    reward = store.referral_reward()
    if reward <= 0:
        await message.answer("Hozircha referal dasturi o'chirilgan.")
        return
    link = f"https://t.me/{runtime.bot_username}?start=ref_{user.id}"
    await message.answer(
        texts.referral_info(link, user.invited_count, user.free_credits, reward)
    )


@router.message(Command("dost"))
async def referral(message: Message, user: User) -> None:
    await show_referral(message, user)


@router.message(Command("hudud"))
async def change_region(message: Message, state: FSMContext) -> None:
    await state.set_state(Reg.region)
    await message.answer(texts.ASK_REGION, reply_markup=regions_kb("rregion"))


@router.message(Command("kasb"))
async def change_categories(message: Message, state: FSMContext, user: User) -> None:
    await state.set_state(Reg.categories)
    await message.answer(
        texts.ASK_CATEGORIES, reply_markup=categories_multi_kb(user.category_keys)
    )


async def do_toggle_notify(message: Message, session: AsyncSession, user: User) -> None:
    user.notify = not user.notify
    await session.commit()
    # Aniq yozamiz: bu FAQAT yangi e'lon tarqatmasini o'chiradi. Shaxsiy
    # xabarlar (tasdiq, eslatma, navbat) baribir keladi — aks holda odam
    # "hech narsa kelmaydi" deb o'ylab, ishga chiqmay qoladi.
    if user.notify:
        await message.answer(
            "🔔 <b>Yangi e'lonlar haqida xabar yoqildi.</b>\n\n"
            "Hududingiz va tanlagan kasblaringizga mos e'lon chiqqanda "
            "shu yerga xabar keladi."
        )
    else:
        await message.answer(
            "🔕 <b>Yangi e'lonlar haqida xabar o'chirildi.</b>\n\n"
            "E'lonlarni «🔎 Ish qidirish» orqali o'zingiz ko'rasiz.\n\n"
            "<i>Diqqat: yozilgan ishlaringiz bo'yicha xabarlar — to'lov "
            "tasdig'i, ish eslatmasi, navbatdan joy bo'shashi — baribir "
            "keladi. Ular o'chmaydi.</i>"
        )


@router.message(Command("xabar"))
async def toggle_notify(message: Message, session: AsyncSession, user: User) -> None:
    await do_toggle_notify(message, session, user)


@router.message(Command("rol"))
async def change_role(message: Message, state: FSMContext, user: User) -> None:
    if is_staff(user):
        await message.answer("Siz xodimsiz — rol o'zgarmaydi.")
        return
    await state.set_state(Reg.role)
    await message.answer(texts.CHOOSE_ROLE, reply_markup=role_kb())


# ================================================================ profil tugmalari

@router.callback_query(ProfCB.filter())
async def profile_action(
    call: CallbackQuery, callback_data: ProfCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    """Profil ostidagi tugmalar.

    Har biri o'sha buyruq bajaradigan ishni qiladi — mantiq takrorlanmasin
    deb umumiy funksiyalar chaqiriladi. Amal bajarilgach profil QAYTA
    ko'rsatilmaydi: odam nima o'zgarganini xabar matnidan ko'radi va
    kerak bo'lsa «👤 Profil» ni yana bosadi.
    """
    action = callback_data.action
    msg = call.message

    if action == "lang":
        await tg.answer_cb(call)
        await msg.answer("Tilni tanlang / Выберите язык", reply_markup=lang_kb())
        return

    if action == "region":
        await state.set_state(Reg.region)
        await tg.answer_cb(call)
        await msg.answer(texts.ASK_REGION, reply_markup=regions_kb("rregion"))
        return

    if action == "cats":
        await state.set_state(Reg.categories)
        await tg.answer_cb(call)
        await msg.answer(
            texts.ASK_CATEGORIES, reply_markup=categories_multi_kb(user.category_keys)
        )
        return

    if action == "notify":
        await do_toggle_notify(msg, session, user)
        await tg.answer_cb(call, "🔔" if user.notify else "🔕")
        # Tugma yozuvi holatga qarab o'zgaradi — darhol yangilaymiz.
        await tg.edit_markup(msg, profile_kb(user))
        return

    if action == "invite":
        await tg.answer_cb(call)
        await show_referral(msg, user)
        return

    if action == "complain":
        await state.set_state(ReportFlow.text)
        await state.update_data(report_job_id=None)
        await tg.answer_cb(call)
        await msg.answer(texts.ASK_REPORT)
        return

    if action == "role":
        if is_staff(user):
            await tg.answer_cb(call, "Siz xodimsiz — rol o'zgarmaydi.", alert=True)
            return
        await state.set_state(Reg.role)
        await tg.answer_cb(call)
        await msg.answer(texts.CHOOSE_ROLE, reply_markup=role_kb())
        return

    if action == "help":
        await tg.answer_cb(call)
        await msg.answer(help_text(user))
        return

    await tg.answer_cb(call)


# ================================================================ navigatsiya

@router.message(F.text.in_(variants("back")))
async def back_to_menu(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await message.answer(texts.MAIN_MENU, reply_markup=main_menu(user))


@router.callback_query(NavCB.filter(F.to == "menu"))
async def nav_menu(call: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    await call.message.answer(texts.MAIN_MENU, reply_markup=main_menu(user))
    await call.answer()


@router.callback_query(NavCB.filter(F.to == "noop"))
async def nav_noop(call: CallbackQuery) -> None:
    await call.answer()


def help_text(user: User) -> str:
    """Yordam matni.

    Buyruqlar ro'yxati emas, QISQA yo'l-yo'riq: kundalik ishlarning
    hammasi tugmalar orqali qilinadi. Buyruqlar faqat zaxira usul —
    klaviatura yo'qolib qolsa yoki tez o'tish kerak bo'lsa.
    """
    text = (
        "ℹ️ <b>Yordam</b>\n\n"
        "Hamma narsa <b>tugmalar</b> orqali:\n\n"
        "🔎 <b>Ish qidirish</b> — ochiq e'lonlar\n"
        "📋 <b>Mening ishlarim</b> — yozilgan ishlaringiz\n"
        "👤 <b>Profil</b> — til, hudud, qiziqishlar, xabarnoma, "
        "do'st chaqirish, shikoyat\n\n"
        "<i>Tugmalar ko'rinmasa /start bosing.</i>\n\n"
        "Tez buyruqlar: /start /ishlar /mening /profil /til /shikoyat"
    )
    if is_staff(user):
        text += (
            "\n\n🛠 <b>Xodim</b>\n"
            "/admin — panel · /newjob — yangi e'lon\n"
            "/pending — kutayotgan cheklar · /review — tasdiq kutayotgan e'lonlar\n"
            "/murojaat — shikoyatlar · /jobs — barcha e'lonlar\n"
            "/cancel — jarayonni bekor qilish · /id — chat ID si"
        )
    if user.id in env.admins:
        text += (
            "\n\n👑 <b>Admin</b>\n"
            "/sozlama — sozlamalar · /users — foydalanuvchilar\n"
            "/stats — statistika · /hisobot — kunlik hisobot\n"
            "/reklama — tarqatish · /jurnal — xodimlar jurnali\n"
            "/health — bot holati · /backup — zaxira nusxa · /mod — moderator"
        )
    return text


@router.message(Command("help"))
async def cmd_help(message: Message, user: User) -> None:
    await message.answer(help_text(user))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Sizning ID: <code>{message.from_user.id}</code>"
    )


# ================================================================ davomat belgilash

@router.callback_query(WorkerCB.filter())
async def worker_action(
    call: CallbackQuery, callback_data: WorkerCB, session: AsyncSession, user: User
) -> None:
    """Ishchini belgilash: chiqdi / chiqmadi / bloklash.

    Bu handler ataylab UMUMIY routerda: tugmalar ish tugagach ISH
    BERUVCHIGA ham yuboriladi. Ilgari u faqat xodimlar routerida edi va
    ish beruvchi bosganda hech narsa bo'lmasdi. Ruxsat ichkarida
    tekshiriladi: xodim yoki o'sha ishning muallifi.
    """
    bot = call.bot
    booking = await session.get(Booking, callback_data.booking_id)
    if booking is None:
        await call.answer(texts.NOT_FOUND, show_alert=True)
        return
    job = await session.get(Job, booking.job_id)
    if not (is_staff(user) or (job is not None and job.created_by == user.id)):
        await call.answer(texts.NO_ACCESS, show_alert=True)
        return
    target = await session.get(User, booking.user_id)

    if callback_data.action == "done":
        await svc.mark_completed(session, booking)
        await call.answer("✅")
        suffix = texts.BTN_MARK_DONE
        if is_staff(user):
            await audit.log_action(
                session, user.id, "worker_done", f"ariza #{booking.id}",
                target.full_name if target else "",
            )
    elif callback_data.action == "noshow":
        await svc.mark_no_show(session, booking)
        await call.answer("🚷")
        suffix = texts.BTN_MARK_NOSHOW
        if is_staff(user):
            await audit.log_action(
                session, user.id, "worker_noshow", f"ariza #{booking.id}",
                target.full_name if target else "",
            )
        try:
            with use_lang(target.lang if target else None):
                note = texts.NOSHOW_MARKED
            await bot.send_message(booking.user_id, note)
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
            await audit.log_action(session, user.id, "user_block", target.mention)
        await call.answer("🚫 Bloklandi")
        suffix = "🚫 Bloklandi"

    try:
        await call.message.edit_text(
            (call.message.text or "") + f"\n\n<b>{suffix}</b>", reply_markup=None
        )
    except Exception:
        pass

    # Ish beruvchi o'z ishchisini «chiqdi» deb belgiladi — baho so'raymiz.
    # Xodim belgilaganda so'ramaymiz: baho ish beruvchiniki bo'lishi kerak.
    if (
        callback_data.action == "done"
        and job is not None
        and user.id == job.created_by
        and target is not None
        and target.id != user.id
    ):
        await call.message.answer(
            texts.RATE_WORKER_ASK, reply_markup=rate_kb("w", booking.id)
        )


# ================================================================ baho

@router.callback_query(RateCB.filter())
async def rate_answer(
    call: CallbackQuery, callback_data: RateCB, session: AsyncSession, user: User
) -> None:
    """1-5 baho tugmasi. Natijani faqat administratsiya ko'radi."""
    if callback_data.kind == "e":
        # Ishchi ish beruvchini baholaydi — faqat shu ishda qatnashgan bo'lsa.
        job = await session.get(Job, callback_data.ref)
        if job is None:
            await call.answer(texts.NOT_FOUND, show_alert=True)
            return
        from sqlalchemy import select

        booking = await session.scalar(
            select(Booking).where(
                Booking.job_id == job.id,
                Booking.user_id == user.id,
                Booking.status.in_(
                    [BookingStatus.CONFIRMED, BookingStatus.COMPLETED]
                ),
            )
        )
        if booking is None:
            await call.answer(texts.NO_ACCESS, show_alert=True)
            return
        target_id, job_id = job.created_by, job.id
    else:
        # Ish beruvchi ishchini baholaydi — faqat o'z e'loni bo'yicha.
        booking = await session.get(Booking, callback_data.ref)
        if booking is None:
            await call.answer(texts.NOT_FOUND, show_alert=True)
            return
        job = await session.get(Job, booking.job_id)
        if job is None or (user.id != job.created_by and not is_staff(user)):
            await call.answer(texts.NO_ACCESS, show_alert=True)
            return
        target_id, job_id = booking.user_id, booking.job_id

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if callback_data.stars <= 0:
        await call.answer(texts.RATE_SKIPPED)
        return
    if target_id == user.id:
        await call.answer()
        return

    await ratings.add(
        session, job_id=job_id, rater_id=user.id, target_id=target_id,
        stars=callback_data.stars,
    )
    await call.answer(texts.RATE_THANKS)
    try:
        await call.message.edit_text(
            (call.message.text or "") + f"\n\n{'⭐' * callback_data.stars}"
        )
    except Exception:
        pass
