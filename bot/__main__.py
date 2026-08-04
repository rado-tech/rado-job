"""Botni ishga tushirish nuqtasi:  python -m bot"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, ErrorEvent

from bot import runtime, scheduler
from bot.config import settings
from bot.db.base import (
    SessionMaker,
    checkpoint,
    engine,
    init_db,
    integrity_check,
    pending_schema_changes,
)
from bot.handlers import build_router
from bot.middlewares import (
    DbSessionMiddleware,
    PrivateOnlyMiddleware,
    ThrottleMiddleware,
    UserMiddleware,
)
from bot.services import backup, channels, health
from bot.services import settings_store as store

def setup_logging() -> None:
    """Konsolga ham, faylga ham yozamiz.

    Fayl kerak: bot serverda ishlaganda konsolni hech kim ko'rmaydi, xato
    esa kechqurun sodir bo'ladi. Fayllar 5 MB dan oshganda avtomat
    almashadi va 5 tadan ortiq saqlanmaydi — disk to'lib qolmaydi.
    """
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.logs_path / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers = [console, file_handler]

    # aiogram har bir yangilanish uchun qator yozadi — bu jurnalni
    # ko'mib tashlaydi. Faqat ogohlantirishlarni qoldiramiz.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


log = logging.getLogger("bot")


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Boshlash"),
            BotCommand(command="ishlar", description="Ochiq e'lonlar"),
            BotCommand(command="mening", description="Mening ishlarim"),
            BotCommand(command="profil", description="Profil"),
            BotCommand(command="kasb", description="Qiziqishlarim"),
            BotCommand(command="help", description="Yordam"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )


async def main() -> None:
    setup_logging()
    startup_warnings: list[str] = []

    if not settings.admins:
        log.warning("ADMIN_IDS bo'sh! Admin panelga hech kim kira olmaydi.")

    # 1. Baza buzilmaganini tekshiramiz. Buzilish kam uchraydi, lekin
    #    jimgina uchraydi — erta bilgan yaxshi.
    verdict = await integrity_check()
    if verdict != "ok":
        log.error("BAZA BUZILGAN: %s", verdict)
        startup_warnings.append(f"🚨 <b>Baza buzilgan:</b> <code>{verdict}</code>")

    # 2. Sxema o'zgarishi bo'ladigan bo'lsa, ALTER TABLE dan OLDIN zaxira.
    #    Migratsiya xato ketsa qaytadigan joy bo'lsin.
    pending = await pending_schema_changes()
    if pending:
        log.warning("Sxema o'zgaradi: %s", ", ".join(pending))
        try:
            path = await backup.create(stamp="pre-migration")
            log.info("Migratsiyadan oldin zaxira olindi: %s", path)
        except Exception:
            log.exception("Migratsiyadan oldingi zaxira olinmadi")

    await init_db()
    async with SessionMaker() as session:
        await store.load(session)
        # Eski bitta-kanal sozlamasini yangi ko'p-kanal ro'yxatiga ko'chiramiz.
        await channels.migrate_legacy(session)
        gap = await health.downtime(session)
    if not store.is_payment_ready():
        log.warning("Karta rekvizitlari sozlanmagan — botda «⚙️ Sozlamalar» dan kiriting.")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    me = await bot.get_me()
    runtime.bot_username = me.username or ""
    log.info("Bot ishga tushdi: @%s (id=%s)", runtime.bot_username, me.id)

    # MemoryStorage — FSM holatlari xotirada. Bot qayta ishga tushsa
    # yo'qoladi; eng yomoni odam e'lonni qaytadan ochadi. Bir nechta
    # nusxada ishlatmoqchi bo'lsangiz RedisStorage'ga o'tasiz.
    dp = Dispatcher(storage=MemoryStorage())

    # OUTER middleware — filtrlardan OLDIN ishlaydi. Bu majburiy, chunki
    # huquq filtrlari (IsAdmin/IsStaff) rolni bazadan olingan `user`
    # obyektidan o'qiydi. Oddiy (inner) middleware filtrlardan KEYIN
    # ishlaganda `user` hali mavjud bo'lmasdi.
    #
    # Tartib shu bo'yicha arzonlashadi:
    #   1. anti-spam         — bazaga umuman tegmaydi
    #   2. baza sessiyasi
    #   3. foydalanuvchi + roli
    #   4. faqat shaxsiy chat — endi rolni biladi, moderatorlarni ham o'tkazadi
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(ThrottleMiddleware())
        observer.outer_middleware(DbSessionMiddleware())
        observer.outer_middleware(UserMiddleware())
        observer.outer_middleware(PrivateOnlyMiddleware())

    # Bot kanal/guruhga qo'shilgani haqidagi xabar. Anti-spam kerak emas
    # (odam yubormaydi), lekin baza sessiyasi kerak.
    dp.my_chat_member.outer_middleware(DbSessionMiddleware())
    dp.my_chat_member.outer_middleware(UserMiddleware())

    dp.include_router(build_router())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        """Global xato ushlagich.

        Busiz bitta handler'dagi kutilmagan xato jimgina yo'qoladi va
        foydalanuvchi "bot javob bermayapti" deb qoladi. Endi xato jurnalga
        tushadi va odamga tushunarli xabar boradi.
        """
        log.exception("Handler xatosi: %s", event.exception)
        try:
            if event.update.callback_query:
                await event.update.callback_query.answer(
                    "⚠️ Xatolik yuz berdi. Qaytadan urinib ko'ring.", show_alert=True
                )
            elif event.update.message:
                await event.update.message.answer(
                    "⚠️ Xatolik yuz berdi. /start bosib qaytadan urinib ko'ring."
                )
        except Exception:
            pass
        return True

    await set_commands(bot)

    # Bot o'chib turganda kelgan eski xabarlarni tashlaymiz — aks holda
    # qayta ishga tushganda o'nlab eski tugma bosishlari birdan ishlaydi.
    await bot.delete_webhook(drop_pending_updates=True)

    # Ishga tushganini adminlarga aytamiz. Kutilmagan qayta ishga tushish —
    # muammo belgisi; o'chib turgan vaqt ham shu yerda ko'rinadi.
    await _announce_start(bot, gap, startup_warnings)

    task = asyncio.create_task(scheduler.run(bot))
    try:
        await dp.start_polling(bot)
    finally:
        await _shutdown(bot, task)


async def _shutdown(bot: Bot, task: asyncio.Task) -> None:
    """To'g'ri to'xtatish.

    Tartib muhim:
      1. fon vazifasini to'xtatamiz
      2. WAL faylini asosiy bazaga ko'chiramiz — shundan keyin baza fayli
         o'zi butun bo'ladi
      3. zaxira nusxa olamiz (Railway kabi muhitda konteyner o'chganda
         fayl tizimi yo'qolishi mumkin — bu oxirgi imkoniyat)
      4. ulanishlarni yopamiz

    Hamma narsa vaqt chegarasi ostida: to'xtashga odatda 10-30 soniya
    beriladi, undan oshsa jarayon majburan o'ldiriladi.
    """
    task.cancel()
    try:
        await task
    except BaseException:
        pass

    try:
        await asyncio.wait_for(checkpoint(), timeout=10)
    except Exception:
        log.warning("WAL checkpoint ulgurmadi")

    try:
        async with SessionMaker() as session:
            await asyncio.wait_for(
                backup.create_and_send(
                    bot, session,
                    caption="💾 To'xtashdan oldingi zaxira",
                    # Bugun allaqachon yuborilgan bo'lsa qayta yubormaymiz —
                    # faqat diskka saqlaymiz. Tez-tez restartda spam bo'lmaydi.
                    min_hours_since_sent=20,
                ),
                timeout=20,
            )
    except Exception as e:
        log.warning("To'xtashdagi zaxira olinmadi: %s", e)

    await engine.dispose()
    await bot.session.close()
    log.info("Bot to'g'ri to'xtatildi, baza yopildi.")


async def _announce_start(bot: Bot, gap, warnings: list[str]) -> None:  # noqa: ANN001
    lines = ["🟢 <b>Bot ishga tushdi.</b>"]
    if gap is not None:
        lines.append(
            f"\n⚠️ Bundan oldin <b>{health.human(gap)}</b> o'chib turgan edi.\n"
            f"<i>Agar buni siz qilmagan bo'lsangiz — server yoki internetni "
            f"tekshiring.</i>"
        )
    age = backup.age_hours()
    if age is not None:
        lines.append(f"\n💾 Oxirgi zaxira: {age:.0f} soat oldin")
    lines.extend(warnings)

    for admin_id in settings.admins:
        try:
            await bot.send_message(admin_id, "\n".join(lines))
        except Exception:
            pass


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to'xtatildi.")
