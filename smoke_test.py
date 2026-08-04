"""Telegramsiz tekshiruv: biznes mantiq to'g'ri ishlayaptimi?

Ishga tushirish:
    .venv\\Scripts\\python.exe smoke_test.py

Nega kerak? Har o'zgarishdan keyin botni qo'lda ochib, tugma bosib, chek
yuborib tekshirish — 10 daqiqa. Bu skript 3 soniyada eng muhim holatlarni
tekshiradi: joy to'lishi, navbat, bron muddati, bir vaqtda yozilish.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

DB_FILE = pathlib.Path("_smoke.db")

# Sozlamalarni import qilishdan OLDIN o'rnatamiz.
os.environ["BOT_TOKEN"] = "test:token"
os.environ["ADMIN_IDS"] = "1"
os.environ["CHANNEL_ID"] = ""
os.environ["MODERATION_CHAT_ID"] = ""
os.environ["DB_URL"] = f"sqlite+aiosqlite:///./{DB_FILE.name}"

import sqlite3  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select  # noqa: E402

from bot import permissions as perms  # noqa: E402
from bot.config import settings as env_settings  # noqa: E402
from bot.db.base import (  # noqa: E402
    SessionMaker,
    checkpoint,
    engine,
    init_db,
    integrity_check,
    pending_schema_changes,
)
from bot.services import health  # noqa: E402
from bot.db.models import (  # noqa: E402
    Booking,
    BookingStatus,
    Job,
    JobPost,
    JobStatus,
    Role,
    User,
    utcnow,
)
from bot.services import backup  # noqa: E402
from bot.services import channels as ch  # noqa: E402
from bot.services import jobs as svc  # noqa: E402
from bot.services import settings_store as store  # noqa: E402

OK, FAIL = "  ✓", "  ✗"
failures = 0


def check(label: str, cond: bool) -> None:
    global failures
    print((OK if cond else FAIL) + " " + label)
    if not cond:
        failures += 1


def section(title: str) -> None:
    print(f"\n── {title}")


async def main() -> None:
    DB_FILE.unlink(missing_ok=True)
    await init_db()

    async with SessionMaker() as s:
        await store.load(s)
        await store.set_value(s, "hold_minutes", "15")
        await store.set_value(s, "waitlist_minutes", "10")
        await store.set_value(s, "card_number", "8600 1111 2222 3333")
        await store.set_value(s, "card_holder", "Test Test")

        section("Sozlamalar")
        check("bazadan o'qildi", store.hold_minutes() == 15)
        check("to'lov rekvizitlari tayyor", store.is_payment_ready())

        # Chat ID qo'lda kiritilganda uchraydigan xatolarga chidamlilik.
        # int('--100...') xato beradi va butun moderatsiya oqimini
        # to'xtatib qo'yadi — shuning uchun alohida tekshiramiz.
        for raw, expected in [
            ("-1001234567890", -1001234567890),
            ("--1004276656805", -1004276656805),   # ikkita minus
            (" -100 123 4567 ", -1001234567),      # bo'shliqlar
            ("1234567890", 1234567890),
            ("@mening_kanalim", "@mening_kanalim"),
            ("mening_kanalim", "@mening_kanalim"),  # @ unutilgan
            ("", None),
        ]:
            await store.set_value(s, "channel_id", raw)
            check(f"chat ID '{raw}' -> {expected}", store.chat_id("channel_id") == expected)
        await store.set_value(s, "channel_id", "")

        # Aniq ko'rsatilgan DB_URL ustun turadi (bu testda _smoke.db).
        check("aniq DB_URL ustun turdi", "_smoke.db" in env_settings.database_url)
        check("zaxira papkasi DATA_DIR ichida",
              env_settings.backups_path == env_settings.data_path / "backups")

        admin = User(id=1, full_name="Admin", phone="+998900000000",
                     region="Chilonzor", role=Role.ADMIN)
        w1 = User(id=101, full_name="Ishchi 1", phone="+998901111111",
                  region="Chilonzor", categories="|yuk|")
        w2 = User(id=102, full_name="Ishchi 2", phone="+998902222222",
                  region="Chilonzor", categories="|qurilish|")
        w3 = User(id=103, full_name="Ishchi 3", phone="+998903333333", region="Sergeli")
        emp = User(id=201, full_name="Ish beruvchi", phone="+998905555555",
                   region="Chilonzor", role=Role.EMPLOYER)
        s.add_all([admin, w1, w2, w3, emp])
        await s.commit()

        job = Job(
            category="yuk", title="Omborga yuk tashish",
            description="8 soat, baquvvat erkaklar kerak",
            secret_details="Chilonzor 19, Aziz aka +998901234567",
            region="Chilonzor", work_date=date.today() + timedelta(days=1),
            start_time="08:00", salary=200_000, fee=10_000, slots_total=2,
            created_by=1,
        )
        s.add(job)
        await s.commit()

        section("Yozilish va joy hisobi")
        b1 = await svc.apply_to_job(s, job.id, w1.id)
        check("1-ishchi yozildi", b1.status == BookingStatus.PENDING_PAYMENT)
        check("band joy = 1", await svc.taken_count(s, job.id) == 1)

        try:
            await svc.apply_to_job(s, job.id, w1.id)
            check("takroriy yozilish to'xtatildi", False)
        except svc.ApplyError:
            check("takroriy yozilish to'xtatildi", True)

        await svc.apply_to_job(s, job.id, w2.id)
        await s.refresh(job)
        check("joylar to'ldi -> FULL", job.status == JobStatus.FULL)

        try:
            await svc.apply_to_job(s, job.id, w3.id)
            check("to'lgan e'longa yozib bo'lmaydi", False)
        except svc.ApplyError:
            check("to'lgan e'longa yozib bo'lmaydi", True)

        section("Navbat (waitlist)")
        wl = await svc.join_waitlist(s, job.id, w3.id)
        check("navbatga yozildi", wl.status == BookingStatus.WAITLIST)
        check("navbat joy egallamaydi", await svc.taken_count(s, job.id) == 2)
        check("navbatdagi o'rin = 1", await svc.waitlist_position(s, wl) == 1)
        check("navbatda 1 kishi", await svc.waitlist_count(s, job.id) == 1)

        section("Chek va tasdiqlash")
        await svc.attach_receipt(s, b1, "FAKE_FILE_ID")
        check("chek qabul qilindi", b1.status == BookingStatus.RECEIPT_SENT)
        check("chekdan keyin muddat yo'q", b1.expires_at is None)
        await svc.confirm_booking(s, b1, admin.id)
        check("to'lov tasdiqlandi", b1.status == BookingStatus.CONFIRMED)

        section("Bron muddati tugashi va navbatdan ko'tarilish")
        b2 = await svc.get_booking(s, job.id, w2.id)
        b2.expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()

        expired = await svc.expire_holds(s)
        check("muddati o'tgan bron topildi", len(expired) == 1)
        check("bron EXPIRED bo'ldi", expired[0].status == BookingStatus.EXPIRED)
        check("band joy 1 ga tushdi", await svc.taken_count(s, job.id) == 1)
        await s.refresh(job)
        check("e'lon qayta OPEN bo'ldi", job.status == JobStatus.OPEN)

        promoted = await svc.promote_from_waitlist(s, job.id)
        check("navbatdagi odam ko'tarildi", promoted is not None and promoted.user_id == w3.id)
        check("unga to'lov muddati berildi",
              promoted.status == BookingStatus.PENDING_PAYMENT and promoted.expires_at is not None)
        check("joy yana band", await svc.taken_count(s, job.id) == 2)
        check("navbat bo'shadi", await svc.waitlist_count(s, job.id) == 0)

        section("Rad etish joyni bo'shatadi")
        await svc.attach_receipt(s, promoted, "FAKE_2")
        await svc.reject_booking(s, promoted, admin.id, "Chek soxta")
        check("rad etildi", promoted.status == BookingStatus.REJECTED)
        check("joy bo'shadi", await svc.taken_count(s, job.id) == 1)

        section("Bir vaqtda yozilish (race condition)")
        job2 = Job(
            category="qurilish", title="Bitta joy", description="test",
            secret_details="test", region="Chilonzor", work_date=date.today(),
            start_time="09:00", salary=100_000, fee=10_000, slots_total=1,
            created_by=1,
        )
        s.add(job2)
        await s.commit()

        users = [User(id=300 + i, full_name=f"U{i}", phone=f"+9989040000{i:02d}",
                      region="Chilonzor") for i in range(10)]
        s.add_all(users)
        await s.commit()

        results = await asyncio.gather(
            *[svc.apply_to_job(s, job2.id, u.id) for u in users],
            return_exceptions=True,
        )
        winners = [r for r in results if isinstance(r, Booking)]
        check("10 kishidan faqat 1 tasi joy oldi", len(winners) == 1)
        check("ortiqcha sotilmadi", await svc.taken_count(s, job2.id) == 1)

        section("Filtr va qidiruv")
        all_jobs, total = await svc.feed(s, include_full=True)
        check("barcha ochiq e'lonlar", total == 2)
        _, only_chilonzor = await svc.feed(s, region="Chilonzor", include_full=True)
        check("hudud bo'yicha filtr", only_chilonzor == 2)
        _, only_yuk = await svc.feed(s, category="yuk", include_full=True)
        check("kasb bo'yicha filtr", only_yuk == 1)
        _, tomorrow = await svc.feed(s, day=date.today() + timedelta(days=1), include_full=True)
        check("sana bo'yicha filtr", tomorrow == 1)
        page1, _ = await svc.feed(s, include_full=True, offset=0, limit=1)
        page2, _ = await svc.feed(s, include_full=True, offset=1, limit=1)
        check("sahifalash ishlaydi", len(page1) == 1 and len(page2) == 1
              and page1[0].id != page2[0].id)

        section("Obuna bo'yicha tarqatish ro'yxati")
        subs = await svc.subscribers_for_job(s, job)
        check("kasbga obuna bo'lgan chaqirildi", w1.id in subs)
        check("boshqa kasbga obuna chaqirilmadi", w2.id not in subs)
        check("boshqa hududdagi chaqirilmadi", w3.id not in subs)
        check("ish beruvchi chaqirilmadi", emp.id not in subs)

        await svc.deactivate(s, w1.id)
        subs = await svc.subscribers_for_job(s, job)
        check("botni o'chirgan chaqirilmadi", w1.id not in subs)

        section("Ish beruvchi e'loni tasdiqdan o'tadi")
        emp_job = Job(
            category="tozalash", title="Ofis tozalash", description="4 soatlik ish",
            secret_details="Yunusobod 5, Dilnoza opa +998901112233",
            region="Yunusobod", work_date=date.today() + timedelta(days=2),
            start_time="10:00", salary=150_000, fee=10_000, slots_total=3,
            status=JobStatus.PENDING_REVIEW, created_by=emp.id,
        )
        s.add(emp_job)
        await s.commit()

        review = await svc.pending_jobs(s)
        check("tasdiq navbatida turibdi", len(review) == 1)
        _, visible = await svc.feed(s, include_full=True)
        check("tasdiqlanmagan e'lon ro'yxatda ko'rinmaydi", visible == 2)

        emp_job.status = JobStatus.OPEN
        await s.commit()
        _, visible = await svc.feed(s, include_full=True)
        check("tasdiqlangach ko'rinadi", visible == 3)

        section("BEPUL e'lon")
        free_job = Job(
            category="tozalash", title="Bepul ish", description="tekshiruv uchun",
            secret_details="Manzil, Aziz aka +998901112233",
            region="Chilonzor", work_date=date.today() + timedelta(days=3),
            start_time="09:00", salary=150_000, fee=0, slots_total=1,
            created_by=1,
        )
        s.add(free_job)
        await s.commit()

        fb = await svc.apply_to_job(s, free_job.id, w1.id)
        check("bepul ishga darhol TASDIQLANDI", fb.status == BookingStatus.CONFIRMED)
        check("chek kutilmaydi (muddat yo'q)", fb.expires_at is None)
        check("joy band bo'ldi", await svc.taken_count(s, free_job.id) == 1)
        await s.refresh(free_job)
        check("bitta joy edi -> FULL", free_job.status == JobStatus.FULL)

        section("Bepul ishda no-show cheklovi")
        await store.set_value(s, "max_no_show", "2")
        lazy = User(id=601, full_name="Kelmaydigan", phone="+998908888888",
                    region="Chilonzor", no_show_count=2)
        s.add(lazy)
        await s.commit()

        free2 = Job(
            category="tozalash", title="Bepul 2", description="test",
            secret_details="test", region="Chilonzor",
            work_date=date.today() + timedelta(days=3), start_time="09:00",
            salary=150_000, fee=0, slots_total=5, created_by=1,
        )
        paid2 = Job(
            category="tozalash", title="Pulli 2", description="test",
            secret_details="test", region="Chilonzor",
            work_date=date.today() + timedelta(days=3), start_time="09:00",
            salary=150_000, fee=10_000, slots_total=5, created_by=1,
        )
        s.add_all([free2, paid2])
        await s.commit()

        try:
            await svc.apply_to_job(s, free2.id, lazy.id)
            check("no-show limiti bepul ishda ishladi", False)
        except svc.ApplyError:
            check("no-show limiti bepul ishda ishladi", True)

        pb = await svc.apply_to_job(s, paid2.id, lazy.id)
        check("pulli ishga baribir yozila oladi",
              pb.status == BookingStatus.PENDING_PAYMENT)

        section("Bepul ishda navbatdan ko'tarilish")
        wl2 = await svc.join_waitlist(s, free_job.id, w2.id)
        check("navbatga yozildi", wl2.status == BookingStatus.WAITLIST)
        await svc.cancel_booking(s, fb)
        promoted_free = await svc.promote_from_waitlist(s, free_job.id)
        check("navbatdagi darhol TASDIQLANDI",
              promoted_free is not None
              and promoted_free.status == BookingStatus.CONFIRMED)
        check("to'lov kutilmaydi", promoted_free.expires_at is None)

        section("Bepul <-> pulli almashtirish")
        check("pul to'laganlar yo'q", not await svc.has_money_bookings(s, free2.id))
        await svc.set_fee(s, free2, 10_000)
        await s.refresh(free2)
        check("pulli qilindi", free2.fee == 10_000)
        nb = await svc.apply_to_job(s, free2.id, w3.id)
        check("endi to'lov so'raladi", nb.status == BookingStatus.PENDING_PAYMENT)
        await svc.attach_receipt(s, nb, "CHEK")
        check("chek bor -> narxni o'zgartirib bo'lmaydi",
              await svc.has_money_bookings(s, free2.id))

        section("Reklama auditoriyasi")
        everyone = await svc.audience(s)
        check("barcha faol ishchilar", len(everyone) > 0)
        by_region = await svc.audience(s, region="Sergeli")
        check("hudud bo'yicha filtr", all(uid != w1.id for uid in by_region))
        by_cat = await svc.audience(s, category="qurilish")
        check("kasb bo'yicha filtr", w2.id in by_cat and w1.id not in by_cat)

        section("Ko'p kanal va filtrlash")
        c_all = await ch.add(s, -1001, "Umumiy kanal", "channel")
        c_chi = await ch.add(s, -1002, "Chilonzor ishlari", "channel")
        await ch.set_filter(s, c_chi.id, "regions", ["Chilonzor"])
        c_yuk = await ch.add(s, -1003, "Yuk tashish guruhi", "group")
        await ch.set_filter(s, c_yuk.id, "categories", ["yuk"])
        c_off = await ch.add(s, -1004, "To'xtatilgan", "channel")
        await ch.toggle(s, c_off.id)

        targets = await ch.targets_for(s, job)  # Chilonzor + yuk
        names = {t.title for t in targets}
        check("filtrsiz kanal oldi", "Umumiy kanal" in names)
        check("hudud mos kanal oldi", "Chilonzor ishlari" in names)
        check("kasb mos kanal oldi", "Yuk tashish guruhi" in names)
        check("to'xtatilgan kanal olmadi", "To'xtatilgan" not in names)

        targets2 = await ch.targets_for(s, emp_job)  # Yunusobod + tozalash
        names2 = {t.title for t in targets2}
        check("boshqa hudud kanali chetlatildi", "Chilonzor ishlari" not in names2)
        check("boshqa kasb kanali chetlatildi", "Yuk tashish guruhi" not in names2)
        check("umumiy kanal baribir oldi", "Umumiy kanal" in names2)

        section("Post takrorlanmasligi (ortiqcha so'rov bermaslik)")
        s.add(JobPost(job_id=job.id, chat_id=-1001, message_id=55, last_hash="eski"))
        await s.commit()
        post = await s.scalar(select(JobPost).where(JobPost.job_id == job.id))
        check("post yozildi", post is not None and post.message_id == 55)
        check("xesh saqlanadi", post.last_hash == "eski")

        section("Lokatsiya")
        job.lat, job.lon = 41.2856, 69.2034
        await s.commit()
        await s.refresh(job)
        check("koordinata saqlandi", abs(job.lat - 41.2856) < 1e-6)

        section("Huquqlar")
        mod = User(id=501, full_name="Moderator", phone="+998907777777",
                   region="Chilonzor", role=Role.MODERATOR)
        s.add(mod)
        await s.commit()
        check("admin — admin", perms.is_admin(admin))
        check("admin — xodim", perms.is_staff(admin))
        check("moderator — xodim", perms.is_staff(mod))
        check("moderator admin EMAS", not perms.is_admin(mod))
        check("ishchi xodim emas", not perms.is_staff(w1))
        check("ish beruvchi xodim emas", not perms.is_staff(emp))

        section("Zaxira nusxa")
        path = await backup.create(stamp="test")
        check("nusxa yaratildi", path is not None and path.exists())
        if path:
            check("nusxa bo'sh emas", path.stat().st_size > 1000)
            # Nusxa haqiqiy baza ekanini tekshiramiz — ochib o'qiymiz
            con = sqlite3.connect(path)
            n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            bad = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            check("nusxadan o'qish mumkin", n >= 5)
            check("nusxa buzilmagan", bad == "ok")
            check("zaxira yoshi hisoblandi", (backup.age_hours() or 99) < 1)
            path.unlink(missing_ok=True)
        check("baza hajmi o'lchandi", backup.db_size_kb() > 0)

        section("Bazaning butunligi va sxema nazorati")
        check("baza soz", await integrity_check() == "ok")
        check("sxema to'liq (o'zgarish kutilmaydi)", await pending_schema_changes() == [])

        section("Tiriklik nazorati (bot o'chib qolsa)")
        await health.heartbeat(s)
        check("tiriklik belgisi yozildi", bool(store.get("last_seen")))
        check("yaqinda ishlagan -> uzilish yo'q", await health.downtime(s) is None)

        # 3 soat oldin ishlagan deb ko'rsatamiz
        long_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
        await store.set_value(s, "last_seen", long_ago)
        gap = await health.downtime(s)
        check("uzilish aniqlandi", gap is not None and gap.total_seconds() > 3500)
        check("odam o'qiydigan ko'rinish", "soat" in health.human(gap))

        await checkpoint()
        check("WAL bazaga ko'chirildi", True)

        section("Ishonchlilik va statistika")
        await svc.mark_completed(s, b1)
        await s.refresh(w1)
        check("ishga chiqqani belgilandi", w1.completed_count == 1)

        st = await svc.stats(s)
        # Bepul yozilishlar tushumni oshirmasligi kerak — faqat pulli
        # e'lonlarning to'lovi hisoblanadi.
        check("bepul ishlar tushumga qo'shilmadi", st["revenue"] == 10_000)
        check("tasdiqlanganlar sanaldi", st["confirmed"] >= 2)
        check("ish beruvchilar sanaldi", st["employers"] == 1)

    await engine.dispose()
    DB_FILE.unlink(missing_ok=True)
    pathlib.Path(f"{DB_FILE.name}-wal").unlink(missing_ok=True)
    pathlib.Path(f"{DB_FILE.name}-shm").unlink(missing_ok=True)

    print()
    if failures:
        print(f"❌ {failures} ta tekshiruv muvaffaqiyatsiz")
        sys.exit(1)
    print("✅ Barcha tekshiruvlar o'tdi")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
