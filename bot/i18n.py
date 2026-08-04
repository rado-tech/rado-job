"""Ko'p tillilik.

Ishlash tamoyili: har bir xabar qayta ishlanayotganda foydalanuvchining
tili `contextvar` ga yoziladi (middleware'da). `bot/texts.py` esa oddiy
modul emas, balki PROKSI: undan nima so'ralsa, joriy tilga mos lug'atdan
qaytaradi.

Shuning uchun handler'lardagi `texts.job_card(...)` chaqiruvlarining
birortasini o'zgartirish kerak emas — ular o'z-o'zidan to'g'ri tilda
ishlaydi.

Rus tiliga ISHCHI ko'radigan matnlar tarjima qilingan (auditoriyaning
asosiy qismi). Admin paneli o'zbekcha qoladi — uni siz va moderatorlar
ishlatasiz. Tarjimasi yo'q matn avtomat o'zbekchaga qaytadi, ya'ni
hech qachon bo'sh joy chiqmaydi.
"""

from __future__ import annotations

import contextvars

LANGS = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский"}
DEFAULT = "uz"

_current: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default=DEFAULT)


def set_lang(lang: str | None) -> None:
    _current.set(lang if lang in LANGS else DEFAULT)


def current_lang() -> str:
    return _current.get()


def is_ru() -> bool:
    return _current.get() == "ru"


def pick(uz_value, ru_value):  # noqa: ANN001, ANN201
    """Ikki qiymatdan joriy tilga mosini tanlaydi."""
    return ru_value if is_ru() else uz_value
