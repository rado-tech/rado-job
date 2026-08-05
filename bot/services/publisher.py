"""Kanallarga joylash, postlarni yangilash, moderatsiyaga yuborish.

Bu yerdagi asosiy qiymat — Telegram nozikliklarini bir joyda ushlash:
guruh supergruppaga aylanishi, bot kanaldan chiqarilishi, postning
o'zgarmagani. Handler'lar bularni bilmasligi kerak.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramMigrateToChat
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import runtime
from bot.config import settings as env
from bot.db.models import Booking, Channel, Job, JobPost, JobStatus  # noqa: F401
from bot.keyboards import channel_post_kb, moderation_kb
from bot.services import channels as ch
from bot.services import jobs as svc
from bot.services import settings_store as store
from bot import texts

log = logging.getLogger(__name__)

# Postlarni tahrirlashda so'rovlar orasidagi pauza. Telegram sekundiga
# ~30 so'rovga ruxsat beradi; 20 ms bilan 50/sek chegarasiga yaqinlashmaymiz.
EDIT_DELAY = 0.05


class ChannelError(Exception):
    """Kanalga joylash imkonsiz — sabab foydalanuvchiga ko'rsatiladi."""


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:32]


async def _render(session: AsyncSession, job: Job) -> tuple[str, bool]:
    taken = await svc.taken_count(session, job.id)
    waiting = await svc.waitlist_count(session, job.id)
    text = texts.job_card(job, taken, waitlist=waiting)
    return text, job.status == JobStatus.OPEN


# ================================================================ joylash

async def publish_job(bot: Bot, session: AsyncSession, job: Job) -> tuple[int, list[str]]:
    """E'lonni unga mos BARCHA kanallarga joylaydi.

    Qaytaradi: (nechta kanalga joylandi, xatolar ro'yxati).
    Bitta kanal ishlamasa qolganlari baribir joylanadi — hammasi
    to'xtab qolmaydi.
    """
    targets = await ch.targets_for(session, job)
    if not targets:
        return 0, []

    text, open_ = await _render(session, job)
    posted, errors = 0, []

    for channel in targets:
        # Har kanalga o'z belgisi bilan — kim olib kelganini bilish uchun.
        kb = channel_post_kb(
            runtime.bot_username, job, open_=open_, channel_id=channel.id
        )
        try:
            msg = await _send(bot, session, channel, text, kb)
        except Exception as e:
            reason = _explain(e)
            errors.append(f"{channel.title or channel.chat_id}: {reason}")
            await ch.note_failure(session, channel, reason)
            log.warning("Kanalga joylanmadi (%s): %s", channel.chat_id, e)
            continue

        # Bir e'lon bir kanalda bir marta. Qayta joylansa eskisini almashtiramiz.
        existing = await session.scalar(
            select(JobPost).where(JobPost.job_id == job.id, JobPost.chat_id == channel.chat_id)
        )
        if existing:
            existing.message_id = msg.message_id
            existing.last_hash = _hash(text)
        else:
            session.add(
                JobPost(
                    job_id=job.id,
                    chat_id=channel.chat_id,
                    message_id=msg.message_id,
                    last_hash=_hash(text),
                )
            )
        await session.commit()
        await ch.note_success(session, channel)
        posted += 1
        await asyncio.sleep(EDIT_DELAY)

    return posted, errors


async def _send(bot: Bot, session: AsyncSession, channel: Channel, text: str, kb):  # noqa: ANN001
    """Yuboradi va chat ID o'zgarib qolgan bo'lsa o'zi to'g'rilaydi.

    Telegram oddiy guruhni supergruppaga aylantirganda ID BUTUNLAY
    o'zgaradi va eski ID bilan yuborilgan xabar xato beradi. Telegram
    javobida yangi ID ni beradi — uni ushlab, bazaga yozib qo'yamiz va
    qayta yuboramiz. Foydalanuvchi buni sezmaydi ham.
    """
    try:
        return await bot.send_message(channel.chat_id, text, reply_markup=kb)
    except TelegramMigrateToChat as e:
        old = channel.chat_id
        channel.chat_id = e.migrate_to_chat_id
        await session.commit()
        log.warning("Kanal supergruppaga aylandi: %s -> %s", old, channel.chat_id)
        return await bot.send_message(channel.chat_id, text, reply_markup=kb)


