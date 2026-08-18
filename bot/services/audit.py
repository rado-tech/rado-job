"""Moderator/admin harakatlari jurnali.

Bir nechta moderator ishlaganda «kim tasdiqladi, kim blokladi, kim narxni
o'zgartirdi» degan savol albatta chiqadi. Har muhim harakat shu yerga
yoziladi; jurnalni faqat admin ko'radi (⚙️ Sozlamalar → 📋 Jurnal).

Yozish hech qachon asosiy oqimni to'xtatmasligi kerak: jurnal yozilmasa ham
chek tasdiqlanaveradi — shuning uchun log() xatoni yutadi.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import StaffAction

log = logging.getLogger(__name__)

# Harakat kodi -> jurnalda ko'rinadigan yozuv. Kod qisqa saqlanadi (bazada),
# matn esa istalgan payt o'zgartirilishi mumkin — eski yozuvlar buzilmaydi.
ACTION_LABEL: dict[str, str] = {
    "receipt_ok": "✅ chekni tasdiqladi",
    "receipt_no": "❌ chekni rad etdi",
    "undo": "↩️ qarorni qaytardi",
    "job_ok": "🟢 e'lonni tasdiqladi",
    "job_no": "🚫 e'lonni rad etdi",
    "job_edit": "✏️ e'lonni tahrirladi",
    "job_close": "🔒 e'lonni yopdi",
    "job_reopen": "🔓 e'lonni ochdi",
    "job_cancel": "❌ ishni bekor qildi",
    "job_fee": "💳 e'lon narxini o'zgartirdi",
    "job_post": "📢 kanallarga joyladi",
    "user_block": "🚫 foydalanuvchini blokladi",
    "user_unblock": "✅ blokdan chiqardi",
    "user_mod": "🛡 moderator qildi",
    "user_unmod": "🗑 moderatorlikdan oldi",
    "worker_done": "✅ «ishga chiqdi» deb belgiladi",
    "worker_noshow": "🚷 «chiqmadi» deb belgiladi",
    "channel_add": "➕ kanal qo'shdi",
    "channel_del": "🗑 kanalni o'chirdi",
    "channel_toggle": "⏯ kanal holatini o'zgartirdi",
    "ad_sent": "📣 reklama yubordi",
    "backup": "💾 zaxira oldi",
    "restore": "♻️ BAZANI TIKLADI",
    "freemode": "🆓 bepul rejimni o'zgartirdi",
    "report_answer": "✍️ murojaatga javob berdi",
    "report_close": "✅ murojaatni yopdi",
}


async def log_action(
    session: AsyncSession, staff_id: int, action: str, target: str = "", details: str = ""
) -> None:
    try:
        session.add(
            StaffAction(
                staff_id=staff_id,
                action=action,
                target=(target or "")[:64],
                details=(details or "")[:256],
            )
        )
        await session.commit()
    except Exception as e:  # jurnal asosiy ishni to'xtatmasin
        log.warning("Jurnalga yozilmadi (%s): %s", action, e)


async def recent(
    session: AsyncSession, *, offset: int = 0, limit: int = 10
) -> tuple[list[StaffAction], int]:
    total = int(
        (await session.scalar(select(func.count()).select_from(StaffAction))) or 0
    )
    rows = list(
        (
            await session.scalars(
                select(StaffAction)
                .order_by(StaffAction.created_at.desc(), StaffAction.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    return rows, total


def label(action: str) -> str:
    return ACTION_LABEL.get(action, action)
