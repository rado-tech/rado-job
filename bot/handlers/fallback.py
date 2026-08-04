"""Hech qaysi handler ushlamagan xabarlar.

Ilgari odam tushunarsiz narsa yozsa — bot JIM qolardi. Foydalanuvchi
"bot buzilibdi" deb o'ylab ketardi. Bu router eng OXIRIDA turadi va
faqat boshqa hech kim javob bermagan holatda ishlaydi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db.models import Role, User
from bot.keyboards import admin_menu, main_menu
from bot.permissions import is_staff

router = Router(name="fallback")


@router.message(F.text)
async def unknown_text(message: Message, state: FSMContext, user: User) -> None:
    if not user.is_registered:
        await message.answer(
            "👋 Boshlash uchun /start bosing va ro'yxatdan o'ting."
        )
        return

    hint = (
        "🤔 Tushunmadim.\n\n"
        "Pastdagi tugmalardan foydalaning yoki:\n"
    )
    if user.role == Role.EMPLOYER:
        hint += "➕ E'lon berish · 📢 E'lonlarim · 👤 Profil\n"
    else:
        hint += "🔎 Ish qidirish · 📋 Mening ishlarim · 👤 Profil\n"
    hint += "\n/help — barcha buyruqlar\n/shikoyat — muammo yoki savol"

    kb = admin_menu(user) if is_staff(user) else main_menu(user)
    await message.answer(hint, reply_markup=kb)


@router.message()
async def unknown_other(message: Message, user: User) -> None:
    """Rasm, video, stiker, ovozli xabar va hokazo."""
    await message.answer(
        "🤔 Buni qanday ishlatishni bilmadim.\n\n"
        "Chek yuborayotgan bo'lsangiz — avval e'longa yozilib, "
        "«Yozilish» tugmasini bosing.\n\n"
        "/help — yordam",
        reply_markup=admin_menu(user) if is_staff(user) else main_menu(user),
    )