async def sync_job_post(bot: Bot, session: AsyncSession, job: Job) -> None:
    """Barcha kanallardagi postlarni bazadagi holatga moslaydi.

    Joylar to'lganda post o'zi «🔴 TO'LDI» ga aylanadi, joy bo'shasa qayta
    ochiladi. Admin qo'lda hech narsa yozmaydi.

    Tejamkorlik: matn o'zgarmagan bo'lsa Telegramga umuman murojaat
    qilmaymiz. Ko'p kanalda bu eng katta yuklamani oldini oladi.
    """
    posts = list(
        (await session.scalars(select(JobPost).where(JobPost.job_id == job.id))).all()
    )
    if not posts:
        return

    text, open_ = await _render(session, job)
    new_hash = _hash(text)

    # Post qaysi kanalga tegishli ekanini bilish uchun (tugma havolasi shunga
    # bog'liq).
    by_chat = {c.chat_id: c.id for c in await ch.all_channels(session)}

    for post in posts:
        if post.last_hash == new_hash:
            continue  # o'zgarish yo'q — so'rov ham yo'q
        kb = channel_post_kb(
            runtime.bot_username, job, open_=open_, channel_id=by_chat.get(post.chat_id)
        )
        try:
            await bot.edit_message_text(
                chat_id=post.chat_id,
                message_id=post.message_id,
                text=text,
                reply_markup=kb,
            )
            post.last_hash = new_hash
            await session.commit()
        except Exception as e:
            if "not modified" in str(e):
                post.last_hash = new_hash
                await session.commit()
            else:
                log.warning("Post yangilanmadi (job=%s chat=%s): %s", job.id, post.chat_id, e)
        await asyncio.sleep(EDIT_DELAY)


async def test_channel(bot: Bot, session: AsyncSession, channel: Channel) -> str:
    try:
        me = await bot.get_chat_member(channel.chat_id, (await bot.get_me()).id)
        info = await bot.get_chat(channel.chat_id)
    except Exception as e:
        return f"❌ <b>{channel.title}</b> — {_explain(e)}"

    if channel.kind == "channel" and me.status not in ("administrator", "creator"):
        return (
            f"⚠️ <b>{info.title}</b> — bot ADMIN emas, e'lon joylay olmaydi.\n"
            f"Kanal sozlamalari → Administratorlar → botni qo'shing va "
            f"«Xabar joylash» + «Xabarlarni tahrirlash» huquqlarini bering."
        )
    return f"✅ <b>{info.title}</b> — ishlayapti"


def _explain(e: Exception) -> str:
    text = str(e).lower()
    if "chat not found" in text:
        return "chat topilmadi (bot qo'shilmagan yoki ID xato)"
    if "not enough rights" in text or "need administrator" in text:
        return "huquq yetarli emas (botni admin qiling)"
    if "bot was kicked" in text or "bot is not a member" in text:
        return "bot chatdan chiqarib yuborilgan"
    if "have no rights to send" in text:
        return "xabar yuborish huquqi yo'q"
    return str(e)[:120]


# ================================================================ moderatsiya

