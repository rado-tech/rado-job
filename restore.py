"""Zaxira nusxadan bazani tiklash — xavfsiz usul.

Ishlatish:
    .venv\\Scripts\\python.exe restore.py            # nusxalar ro'yxati
    .venv\\Scripts\\python.exe restore.py backups\\rado_job-20260804-0400.db

Nima qiladi:
  1. Tanlangan nusxaning BUZILMAGANINI tekshiradi
  2. Hozirgi bazani O'CHIRMAYDI — nomini o'zgartirib chetga oladi
  3. Nusxani asosiy baza qilib qo'yadi

MUHIM: bundan oldin botni to'xtating (Ctrl+C).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Baza va zaxiralar DATA_DIR ichida (mahalliy: ".", Railway: "/data").
DATA_DIR = Path(os.environ.get("DATA_DIR", "."))
DB = DATA_DIR / "rado_job.db"
BACKUP_DIR = DATA_DIR / "backups"


def human_size(path: Path) -> str:
    return f"{path.stat().st_size / 1024:.0f} KB"


def human_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def verify(path: Path) -> tuple[bool, str]:
    """Nusxa haqiqiy va butun SQLite bazasimi?"""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        verdict = con.execute("PRAGMA quick_check").fetchone()[0]
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        jobs = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        bookings = con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        con.close()
    except Exception as e:
        return False, f"ochib bo'lmadi: {e}"
    if verdict != "ok":
        return False, f"buzilgan: {verdict}"
    return True, f"{users} foydalanuvchi, {jobs} e'lon, {bookings} ariza"


def main() -> None:
    backups = list_backups()

    if len(sys.argv) < 2:
        print(f"\n📂 Ma'lumot papkasi: {DATA_DIR.resolve()}")
        print("\n💾 Mavjud zaxira nusxalar:\n")
        if not backups:
            print("  (yo'q) — bot hali zaxira olmagan.")
            return
        for path in backups:
            ok, info = verify(path)
            mark = "✅" if ok else "❌"
            print(f"  {mark} {path}  ·  {human_time(path)}  ·  {human_size(path)}")
            print(f"      {info}")
        print("\nTiklash uchun:")
        print(f"  .venv\\Scripts\\python.exe restore.py {backups[0]}\n")
        return

    source = Path(sys.argv[1])
    if not source.exists():
        print(f"❌ Fayl topilmadi: {source}")
        sys.exit(1)

    ok, info = verify(source)
    if not ok:
        print(f"❌ Bu nusxadan tiklab bo'lmaydi — {info}")
        print("   Boshqa (eskiroq) nusxani sinab ko'ring.")
        sys.exit(1)

    print(f"\n📦 Manba: {source}")
    print(f"   {info}")
    print(f"   Sana: {human_time(source)}\n")

    if DB.exists():
        ok_now, info_now = verify(DB)
        print(f"📂 Hozirgi baza: {info_now if ok_now else '❌ ' + info_now}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside = DB.with_name(f"rado_job.before-restore-{stamp}.db")
        print(f"   U O'CHIRILMAYDI, chetga olinadi: {aside.name}\n")
    else:
        aside = None
        print("📂 Hozirgi baza yo'q — toza tiklash.\n")

    answer = input("Davom etamizmi? (ha/yo'q): ").strip().lower()
    if answer not in ("ha", "h", "yes", "y"):
        print("Bekor qilindi.")
        return

    # WAL/SHM yordamchi fayllari eski bazaga tegishli — ular ham chetga.
    if DB.exists() and aside is not None:
        DB.rename(aside)
        for suffix in ("-wal", "-shm"):
            side = Path(str(DB) + suffix)
            if side.exists():
                side.rename(Path(str(aside) + suffix))

    shutil.copy2(source, DB)
    print(f"\n✅ Tiklandi. Endi botni ishga tushiring:")
    print("   .venv\\Scripts\\python.exe -m bot")
    if aside:
        print(f"\nEski baza saqlanib turibdi: {aside.name}")
        print("Hammasi joyida ekaniga ishonch hosil qilgach o'chirsangiz bo'ladi.")


if __name__ == "__main__":
    main()
