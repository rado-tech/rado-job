"""Zaxira nusxadan bazani TIKLASH — bot ichidan, fayl yuborish orqali.

Nega kerak? Railway'da (va ko'p bulut muhitlarida) Volume ichiga tashqaridan
fayl qo'yish yo'li yo'q: konteyner fayl tizimiga faqat ishlab turgan
jarayonning o'zi yeta oladi. Ya'ni `restore.py` skripti faqat lokal
kompyuterda foyda beradi.

Shuning uchun tiklashni botning o'ziga o'rnatamiz: egasi zaxira faylini
botga yuboradi, bot uni tekshirib, o'rniga qo'yadi va qayta ishga tushadi.
Server, tarif, CLI — hech biri kerak emas.

Xavfsizlik qatlamlari (tartib bilan):
  1. Faqat .env dagi EGASI — moderator ham, oddiy admin ham qila olmaydi
  2. Fayl avval VAQTINCHALIK joyga tushiriladi va o'sha yerda tekshiriladi
  3. Tekshiruv: haqiqiy SQLite, buzilmagan, bizning jadvallar bor
  4. Nechta foydalanuvchi/e'lon borligi KO'RSATILADI va tasdiq so'raladi
  5. Hozirgi baza O'CHIRILMAYDI — nomi o'zgartirilib chetga olinadi
"""

from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bot.services.backup import _db_path

log = logging.getLogger(__name__)

# Tiklash uchun majburiy jadvallar. Bittasi yetishmasa — bu bizning
# bazamiz emas (yoki juda eski nusxa), tiklash xavfli.
REQUIRED_TABLES = {"users", "jobs", "bookings", "settings"}


class RestoreError(Exception):
    """Tiklab bo'lmaydi — sabab foydalanuvchiga ko'rsatiladi."""


@dataclass
class Preview:
    """Tasdiqdan oldin ko'rsatiladigan ma'lumot."""

    path: Path        # tekshirilgan, ochilgan .db fayl (vaqtincha)
    users: int
    jobs: int
    bookings: int
    size_kb: float
    was_gz: bool


def workdir() -> Path:
    """Vaqtinchalik fayllar joyi — DATA_DIR ichida.

    Ataylab tizim temp papkasida emas: DATA_DIR bilan bitta disk bo'lsa,
    faylni ko'chirish o'rniga NOMINI o'zgartirish kifoya — bu bir zumda
    bo'ladi va yarim ko'chirilgan baza qolib ketmaydi.
    """
    from bot.config import settings

    path = settings.data_path / "restore-tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unpack(src: Path) -> tuple[Path, bool]:
    """.gz bo'lsa ochadi. Qaytaradi: (ochilgan fayl, siqilganmidi)."""
    if src.suffix != ".gz":
        return src, False
    target = src.with_suffix("")  # ....db.gz -> ....db
    if target.suffix != ".db":
        target = target.with_suffix(".db")
    try:
        with gzip.open(src, "rb") as fin, open(target, "wb") as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
    except OSError as e:
        raise RestoreError(f"Faylni ochib bo'lmadi (.gz buzilgan?): {e}") from e
    return target, True


def inspect(src: Path) -> Preview:
    """Faylni tekshiradi va ichidagi raqamlarni qaytaradi.

    Bazaga TEGMAYDI — faqat o'qiydi. Shu bosqichda yiqilsa, ishlab turgan
    baza butunligicha qoladi.
    """
    if not src.exists() or src.stat().st_size == 0:
        raise RestoreError("Fayl bo'sh yoki topilmadi.")

    path, was_gz = _unpack(src)

    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise RestoreError(f"Bu SQLite bazasi emas: {e}") from e

    try:
        verdict = con.execute("PRAGMA quick_check").fetchone()[0]
        if verdict != "ok":
            raise RestoreError(f"Baza buzilgan: {verdict}")

        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise RestoreError(
                "Bu Rado Job bazasi emas — jadvallar yetishmayapti: "
                + ", ".join(sorted(missing))
            )

        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        jobs = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        bookings = con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    except sqlite3.DatabaseError as e:
        raise RestoreError(f"Faylni o'qib bo'lmadi: {e}") from e
    finally:
        con.close()

    return Preview(
        path=path,
        users=int(users),
        jobs=int(jobs),
        bookings=int(bookings),
        size_kb=path.stat().st_size / 1024,
        was_gz=was_gz,
    )


async def apply(preview: Preview) -> Path:
    """Tekshirilgan nusxani ASOSIY baza qilib qo'yadi.

    Hozirgi bazaning nomi o'zgartirilib chetga olinadi va uning yo'li
    qaytariladi — xato bo'lsa qaytish uchun.

    Tartib muhim:
      1. WAL ni asosiy faylga ko'chiramiz
      2. barcha ulanishlarni yopamiz  <- shundan keyingina faylga tegish mumkin
      3. eskisini chetga, yangisini o'rniga
      4. WAL/SHM yordamchi fayllarini o'chiramiz (ular ESKI bazaga tegishli;
         qoldirilsa yangi baza ustiga tushib uni buzadi)
    """
    from bot.db.base import checkpoint, engine

    target = _db_path()
    if target is None:
        raise RestoreError("Baza SQLite emas — tiklash bu yo'l bilan ishlamaydi.")

    try:
        await checkpoint()
    except Exception as e:  # noqa: BLE001
        log.warning("Checkpoint bajarilmadi: %s", e)
    await engine.dispose()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    aside = target.with_name(f"{target.stem}.before-restore-{stamp}.db")

    if target.exists():
        target.replace(aside)
    for suffix in ("-wal", "-shm"):
        side = Path(str(target) + suffix)
        if side.exists():
            side.unlink()

    try:
        shutil.copy2(preview.path, target)
    except OSError as e:
        # Ko'chirish yiqildi — eskisini darhol joyiga qaytaramiz.
        if aside.exists():
            aside.replace(target)
        raise RestoreError(f"Faylni joyiga qo'yib bo'lmadi: {e}") from e

    log.warning("BAZA TIKLANDI: %s -> %s (eskisi: %s)", preview.path, target, aside)
    return aside


def cleanup() -> None:
    """Vaqtinchalik fayllarni o'chiradi."""
    try:
        shutil.rmtree(workdir(), ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        log.debug("Vaqtinchalik fayllar tozalanmadi: %s", e)
