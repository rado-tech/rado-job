r"""Tiklash testi: zaxiradan bazani qaytarish HAQIQATAN ishlaydimi?

Ishga tushirish:
    .venv\Scripts\python.exe restore_test.py

Bu eng xavfli amal — butun baza almashtiriladi. Shuning uchun alohida
test: nusxa olinadi, baza ataylab "buziladi", keyin nusxadan tiklanadi
va ma'lumot qaytganiga ishonch hosil qilinadi.
"""

import asyncio
import os
import pathlib
import sys

DB = pathlib.Path("_restore.db")
os.environ["BOT_TOKEN"] = "111:AAAA"
os.environ["ADMIN_IDS"] = "5"
os.environ["DB_URL"] = "sqlite+aiosqlite:///./" + DB.name

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import gzip  # noqa: E402
import shutil  # noqa: E402
from datetime import timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

from bot.db.base import SessionMaker, engine, init_db, integrity_check  # noqa: E402
from bot.db.models import Job, JobStatus, Role, User  # noqa: E402
from bot.services import backup, dbrestore  # noqa: E402
from bot.services import settings_store as store  # noqa: E402
from bot.utils import local_today  # noqa: E402

failures = 0


def check(label, cond, detail=""):  # noqa: ANN001
    global failures
    print(("  OK  " if cond else "  XATO") + " " + label + ((" -- " + detail) if detail else ""))
    if not cond:
        failures += 1


async def count_users():
    async with SessionMaker() as s:
        return int((await s.scalar(select(func.count()).select_from(User))) or 0)


async def main():  # noqa: C901
    for p in (DB, pathlib.Path(DB.name + "-wal"), pathlib.Path(DB.name + "-shm")):
        p.unlink(missing_ok=True)
    await init_db()

    print("")
    print("== Boshlang'ich baza")
    async with SessionMaker() as s:
        await store.load(s)
        for i in range(6):
            s.add(User(id=100 + i, full_name="Foydalanuvchi " + str(i),
                       role=Role.WORKER, phone="+99890000000" + str(i),
                       region="Chilonzor"))
        await s.commit()
        s.add(Job(category="yuk", title="Eski ish", description="d",
                  secret_details="MAXFIY", region="Chilonzor",
                  work_date=local_today() + timedelta(days=1), start_time="08:00",
                  salary=100_000, fee=10_000, slots_total=2,
                  status=JobStatus.OPEN, created_by=100))
        await s.commit()
    before = await count_users()
    check("6 ta foydalanuvchi yozildi", before == 6, str(before))

    print("")
    print("== Zaxira olamiz (.gz)")
    path = await backup.create(stamp="restore-test")
    check("zaxira yaratildi", path is not None and path.exists())
    check("siqilgan", path.name.endswith(".db.gz"))

    print("")
    print("== Bazani 'yo'qotamiz' (server o'chgandek)")
    async with SessionMaker() as s:
        # Avval e'lonlar (ular foydalanuvchiga bog'langan), keyin odamlar.
        for j in (await s.scalars(select(Job))).all():
            await s.delete(j)
        await s.commit()
        for i in range(6):
            u = await s.get(User, 100 + i)
            if u:
                await s.delete(u)
        await s.commit()
    after_loss = await count_users()
    check("ma'lumot yo'qoldi", after_loss == 0, str(after_loss))

    print("")
    print("== Faylni tekshirish (bazaga tegmasdan)")
    preview = dbrestore.inspect(path)
    check("nusxadan 6 ta foydalanuvchi ko'rindi", preview.users == 6, str(preview.users))
    check("e'lon ham bor", preview.jobs == 1, str(preview.jobs))
    check(".gz ekani aniqlandi", preview.was_gz)
    check("tekshiruv ishlab turgan bazaga TEGMADI", await count_users() == 0)

    print("")
    print("== Yaroqsiz fayllar rad etiladi")
    junk = dbrestore.workdir() / "junk.db"
    junk.write_bytes(b"bu SQLite emas, oddiy matn" * 50)
    try:
        dbrestore.inspect(junk)
        check("axlat fayl rad etildi", False, "qabul qilindi!")
    except dbrestore.RestoreError as e:
        check("axlat fayl rad etildi", True, str(e)[:50])

    empty = dbrestore.workdir() / "empty.db"
    empty.write_bytes(b"")
    try:
        dbrestore.inspect(empty)
        check("bo'sh fayl rad etildi", False, "qabul qilindi!")
    except dbrestore.RestoreError as e:
        check("bo'sh fayl rad etildi", True, str(e)[:40])

    # Haqiqiy SQLite, lekin BOSHQA bazaning nusxasi
    import sqlite3
    alien = dbrestore.workdir() / "alien.db"
    con = sqlite3.connect(alien)
    con.execute("CREATE TABLE mehmon (id INTEGER)")
    con.commit()
    con.close()
    try:
        dbrestore.inspect(alien)
        check("begona baza rad etildi", False, "qabul qilindi!")
    except dbrestore.RestoreError as e:
        check("begona baza rad etildi", True, str(e)[:60])

    print("")
    print("== TIKLASH")
    preview = dbrestore.inspect(path)
    aside = await dbrestore.apply(preview)
    check("eski baza chetga olindi", aside.exists(), aside.name)

    # Tiklashdan keyin ulanish qaytadan ochiladi
    restored = await count_users()
    check("6 ta foydalanuvchi QAYTDI", restored == 6, str(restored))
    check("baza butun", await integrity_check() == "ok")

    async with SessionMaker() as s:
        job = await s.scalar(select(Job))
        check("e'lon ham qaytdi", job is not None and job.title == "Eski ish",
              job.title if job else "yo'q")
        check("maxfiy ma'lumot joyida", job is not None and "MAXFIY" in job.secret_details)

    print("")
    print("== Siqilmagan (.db) nusxa ham ishlaydi")
    plain = dbrestore.workdir() / "plain.db"
    with gzip.open(path, "rb") as fin, open(plain, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    pv = dbrestore.inspect(plain)
    check("oddiy .db o'qildi", pv.users == 6 and not pv.was_gz)

    await engine.dispose()
    dbrestore.cleanup()
    for p in (DB, pathlib.Path(DB.name + "-wal"), pathlib.Path(DB.name + "-shm")):
        p.unlink(missing_ok=True)
    for p in pathlib.Path(".").glob("_restore.before-restore-*.db"):
        p.unlink(missing_ok=True)
    if path:
        path.unlink(missing_ok=True)

    print("")
    if failures:
        print("NATIJA: " + str(failures) + " ta muammo")
        sys.exit(1)
    print("NATIJA: tiklash testi o'tdi")


asyncio.run(main())
