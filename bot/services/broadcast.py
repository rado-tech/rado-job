"""Ommaviy xabar tarqatish — minglab foydalanuvchi uchun.

Telegram cheklovi: turli odamlarga sekundiga ~30 ta xabar. Undan oshsangiz
bot vaqtincha bloklanadi (429). Shuning uchun xabarlarni to'plamlarga bo'lib,
har sekundiga qat'iy me'yorda yuboramiz.

Ketma-ket (birma-bir) yuborish 10 000 odamga ~10 daqiqa oladi. Bu usul
to'plamlab parallel yuboradi va shu vaqtni ~7 daqiqaga tushiradi, ayni paytda
cheklovga urilmaydi. Bundan tezroq qilishning yagona yo'li — Telegramdan
rasmiy limit oshirilishini so'rash.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

log = logging.getLogger(__name__)

# Sekundiga nechta xabar. 30 — Telegram chegarasi, 25 — xavfsiz masofa.
RATE_PER_SECOND = 25


@dataclass
class Result:
    sent: int = 0
    blocked: list[int] = field(default_factory=list)  # botni o'chirganlar
    failed: int = 0

    @property
    def total(self) -> int:
        return self.sent + len(self.blocked) + self.failed


async def send_bulk(
    bot: Bot,
    user_ids: Sequence[int],
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    on_progress: Callable[[Result], Awaitable[None]] | None = None,
    progress_every: int = 500,
) -> Result:
    result = Result()
    ids = list(user_ids)

    for start in range(0, len(ids), RATE_PER_SECOND):
        chunk = ids[start : start + RATE_PER_SECOND]
        began = asyncio.get_running_loop().time()

        outcomes = await asyncio.gather(
            *(_send_one(bot, uid, text, reply_markup) for uid in chunk),
            return_exceptions=True,
        )
        for uid, outcome in zip(chunk, outcomes):
            if outcome is True:
                result.sent += 1
            elif outcome == "blocked":
                result.blocked.append(uid)
            else:
                result.failed += 1

        if on_progress and result.total % progress_every < RATE_PER_SECOND:
            await on_progress(result)

        # Sekundni to'ldiramiz — shu bilan tezlik me'yorda ushlanadi.
        elapsed = asyncio.get_running_loop().time() - began
        if elapsed < 1.0 and start + RATE_PER_SECOND < len(ids):
            await asyncio.sleep(1.0 - elapsed)

    return result


async def send_bulk_copy(
    bot: Bot,
    user_ids: Sequence[int],
    *,
    from_chat_id: int,
    message_id: int,
    reply_markup: InlineKeyboardMarkup | None = None,
    on_progress: Callable[[Result], Awaitable[None]] | None = None,
    progress_every: int = 500,
) -> Result:
    """Tayyor xabarning NUSXASINI hammaga yuboradi.

    Reklama uchun aynan shu kerak: admin botga istalgan narsani yuboradi
    (matn, rasm, video, rasm+izoh) va bot uni o'sha ko'rinishida
    tarqatadi. Nusxa forward emas — «Forwarded from» yozuvi chiqmaydi va
    reklama tabiiy ko'rinadi.
    """
    result = Result()
    ids = list(user_ids)

    for start in range(0, len(ids), RATE_PER_SECOND):
        chunk = ids[start : start + RATE_PER_SECOND]
        began = asyncio.get_running_loop().time()

        outcomes = await asyncio.gather(
            *(
                _copy_one(bot, uid, from_chat_id, message_id, reply_markup)
                for uid in chunk
            ),
            return_exceptions=True,
        )
        for uid, outcome in zip(chunk, outcomes):
            if outcome is True:
                result.sent += 1
            elif outcome == "blocked":
                result.blocked.append(uid)
            else:
                result.failed += 1

        if on_progress and result.total % progress_every < RATE_PER_SECOND:
            await on_progress(result)

        elapsed = asyncio.get_running_loop().time() - began
        if elapsed < 1.0 and start + RATE_PER_SECOND < len(ids):
            await asyncio.sleep(1.0 - elapsed)

    return result


async def _copy_one(
    bot: Bot, user_id: int, from_chat_id: int, message_id: int,
    reply_markup: InlineKeyboardMarkup | None,
):
    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            await bot.copy_message(
                chat_id=user_id, from_chat_id=from_chat_id,
                message_id=message_id, reply_markup=reply_markup,
            )
            return True
        except Exception:
            return "failed"
    except TelegramForbiddenError:
        return "blocked"
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            return "blocked"
        log.debug("Nusxa yuborilmadi %s: %s", user_id, e)
        return "failed"
    except Exception as e:
        log.debug("Nusxa yuborilmadi %s: %s", user_id, e)
        return "failed"


async def _send_one(
    bot: Bot, user_id: int, text: str, reply_markup: InlineKeyboardMarkup | None
):
    try:
        await bot.send_message(user_id, text, reply_markup=reply_markup)
        return True
    except TelegramRetryAfter as e:
        # Telegram "sekinlashtir" dedi — kutamiz va bir marta qayta urinamiz.
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            await bot.send_message(user_id, text, reply_markup=reply_markup)
            return True
        except Exception:
            return "failed"
    except TelegramForbiddenError:
        # Odam botni bloklagan yoki o'chirgan — normal holat, xato emas.
        return "blocked"
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            return "blocked"
        log.debug("Yuborilmadi %s: %s", user_id, e)
        return "failed"
    except Exception as e:
        log.debug("Yuborilmadi %s: %s", user_id, e)
        return "failed"