async def send_to_moderation(bot: Bot, session: AsyncSession, booking: Booking) -> bool:
    """Chek skrinshotini moderatsiya chatiga tugmalari bilan yuboradi."""
    taken = await svc.taken_count(session, booking.job_id)

    # Ishchi qaysi kanal orqali kelgan — moderator uchun foydali ma'lumot.
    source = None
    if booking.source_channel_id:
        found = await session.get(Channel, booking.source_channel_id)
        source = found.title if found else None

    caption = texts.moderation_caption(booking, taken, source=source)

    # Shu chek boshqa arizada ishlatilganmi? Moderator buni eslab qololmaydi.
    duplicate = await svc.find_duplicate_receipt(
        session, booking.receipt_unique_id, booking.id
    )
    if duplicate is not None:
        caption += texts.duplicate_warning(duplicate)

    kb = moderation_kb(booking.id)

    target = store.chat_id("moderation_chat_id")
    if target is not None:
        try:
            await bot.send_photo(
                target, photo=booking.receipt_file_id, caption=caption, reply_markup=kb
            )
            return True
        except TelegramMigrateToChat as e:
            await store.set_value(session, "moderation_chat_id", str(e.migrate_to_chat_id))
            log.warning("Moderatsiya chati supergruppaga aylandi -> %s", e.migrate_to_chat_id)
            try:
                await bot.send_photo(
                    e.migrate_to_chat_id, photo=booking.receipt_file_id,
                    caption=caption, reply_markup=kb,
                )
                return True
            except Exception as e2:
                log.warning("Moderatsiya chatiga yuborilmadi: %s", e2)
        except Exception as e:
            log.warning("Moderatsiya chatiga yuborilmadi: %s", e)

    # Chat sozlanmagan yoki ishlamadi — xodimlarga shaxsan yuboramiz.
    # Chek hech qachon yo'qolmasligi kerak: bu odamning puli.
    delivered = False
    for staff_id in await _staff_ids(session):
        try:
            await bot.send_photo(
                staff_id, photo=booking.receipt_file_id, caption=caption, reply_markup=kb
            )
            delivered = True
        except Exception as e:
            log.warning("Xodimga yuborilmadi (%s): %s", staff_id, e)
    return delivered


async def _staff_ids(session: AsyncSession) -> list[int]:
    from bot.db.models import STAFF_ROLES, User

    rows = await session.scalars(select(User.id).where(User.role.in_(STAFF_ROLES)))
    return sorted(set(rows.all()) | env.admins)


async def notify_staff(bot: Bot, session: AsyncSession, text: str, reply_markup=None) -> None:  # noqa: ANN001
    """Xodimlarga ish bo'yicha xabar.

    Moderatsiya guruhi ulangan bo'lsa — AYNAN o'sha yerga. Shunda hamma
    ish bir joyda bo'ladi: cheklar ham, tasdiq kutayotgan e'lonlar ham,
    murojaatlar ham. Ilgari cheklar guruhga, qolgani lichkaga borardi va
    moderatorlar e'lonlarni umuman ko'rmasdi.
    """
    target = store.chat_id("moderation_chat_id")
    if target is not None:
        try:
            await bot.send_message(target, text, reply_markup=reply_markup)
            return
        except TelegramMigrateToChat as e:
            await store.set_value(session, "moderation_chat_id", str(e.migrate_to_chat_id))
            try:
                await bot.send_message(
                    e.migrate_to_chat_id, text, reply_markup=reply_markup
                )
                return
            except Exception as e2:
                log.warning("Moderatsiya guruhiga yuborilmadi: %s", e2)
        except Exception as e:
            log.warning("Moderatsiya guruhiga yuborilmadi: %s", e)

    for staff_id in await _staff_ids(session):
        try:
            await bot.send_message(staff_id, text, reply_markup=reply_markup)
        except Exception as e:
            log.debug("Xodimga xabar bormadi (%s): %s", staff_id, e)


async def notify_admins(bot: Bot, text: str, reply_markup=None) -> None:  # noqa: ANN001
    """Faqat .env dagi egalari — moderatorlarga tegishli bo'lmagan narsalar."""
    for admin_id in env.admins:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception as e:
            log.debug("Adminga xabar bormadi (%s): %s", admin_id, e)
