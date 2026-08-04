"""/start, ro'yxatdan o'tish, profil, navigatsiya."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import NavCB, PickCB
from bot.config import CATEGORY_NAMES, settings as env
from bot.db.models import Role, User
from bot.keyboards import (
    BTN_BACK,
    BTN_PROFILE,
    categories_multi_kb,
    main_menu,
    phone_kb,
    regions_kb,
    role_kb,
)
from bot import runtime
from bot.permissions import is_staff
from bot.services import jobs as svc
from bot.services import settings_store as store
from bot.states import Reg

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
    payload = (command.args or "").strip()
    pending_job: int | None = None
    if payload.startswith("job_") and payload[4:].isdigit():
        pending_job = int(payload[4:])

    # Referal havolasi: https://t.me/bot?start=ref_123456789
    # Faqat YANGI foydalanuvchi uchun ishlaydi va o'zini o'zi chaqira olmaydi.
    if payload.startswith("ref_") and payload[4:].isdigit():
        if await svc.register_referral(session, user, int(payload[4:])):
            await message.answer(
                "🎁 Do'stingizning havolasi orqali kirdingiz.\n"
                "<i>Birinchi ishga yozilganingizda unga bonus beriladi.</i>"
            )

    if not user.is_registered:
        if pending_job:
            await state.update_data(pending_job=pending_job)
        await state.set_state(Reg.role)
        await message.answer(texts.CHOOSE_ROLE, reply_markup=role_kb())
        return

    await message.answer(texts.MAIN_MENU, reply_markup=main_menu(user))

    if pending_job:
        from bot.handlers.worker import show_job

        await show_job(message, session, user, pending_job)
    elif payload == "feed":
        from bot.handlers.worker import show_feed

        await show_feed(message, state, session, user)


# ================================================================ ro'yxatdan o'tish

@router.callback_query(Reg.role, PickCB.filter(F.field == "role"))
async def pick_role(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, user: User
) -> None:
    # Xodim roli hech qachon pastga tushmasin.
    if not is_staff(user):
        user.role = Role.EMPLOYER if callback_data.value == "employer" else Role.WORKER
        await session.commit()

    intro = texts.START_EMPLOYER if callback_data.value == "employer" else texts.START_WORKER
    await state.set_state(Reg.phone)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(intro, reply_markup=phone_kb())
    await call.answer()


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

    if user.role == Role.EMPLOYER:
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
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer()
        await _finish_registration(call.message, state, session, user)
        return

    await svc.toggle_category(session, user, callback_data.value)
    await call.message.edit_reply_markup(reply_markup=categories_multi_kb(user.category_keys))
    await call.answer()


async def _finish_registration(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    await state.clear()

    text = texts.REGISTERED_EMPLOYER if user.role == Role.EMPLOYER else texts.REGISTERED_WORKER
    await message.answer(text, reply_markup=main_menu(user))

    if job_id := data.get("pending_job"):
        from bot.handlers.worker import show_job

        await show_job(message, session, user, job_id)


# ================================================================ profil

@router.message(F.text == BTN_PROFILE)
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
        f"\nID: <code>{user.id}</code>\n\n"
        f"/dost — do'st chaqirib bonus olish\n"
        f"/hudud — hududni o'zgartirish\n"
        f"/kasb — qiziqishlarni o'zgartirish\n"
        f"/xabar — xabarnomani yoqish/o'chirish\n"
        f"/shikoyat — muammo yoki savol\n"
        f"/rol — rolni almashtirish"
    )
    await message.answer(text)


@router.message(Command("dost"))
async def referral(message: Message, user: User) -> None:
    reward = store.referral_reward()
    if reward <= 0:
        await message.answer("Hozircha referal dasturi o'chirilgan.")
        return
    link = f"https://t.me/{runtime.bot_username}?start=ref_{user.id}"
    await message.answer(
        texts.referral_info(link, user.invited_count, user.free_credits, reward)
    )


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


@router.message(Command("xabar"))
async def toggle_notify(message: Message, session: AsyncSession, user: User) -> None:
    user.notify = not user.notify
    await session.commit()
    await message.answer(
        "🔔 Xabarnoma <b>yoqildi</b>." if user.notify
        else "🔕 Xabarnoma <b>o'chirildi</b>. Yangi e'lonlar haqida xabar kelmaydi."
    )


@router.message(Command("rol"))
async def change_role(message: Message, state: FSMContext, user: User) -> None:
    if is_staff(user):
        await message.answer("Siz xodimsiz — rol o'zgarmaydi.")
        return
    await state.set_state(Reg.role)
    await message.answer(texts.CHOOSE_ROLE, reply_markup=role_kb())


# ================================================================ navigatsiya

@router.message(F.text == BTN_BACK)
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


@router.message(Command("help"))
async def cmd_help(message: Message, user: User) -> None:
    text = (
        "ℹ️ <b>Yordam</b>\n\n"
        "/start — boshlash\n"
        "/ishlar — ochiq e'lonlar\n"
        "/mening — mening ishlarim\n"
        "/profil — profil\n"
        "/dost — do'st chaqirib bonus olish\n"
        "/kasb — qiziqishlar\n"
        "/xabar — xabarnomani yoqish/o'chirish\n"
        "/shikoyat — muammo yoki savol\n"
    )
    if user.id in env.admins:
        text += (
            "\n🛠 <b>Admin</b>\n"
            "/newjob — yangi e'lon\n"
            "/pending — kutayotgan to'lovlar\n"
            "/review — tasdiq kutayotgan e'lonlar\n"
            "/stats — statistika\n"
            "/sozlama — sozlamalar\n"
            "/cancel — jarayonni bekor qilish\n"
            "/id — shu chat ID si"
        )
    await message.answer(text)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Sizning ID: <code>{message.from_user.id}</code>"
    )
