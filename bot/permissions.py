"""Kim nima qila oladi.

Ikki daraja:
  ADMIN     — hamma narsa: sozlamalar, moliya, moderatorlarni tayinlash
  MODERATOR — chek tekshirish, e'lon joylash, yozilganlarni ko'rish

Nega .env dagi ADMIN_IDS yetarli emas? Chunki har yangi moderator uchun
faylni tahrirlab, botni qayta ishga tushirish kerak bo'lardi. Endi rol
bazada saqlanadi va admin bot ichidan tayinlaydi.

.env dagi ADMIN_IDS — «egalari». Ularning rolini hech kim tortib
ololmaydi, shu jumladan boshqa admin ham.
"""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.config import settings as env
from bot.db.models import STAFF_ROLES, Role, User


def is_owner(user_id: int) -> bool:
    """.env da ko'rsatilgan asosiy egasi — roli hech qachon o'zgarmaydi."""
    return user_id in env.admins


def is_admin(user: User | None) -> bool:
    return user is not None and (user.role == Role.ADMIN or is_owner(user.id))


def is_staff(user: User | None) -> bool:
    return user is not None and (user.role in STAFF_ROLES or is_owner(user.id))


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, user: User | None = None) -> bool:
        return is_admin(user)


class IsStaff(BaseFilter):
    async def __call__(self, event: TelegramObject, user: User | None = None) -> bool:
        return is_staff(user)
