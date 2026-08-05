"""Bazani yo'qotmaslik uchun zaxira nusxa.

Nega oddiy fayl nusxasi emas? Bot ishlab turganda baza fayliga yozib
turiladi va o'sha paytda ko'chirilgan nusxa yarim yozilgan holatda
qolishi mumkin — ya'ni buzuq. SQLite'ning `VACUUM INTO` buyrug'i esa
tranzaksiya ichida ishlaydi va DOIM butun, siqilgan nusxa beradi.
Botni to'xtatish shart emas.

Nusxa ikki joyga boradi:
  1. DATA_DIR/backups papkasi (Railway'da — ulangan Volume)
  2. Telegram orqali adminlarga fayl sifatida — bepul TASHQI zaxira.
     Server yo'qolsa ham baza Telegramda saqlanib qoladi. Railway'da
     bu ayniqsa muhim: konteyner fayl tizimi vaqtinchalik bo'lishi mumkin.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.base import engine
from bot.services import settings_store as store

log = logging.getLogger(__name__)

KEEP = 14  # oxirgi 14 ta nusxa — taxminan ikki hafta


def backup_dir() -> Path:
    return settings.backups_path


def _db_path() -> Path | None:
    """sqlite+aiosqlite:////data/rado_job.db -> /data/rado_job.db"""
    url = settings.database_url
    if not url.startswith("sqlite"):
        return None
    return Path(url.split("///", 1)[-1])


async def create(stamp: str | None = None) -> Path | None:
    """Zaxira nusxa yaratadi va yo'lini qaytaradi."""
    if _db_path() is None:
        log.info("Zaxira o'tkazib yuborildi: baza SQLite emas (PostgreSQL'da pg_dump)")
        return None

    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    target = backup_dir() / f"rado_job-{stamp}.db"
    if target.exists():
        target.unlink()

    # VACUUM INTO fayl yo'lini matn sifatida oladi. Windows'dagi teskari
    # chiziqlar SQL uchun muammo bermasligi uchun to'g'ri chiziqqa o'giramiz.
    safe = str(target.resolve()).replace("\\", "/").replace("'", "''")
    async with engine.connect() as conn:
        await conn.execute(text(f"VACUUM INTO '{safe}'"))

    _prune()
    log.info("Zaxira nusxa: %s (%.1f KB)", target, target.stat().st_size / 1024)
    return target


async def create_and_send(
    bot: Bot,
    session: AsyncSession,
    *,
    stamp: str | None = None,
    caption: str = "💾 Zaxira nusxa",
    min_hours_since_sent: float = 0.0,
) -> Path | None:
    """Nusxa oladi va adminlarga Telegram orqali yuboradi.

    min_hours_since_sent — oxirgi yuborishdan shuncha soat o'tmagan bo'lsa
    yubormaydi (faqat diskka saqlaydi). Bu bot tez-tez qayta ishga
    tushadigan muhitda (Railway) har restartda spam bo'lmasligi uchun.
    """
    path = await create(stamp)
    if path is None:
        return None

    if min_hours_since_sent > 0:
        since = _hours_since_sent()
        if since is not None and since < min_hours_since_sent:
            log.info("Zaxira yuborilmadi: oxirgisi %.1f soat oldin", since)
            return path

    size_kb = path.stat().st_size / 1024
    text_caption = f"{caption}\n{path.name} · {size_kb:.0f} KB"
    sent = False

    # Alohida zaxira kanali bo'lsa — o'sha yerga. Shunda nusxalar oddiy
    # xabarlar orasida ko'milib ketmaydi va arxiv sifatida qidiriladi.
    target = store.backup_chat()
    if target is not None:
        try:
            await bot.send_document(target, FSInputFile(path), caption=text_caption)
            sent = True
        except Exception as e:
            log.warning("Zaxira kanaliga yuborilmadi: %s", e)

    if not sent:
        for admin_id in settings.admins:
            try:
                await bot.send_document(admin_id, FSInputFile(path), caption=text_caption)
                sent = True
            except Exception as e:
                log.warning("Zaxira adminga yuborilmadi (%s): %s", admin_id, e)

    if sent:
        await store.set_value(
            session, "last_backup_sent",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    return path


def _hours_since_sent() -> float | None:
    raw = store.get("last_backup_sent")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - value).total_seconds() / 3600


def _prune() -> None:
    files = sorted(backup_dir().glob("rado_job-*.db"))
    for old in files[:-KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def latest() -> Path | None:
    folder = backup_dir()
    if not folder.exists():
        return None
    files = sorted(folder.glob("*.db"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def age_hours() -> float | None:
    """Oxirgi zaxiradan beri necha soat o'tdi. None — umuman yo'q."""
    last = latest()
    if last is None:
        return None
    return (datetime.now().timestamp() - last.stat().st_mtime) / 3600


def db_size_kb() -> float:
    path = _db_path()
    if path is None or not path.exists():
        return 0.0
    total = path.stat().st_size
    # WAL fayli ham bazaning bir qismi — hisobga olamiz.
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            total += side.stat().st_size
    return total / 1024
