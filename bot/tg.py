"""Telegram bilan ishlashdagi takrorlanuvchi nozikliklar.

Eng ko'p uchraydigani: xabarni O'ZGARMAGAN holatga tahrirlash. Telegram
bunga xato qaytaradi («message is not modified»), aiogram esa uni
istisno qilib ko'taradi. Ushlanmasa global xato ushlagichga tushadi va
foydalanuvchi «⚠️ Xatolik yuz berdi» degan yozuvni ko'radi — aslida
hech qanday xato yo'q, shunchaki o'zgartiradigan narsa bo'lmagan.

Aynan shu «Barchasi (filtrsiz)» tugmasini ishlamaydigan qilib qo'ygan
edi: filtr allaqachon bo'sh bo'lsa, tugma bosilgach klaviatura o'zi
bilan bir xil bo'lib chiqardi.
"""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

log = logging.getLogger(__name__)


def _harmless(e: Exception) -> bool:
    """Bu xato foydalanuvchiga ko'rsatishga arzimaydimi?

    «not modified» — o'zgarish yo'q.
    «message to edit not found» / «message can't be edited» — xabar
    o'chirilgan yoki juda eski (Telegram 48 soatdan keyin tahrirlashga
    ruxsat bermaydi).
    «query is too old» — tugma javobi kechikkan.
    """
    text = str(e).lower()
    return any(
        s in text
        for s in (
            "not modified",
            "message to edit not found",
            "message can't be edited",
            "message is not accessible",
            "query is too old",
        )
    )


async def edit_markup(message: Message, reply_markup=None) -> bool:  # noqa: ANN001
    """Tugmalarni almashtiradi. Muvaffaqiyatli bo'lsa True.

    Xabar o'zgarmagan bo'lsa jimgina False qaytaradi — bu xato emas.
    """
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
        return True
    except TelegramBadRequest as e:
        if _harmless(e):
            return False
        log.warning("Tugmalarni yangilab bo'lmadi: %s", e)
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("Tugmalarni yangilab bo'lmadi: %s", e)
        return False


async def edit_text(message: Message, text: str, reply_markup=None) -> bool:  # noqa: ANN001
    """Xabar matnini almashtiradi. Tahrirlab bo'lmasa False."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as e:
        if _harmless(e):
            return False
        log.warning("Xabarni tahrirlab bo'lmadi: %s", e)
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("Xabarni tahrirlab bo'lmadi: %s", e)
        return False


async def edit_or_send(message: Message, text: str, reply_markup=None) -> None:  # noqa: ANN001
    """Tahrirlashga urinadi; imkoni bo'lmasa YANGI xabar yuboradi.

    Ro'yxatlarni varaqlashda kerak: eski xabarni tahrirlab bo'lmasa ham
    foydalanuvchi ro'yxatni ko'rishi shart, aks holda tugma «o'lik»
    tuyuladi.
    """
    if await edit_text(message, text, reply_markup=reply_markup):
        return
    try:
        await message.answer(text, reply_markup=reply_markup)
    except Exception as e:  # noqa: BLE001
        log.warning("Xabar yuborilmadi: %s", e)


async def answer_cb(call: CallbackQuery, text: str = "", *, alert: bool = False) -> None:
    """call.answer() — kechikkan tugmada xato bermasin.

    Telegram tugma bosilgandan keyin ~15 soniya javob kutadi. Bot band
    bo'lsa (masalan tarqatish ketayotgan bo'lsa) shu muddat o'tib ketadi
    va javob berish xato beradi — foydalanuvchi uchun ahamiyatsiz.
    """
    try:
        await call.answer(text, show_alert=alert)
    except Exception:  # noqa: BLE001
        pass
