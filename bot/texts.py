"""Matnlar — TIL BO'YICHA avtomat tanlanadi.

Bu modul o'zida matn saqlamaydi. Undan biror nom so'ralganda, joriy
foydalanuvchining tiliga mos lug'atdan qaytaradi:

    bot/locales/uz.py — o'zbekcha (asosiy, to'liq)
    bot/locales/ru.py — ruscha (ishchi ko'radigan qism)

Shu tufayli handler'lardagi `texts.job_card(...)` chaqiruvlarining
birortasini o'zgartirish kerak bo'lmadi.

MUHIM: bu moduldan nomni to'g'ridan-to'g'ri import qilmang:

    from bot.texts import money        # ❌ import paytida o'zbekchaga qotib qoladi
    from bot import texts; texts.money  # ✅ har chaqiruvda til tekshiriladi

Ruscha tarjimasi yo'q nom avtomat o'zbekchaga qaytadi — bo'sh joy
hech qachon chiqmaydi.
"""

from __future__ import annotations

from bot.i18n import is_ru
from bot.locales import ru as _ru
from bot.locales import uz as _uz

__all__ = [name for name in dir(_uz) if not name.startswith("_")]


def __getattr__(name: str):  # noqa: ANN202
    """PEP 562: modul darajasidagi atribut so'ralganda chaqiriladi."""
    if is_ru():
        value = getattr(_ru, name, None)
        if value is not None:
            return value
    try:
        return getattr(_uz, name)
    except AttributeError as e:
        raise AttributeError(f"bot.texts da '{name}' yo'q") from e


def __dir__() -> list[str]:
    return __all__
