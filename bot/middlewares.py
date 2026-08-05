"""Middleware — har bir xabardan oldin avtomat bajariladigan kod.

Uchta vazifa:
  1. Anti-spam: bir odam sekundiga o'nlab tugma bosib, botni cho'ktirmasin
  2. Baza sessiyasini ochish/yopish (handler ichida yozib yurmaymiz)
  3. Foydalanuvchini topish/yaratish, bloklanganini to'xtatish
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TgUser

from bot import texts
from bot.db.base import SessionMaker
from bot.i18n import set_lang
from bot.permissions import is_staff
from bot.services.jobs import get_or_create_user


class ThrottleMiddleware(BaseMiddleware):
    """Bir foydalanuvchidan minimal interval.

    Nega kerak? Bitta odam tugmani ketma-ket 30 marta bossa, har bosish
    baza so'rovi va Telegram chaqiruvi demak. Minglab foydalanuvchida
    bir nechta shunday odam butun botni sekinlashtiradi.

    Ogohlantirish faqat BIR MARTA yuboriladi: aks holda spamga javoban
    spam qilgan bo'lardik.
    """

    def __init__(self, interval: float = 0.4, ttl: float = 300.0) -> None:
        self.interval = interval
        self.ttl = ttl
        self._seen: dict[int, tuple[float, bool]] = {}
        self._last_cleanup = time.monotonic()

    def _cleanup(self, now: float) -> None:
        # Xotira o'smasligi uchun eskilarni tozalaymiz.
        if now - self._last_cleanup < self.ttl:
            return
        self._last_cleanup = now
        self._seen = {k: v for k, v in self._seen.items() if now - v[0] < self.ttl}

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:  # noqa: ANN001
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        now = time.monotonic()
        self._cleanup(now)
        last, warned = self._seen.get(tg_user.id, (0.0, False))

        if now - last < self.interval:
            self._seen[tg_user.id] = (now, True)
            if not warned:
                if isinstance(event, CallbackQuery):
                    await event.answer(texts.TOO_FAST)
                elif isinstance(event, Message):
                    await event.answer(texts.TOO_FAST)
            return None

        self._seen[tg_user.id] = (now, False)
        return await handler(event, data)


class PrivateOnlyMiddleware(BaseMiddleware):
    """Bot faqat SHAXSIY yozishmada javob beradi.

    Nega bu xavfsizlik masalasi? Botni istalgan odam o'z guruhiga qo'shishi
    mumkin. Agar bot guruhdagi buyruqlarga javob bersa:
      * admin o'sha guruhda /sozlama yozsa — KARTA RAQAMI guruhga chiqadi
      * /users — foydalanuvchilar TELEFON RAQAMLARI
      * /stats — tushum ma'lumotlari
      * oddiy odam /mening yozsa — o'z arizalari hammaga ko'rinadi
      * e'lon kartasi guruhga forward qilinsa, «Yozilish» tugmasi bosilganda
        TO'LOV REKVIZITLARI guruhga tushadi

    Ikkita istisno bor:
      1. /id — sozlashda guruh ID sini bilish uchun kerak, maxfiy emas
      2. Guruhdagi tugmalar — moderatsiya chati aynan guruh bo'lishi mumkin,
         lekin faqat ADMIN bosgan bo'lsa
    """

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:  # noqa: ANN001
        if isinstance(event, Message):
            if event.chat.type == "private":
                return await handler(event, data)
            # Guruhda faqat /id ga javob beramiz — u hech qanday maxfiy
            # ma'lumot ochmaydi va sozlash uchun zarur.
            text = (event.text or "").strip()
            if text.startswith("/id"):
                return await handler(event, data)

            # Xodim guruhda javob yozayotgan bo'lsa — o'tkazamiz.
            #
            # Nega kerak? Moderator chekni «rad etish» bosgach, bot undan
            # sabab so'raydi. Sabab AYNAN o'sha guruhda yoziladi. Bu qoida
            # bo'lmasa, yozilgan matn jimgina yo'qolardi va rad etish
            # umuman ishlamasdi.
            #
            # Xavfsiz, chunki ikkita shart birga tekshiriladi:
            #   * odam xodim (admin yoki moderator)
            #   * bot AYNAN shu odamdan javob kutib turibdi (FSM holati bor)
            # Begona odamda holat paydo bo'lmaydi — tugmalar unga ishlamaydi.
            if data.get("raw_state") is not None and is_staff(data.get("user")):
                return await handler(event, data)
            return None

        if isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message else None
            if chat is None or chat.type == "private":
                return await handler(event, data)
            # Guruhdagi tugmalar — bu moderatsiya chati bo'lishi mumkin.
            # Faqat xodimlarga (admin/moderator) ruxsat.
            if is_staff(data.get("user")):
                return await handler(event, data)
            await event.answer(
                "Bu tugma shaxsiy yozishmada ishlaydi. Botga o'ting.", show_alert=True
            )
            return None

        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with SessionMaker() as session:
            data["session"] = session
            return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        # Kanal postlari va bot xabarlarida foydalanuvchi bo'lmaydi.
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        user = await get_or_create_user(data["session"], tg_user)
        data["user"] = user

        # Shu xabar davomida barcha matnlar foydalanuvchining tilida
        # bo'lishi uchun. bot/texts.py shu qiymatga qarab tanlaydi.
        set_lang(user.lang)

        if user.is_blocked:
            if isinstance(event, Message):
                await event.answer(texts.BLOCKED)
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.BLOCKED, show_alert=True)
            return None

        return await handler(event, data)
