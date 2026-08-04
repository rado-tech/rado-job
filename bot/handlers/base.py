"""Hamma routerlardan OLDIN turadigan umumiy handler'lar.

Hozircha bitta: /cancel. U eng birinchi bo'lishi shart — aks holda
"foydalanuvchi qidirish" yoki "sabab yozish" kabi holatlardagi handler'lar
uni oddiy matn deb qabul qilib yuboradi.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db.models import User
from bot.keyboards import admin_menu, main_menu
from bot.permissions import is_staff

router = Router(name="base")


@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext, user: User) -> None:
    if await state.get_state() is None:
        await message.answer("Bekor qiladigan amal yo'q.")
        return
    await state.set_state(None)
    kb = admin_menu(user) if is_staff(user) else main_menu(user)
    await message.answer("🚫 Bekor qilindi.", reply_markup=kb)
