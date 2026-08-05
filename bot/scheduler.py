"""Fon vazifalari — hech kim tugma bosmasa ham ishlaydigan qism.

Har daqiqada:
  1. Vaqtida chek yubormaganlarning bronini bekor qiladi, joyni bo'shatadi
  2. Ishchiga "vaqtingiz tugadi" deb xabar beradi
  3. Bo'shagan joyga navbatdagi birinchi odamni chaqiradi
  4. Kanallardagi postlarni yangilaydi
  5. Sanasi o'tib ketgan e'lonlarni yopadi

Kuniga bir marta:
  6. Bazadan zaxira nusxa oladi va uni adminlarga Telegram orqali yuboradi
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from bot import texts
from bot.config import TZ
from bot.db.base import SessionMaker
from bot.services import backup, health, jobs as svc
from bot.services import notifier, publisher

log = logging.getLogger(__name__)

TICK_SECONDS = 60
BACKUP_HOUR = 4    # Toshkent vaqti bilan tunda — yuklama eng kam paytda
REPORT_HOUR = 21   # Kunlik hisobot: ertangi bo'sh joylarni ko'rish uchun kech


async def run(bot: Bot) -> None:
    # Bot endigina ko'tarildi — Telegram bilan aloqa o'rnashsin.
    await asyncio.sleep(5)
    last_backup_day: str | None = None
    last_report_day: str | None = None

    # Bot 04:00 da o'chib turgan bo'lsa o'sha kunlik zaxira o'tkazib
    # yuborilardi. Shuning uchun ishga tushganda ham tekshiramiz: oxirgi
    # nusxa 20 soatdan eski bo'lsa — darhol yangisini olamiz.
    age = backup.age_hours()
    if age is None or age > 20:
        try:
            await _daily_backup(bot, datetime.now(TZ).strftime("%Y-%m-%d"))
            last_backup_day = datetime.now(TZ).strftime("%Y-%m-%d")
        except Exception:
            log.exception("Ishga tushishdagi zaxira olinmadi")

    while True:
        try:
            await _tick(bot)

            now = datetime.now(TZ)
            today = now.strftime("%Y-%m-%d")
            if now.hour >= BACKUP_HOUR and last_backup_day != today:
                last_backup_day = today
                await _daily_backup(bot, today)

            if now.hour >= REPORT_HOUR and last_report_day != today:
                last_report_day = today
                await _daily_report(bot, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Fon vazifasi hech qachon "o'lib qolmasligi" kerak — xatoni
            # yozib qo'yamiz va keyingi tsiklda davom etamiz.
            log.exception("Scheduler xatosi")
        await asyncio.sleep(TICK_SECONDS)


async def _tick(bot: Bot) -> None:
    async with SessionMaker() as session:
        # «Men tirikman» belgisi. Bot to'xtab qolsa, qayta ishga tushganda
        # shu belgiga qarab qancha vaqt o'chib turgani aniqlanadi.
        await health.heartbeat(session)

        expired = await svc.expire_holds(session)
        for b in expired:
            try:
                await bot.send_message(b.user_id, texts.booking_expired(b.job))
            except Exception:
                pass

        touched = {b.job for b in expired}
        touched.update(await svc.close_past_jobs(session))
        for job in touched:
            await publisher.sync_job_post(bot, session, job)

        # Bo'sh joyi ham, navbati ham bor e'lonlar — navbatdagini chaqiramiz.
        for job_id in await svc.jobs_needing_promotion(session):
            await notifier.promote_and_notify(bot, session, job_id)

        # Eslatmalar: ish oldingi kuni kechqurun va ishgacha bir necha soat.
        evening = await notifier.send_reminders(bot, session, "evening")
        soon = await notifier.send_reminders(bot, session, "soon")

        # Tugagan ishlar bo'yicha «chiqdingizmi?» so'rovi.
        asked = await notifier.ask_attendance(bot, session)

        if expired:
            log.info("%s ta bron muddati tugadi", len(expired))
        if evening or soon or asked:
            log.info(
                "Eslatma: kechqurun=%s, tez orada=%s · davomat so'rovi=%s",
                evening, soon, asked,
            )


async def _daily_report(bot: Bot, now) -> None:  # noqa: ANN001
    """Kunlik hisobot — kechqurun xodimlarga.

    Soat 21:00 da yuboriladi: shu paytda ertangi e'lonlar to'lgan-to'lmagani
    aniq bo'ladi va bo'sh joylarni to'ldirishga hali vaqt bor.
    """
    since = (now - timedelta(days=1)).astimezone(timezone.utc)
    async with SessionMaker() as session:
        summary = await svc.daily_summary(session, since)
        text = texts.daily_report(summary, now.strftime("%d.%m.%Y"))
        # Faqat adminlarga: hisobotda TUSHUM bor, moderatorlar moliyaviy
        # ma'lumotni ko'rmasligi kerak (statistika ham shunday cheklangan).
        await publisher.notify_admins(bot, text)
    log.info("Kunlik hisobot yuborildi")


async def _daily_backup(bot: Bot, day: str) -> None:
    """Kunlik zaxira + uni Telegram orqali adminlarga yuborish.

    Telegramga yuborish — bepul TASHQI zaxira. Server yo'qolsa ham baza
    sizning Telegramingizda saqlanib qoladi. Railway kabi muhitlarda
    (fayl tizimi vaqtinchalik bo'lishi mumkin) bu asosiy himoya.

    min_hours_since_sent=20 — bot bir kunda bir necha marta qayta ishga
    tushsa ham fayl kuniga BIR MARTA yuboriladi, spam bo'lmaydi.
    """
    async with SessionMaker() as session:
        path = await backup.create_and_send(
            bot,
            session,
            caption=f"💾 Kunlik zaxira · {day}",
            min_hours_since_sent=20,
        )
    if path:
        log.info("Kunlik zaxira tayyor: %s", path)
