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
from bot.config import TZ  # noqa: E402
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
from bot import texts  # noqa: E402
from bot.services import reports  # noqa: E402
from bot.services import settings_store as store  # noqa: E402
from bot.utils import local_today  # noqa: E402

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
            region="Chilonzor", work_date=local_today() + timedelta(days=1),
            start_time="08:00", salary=200_000, fee=10_000, slots_total=2,
            created_by=1,
        )
        s.add(job)
        await s.commit()

        section("Vaqt zonasi (server UTC da ishlaydi)")
        # Railway va aksariyat VPS UTC da ishlaydi. Toshkentda soat 01:30
        # bo'lganda UTC hali kechagi kun — agar kod server sanasiga tayansa,
        # e'lonlar bir kun kech yopiladi va «Bugun/Ertaga» xato chiqadi.
        utc_kech = datetime(2026, 8, 4, 20, 30, tzinfo=timezone.utc)
        check("UTC va Toshkent sanasi farq qiladi",
              utc_kech.date() == date(2026, 8, 4)
              and utc_kech.astimezone(TZ).date() == date(2026, 8, 5))
        check("local_today() Toshkent bo'yicha",
              local_today() == datetime.now(TZ).date())

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
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=1),
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
        # Ertaga ikkita ish bor: "Omborga yuk tashish" va "Bitta joy"
        _, tomorrow = await svc.feed(s, day=local_today() + timedelta(days=1), include_full=True)
        check("sana bo'yicha filtr", tomorrow == 2)
        _, empty_day = await svc.feed(s, day=local_today() + timedelta(days=30), include_full=True)
        check("bo'sh kun -> 0", empty_day == 0)
        page1, _ = await svc.feed(s, include_full=True, offset=0, limit=1)
        page2, _ = await svc.feed(s, include_full=True, offset=1, limit=1)
        check("sahifalash ishlaydi", len(page1) == 1 and len(page2) == 1
              and page1[0].id != page2[0].id)

        section("Boshlangan ishga yozilib bo'lmaydi")
        # Bugun ertalab 00:01 da boshlangan ish — hozir albatta o'tib ketgan
        started = Job(
            category="yuk", title="Boshlangan ish", description="test",
            secret_details="test", region="Chilonzor", work_date=local_today(),
            start_time="00:01", salary=100_000, fee=10_000, slots_total=5,
            created_by=1,
        )
        s.add(started)
        await s.commit()

        _, total_before = await svc.feed(s, include_full=True)
        check("boshlangan ish ro'yxatda ko'rinmaydi",
              all(j.id != started.id for j in (await svc.feed(s, include_full=True))[0]))
        try:
            await svc.apply_to_job(s, started.id, w3.id)
            check("boshlangan ishga yozib bo'lmaydi", False)
        except svc.ApplyError as e:
            check("boshlangan ishga yozib bo'lmaydi", "boshlangan" in str(e))
        try:
            await svc.join_waitlist(s, started.id, w3.id)
            check("boshlangan ishga navbatga ham yozib bo'lmaydi", False)
        except svc.ApplyError:
            check("boshlangan ishga navbatga ham yozib bo'lmaydi", True)

        closed = await svc.close_past_jobs(s)
        check("boshlangan ish avtomat yopildi",
              any(j.id == started.id for j in closed))
        await s.refresh(started)
        check("holati CLOSED", started.status == JobStatus.CLOSED)

        # Kelajakdagi ishlar yopilmadi
        await s.refresh(job)
        check("kelajakdagi ish yopilmadi", job.status != JobStatus.CLOSED)

        section("Chek holatsiz ham qabul qilinadi (bot restart)")
        restart_job = Job(
            category="yuk", title="Restart testi", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=2),
            start_time="08:00", salary=100_000, fee=10_000, slots_total=3,
            created_by=1,
        )
        s.add(restart_job)
        await s.commit()
        rb = await svc.apply_to_job(s, restart_job.id, w2.id)
        check("to'lov kutilyapti", rb.status == BookingStatus.PENDING_PAYMENT)

        # Bot qayta ishga tushdi -> FSM holati yo'q. Chek bazadan topilishi kerak.
        found = await svc.pending_payment_booking(s, w2.id)
        check("holatsiz ariza bazadan topildi", found is not None and found.id == rb.id)
        check("job bog'lanishi yuklangan", found.job is not None)

        await svc.attach_receipt(s, found, "CHEK_RESTART")
        check("chek biriktirildi", rb.status == BookingStatus.RECEIPT_SENT)
        check("chekdan keyin qayta topilmaydi",
              await svc.pending_payment_booking(s, w2.id) is None)

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
        _, before_emp = await svc.feed(s, include_full=True)
        emp_job = Job(
            category="tozalash", title="Ofis tozalash", description="4 soatlik ish",
            secret_details="Yunusobod 5, Dilnoza opa +998901112233",
            region="Yunusobod", work_date=local_today() + timedelta(days=2),
            start_time="10:00", salary=150_000, fee=10_000, slots_total=3,
            status=JobStatus.PENDING_REVIEW, created_by=emp.id,
        )
        s.add(emp_job)
        await s.commit()

        review = await svc.pending_jobs(s)
        check("tasdiq navbatida turibdi", len(review) == 1)

        # Aniq songa emas, FARQqa qaraymiz — testga yangi e'lon qo'shilsa
        # ham buzilmaydi.
        _, visible = await svc.feed(s, include_full=True)
        check("tasdiqlanmagan e'lon ro'yxatda ko'rinmaydi", visible == before_emp)

        emp_job.status = JobStatus.OPEN
        await s.commit()
        _, visible = await svc.feed(s, include_full=True)
        check("tasdiqlangach ko'rinadi", visible == before_emp + 1)

        section("BEPUL e'lon")
        free_job = Job(
            category="tozalash", title="Bepul ish", description="tekshiruv uchun",
            secret_details="Manzil, Aziz aka +998901112233",
            region="Chilonzor", work_date=local_today() + timedelta(days=3),
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
            work_date=local_today() + timedelta(days=3), start_time="09:00",
            salary=150_000, fee=0, slots_total=5, created_by=1,
        )
        paid2 = Job(
            category="tozalash", title="Pulli 2", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=3), start_time="09:00",
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

        section("Eslatmalar")
        await store.set_value(s, "remind_evening_hour", "0")   # doim yuborilsin
        await store.set_value(s, "remind_before_minutes", "120")

        tomorrow_job = Job(
            category="yuk", title="Ertangi ish", description="eslatma testi",
            secret_details="Manzil", region="Chilonzor",
            work_date=local_today() + timedelta(days=1), start_time="08:00",
            salary=200_000, fee=0, slots_total=5, created_by=1,
        )
        s.add(tomorrow_job)
        await s.commit()
        tb = await svc.apply_to_job(s, tomorrow_job.id, w3.id)
        check("ertangi ishga yozildi", tb.status == BookingStatus.CONFIRMED)

        evening = await svc.bookings_needing_reminder(s, "evening")
        check("kechqurungi eslatma navbatga tushdi",
              any(b.id == tb.id for b in evening))
        await svc.mark_reminded(s, evening, "evening")
        again = await svc.bookings_needing_reminder(s, "evening")
        check("ikkinchi marta yuborilmaydi", not any(b.id == tb.id for b in again))

        soon = await svc.bookings_needing_reminder(s, "soon")
        check("hali erta -> tez orada eslatmasi yo'q",
              not any(b.id == tb.id for b in soon))

        # Ishni 1 soatdan keyinga surib qo'yamiz
        target = datetime.now(TZ) + timedelta(hours=1)
        tomorrow_job.work_date = target.date()
        tomorrow_job.start_time = target.strftime("%H:%M")
        await s.commit()
        soon = await svc.bookings_needing_reminder(s, "soon")
        check("1 soat qolganda eslatma navbatga tushdi",
              any(b.id == tb.id for b in soon))

        section("Bekor qilish oynasi")
        await store.set_value(s, "cancel_window_minutes", "180")
        check("1 soat qolgan -> kech bekor qilish",
              svc.is_late_cancel(tomorrow_job, tb))

        far_job = Job(
            category="yuk", title="Uzoq ish", description="test",
            secret_details="Manzil", region="Chilonzor",
            work_date=local_today() + timedelta(days=5), start_time="08:00",
            salary=200_000, fee=0, slots_total=5, created_by=1,
        )
        s.add(far_job)
        await s.commit()
        fb2 = await svc.apply_to_job(s, far_job.id, w3.id)
        check("5 kun qolgan -> oddiy bekor qilish",
              not svc.is_late_cancel(far_job, fb2))

        await svc.cancel_booking(s, fb2, late=False)
        await s.refresh(w3)
        check("o'z vaqtida bekor -> jazo yo'q", w3.no_show_count == 0)
        check("oddiy bekor -> CANCELLED", fb2.status == BookingStatus.CANCELLED)

        before = w3.no_show_count
        await svc.cancel_booking(s, tb, late=True)
        await s.refresh(w3)
        check("kech bekor -> LATE_CANCEL", tb.status == BookingStatus.LATE_CANCEL)
        check("kech bekor -> ko'rsatkichga yozildi", w3.no_show_count == before + 1)
        check("kech bekorda joy BO'SHADI",
              await svc.taken_count(s, tomorrow_job.id) == 0)

        section("Davomat (ishga chiqdimi)")
        await store.set_value(s, "attendance_after_hours", "5")
        past_job = Job(
            category="yuk", title="Kechagi ish", description="test",
            secret_details="Manzil", region="Chilonzor",
            work_date=local_today() - timedelta(days=1), start_time="08:00",
            salary=200_000, fee=0, slots_total=5, created_by=1,
        )
        s.add(past_job)
        await s.commit()
        pb2 = Booking(job_id=past_job.id, user_id=w2.id, status=BookingStatus.CONFIRMED)
        s.add(pb2)
        await s.commit()

        need = await svc.jobs_needing_attendance(s)
        check("tugagan ish so'rov navbatiga tushdi",
              any(j.id == past_job.id for j in need))
        check("kelajakdagi ish tushmadi", not any(j.id == far_job.id for j in need))

        to_ask = await svc.bookings_to_ask(s, past_job.id)
        check("so'raladigan ariza topildi", len(to_ask) == 1)

        w2_done_before = w2.completed_count
        await svc.mark_completed(s, pb2)
        await s.refresh(w2)
        check("ishga chiqqan belgilandi", pb2.status == BookingStatus.COMPLETED)
        check("ko'rsatkich oshdi", w2.completed_count == w2_done_before + 1)

        await svc.mark_completed(s, pb2)
        await s.refresh(w2)
        check("ikki marta sanalmaydi", w2.completed_count == w2_done_before + 1)

        w2_ns_before = w2.no_show_count
        await svc.mark_no_show(s, pb2)
        await s.refresh(w2)
        check("qaroni o'zgartirish ko'rsatkichni to'g'riladi",
              w2.completed_count == w2_done_before and w2.no_show_count == w2_ns_before + 1)

        section("Referal")
        await store.set_value(s, "referral_reward", "1")
        inviter = User(id=701, full_name="Chaqiruvchi", phone="+998901010101",
                       region="Chilonzor")
        friend = User(id=702, full_name="Do'st", phone="+998902020202",
                      region="Chilonzor")
        s.add_all([inviter, friend])
        await s.commit()

        check("o'zini o'zi chaqira olmaydi",
              not await svc.register_referral(s, inviter, inviter.id))
        check("referal yozildi", await svc.register_referral(s, friend, inviter.id))
        await s.refresh(inviter)
        check("chaqirganlar soni oshdi", inviter.invited_count == 1)
        check("mukofot hali yo'q", inviter.free_credits == 0)
        check("ikkinchi marta yozilmaydi",
              not await svc.register_referral(s, friend, inviter.id))

        ref_job = Job(
            category="yuk", title="Referal ishi", description="test",
            secret_details="Manzil", region="Chilonzor",
            work_date=local_today() + timedelta(days=2), start_time="08:00",
            salary=200_000, fee=0, slots_total=5, created_by=1,
        )
        s.add(ref_job)
        await s.commit()
        await svc.apply_to_job(s, ref_job.id, friend.id)

        result = await svc.reward_referrer(s, friend.id)
        await s.refresh(inviter)
        check("birinchi yozilishdan keyin mukofot berildi",
              result is not None and inviter.free_credits == 1)
        check("ikkinchi marta mukofot yo'q",
              await svc.reward_referrer(s, friend.id) is None)

        section("Bonus bilan bepul yozilish")
        paid_job = Job(
            category="yuk", title="Pulli ish", description="test",
            secret_details="Manzil", region="Chilonzor",
            work_date=local_today() + timedelta(days=2), start_time="08:00",
            salary=200_000, fee=15_000, slots_total=5, created_by=1,
        )
        s.add(paid_job)
        await s.commit()

        cb = await svc.apply_to_job(s, paid_job.id, inviter.id, use_credit=True)
        await s.refresh(inviter)
        check("bonus bilan darhol tasdiqlandi", cb.status == BookingStatus.CONFIRMED)
        check("bonus sarflandi", inviter.free_credits == 0)
        check("bonus belgilandi", cb.used_credit is True)

        paid_job2 = Job(
            category="yuk", title="Pulli ish 2", description="test",
            secret_details="Manzil", region="Chilonzor",
            work_date=local_today() + timedelta(days=2), start_time="08:00",
            salary=200_000, fee=15_000, slots_total=5, created_by=1,
        )
        s.add(paid_job2)
        await s.commit()
        try:
            await svc.apply_to_job(s, paid_job2.id, inviter.id, use_credit=True)
            check("bonus tugagach ishlatib bo'lmaydi", False)
        except svc.ApplyError:
            check("bonus tugagach ishlatib bo'lmaydi", True)

        # Bepul e'longa bonus sarflanmaydi — shunchaki e'tiborsiz qoldiriladi
        free_apply = await svc.apply_to_job(s, ref_job.id, w2.id, use_credit=True)
        check("bepul ishga bonus sarflanmaydi", free_apply.used_credit is False)

        st_mid = await svc.stats(s)
        check("bonusli yozilish tushumga qo'shilmadi", st_mid["revenue"] == 10_000)

        section("Shikoyat")
        rep = await reports.create(s, w1.id, "Manzilda hech kim yo'q edi", ref_job.id)
        check("murojaat yaratildi", rep.id > 0)
        check("ochiq murojaatlar sanaldi", await reports.open_count(s) == 1)
        loaded = await reports.get(s, rep.id)
        check("muallif va e'lon yuklandi",
              loaded.user.id == w1.id and loaded.job.id == ref_job.id)
        await reports.answer(s, loaded, admin.id, "Uzr, tekshiramiz")
        check("javob yozildi", loaded.status.value == "ANSWERED")
        check("javobdan keyin ochiq emas", await reports.open_count(s) == 0)

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

        section("Takroriy chekni ushlash")
        dup_job = Job(
            category="yuk", title="Chek testi", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=4), start_time="08:00",
            salary=100_000, fee=10_000, slots_total=5, created_by=1,
        )
        s.add(dup_job)
        await s.commit()

        d1 = await svc.apply_to_job(s, paid_job.id, w1.id)
        await svc.attach_receipt(s, d1, "FILE_A", "UNIQ_AAA")
        await svc.confirm_booking(s, d1, admin.id)

        d2 = await svc.apply_to_job(s, dup_job.id, w1.id)
        await svc.attach_receipt(s, d2, "FILE_B", "UNIQ_AAA")  # AYNAN o'sha rasm

        found = await svc.find_duplicate_receipt(s, "UNIQ_AAA", d2.id)
        check("takroriy chek topildi", found is not None and found.id == d1.id)
        check("bog'lanishlar yuklangan", found.user is not None and found.job is not None)

        d3 = await svc.apply_to_job(s, dup_job.id, w2.id)
        await svc.attach_receipt(s, d3, "FILE_C", "UNIQ_BBB")
        check("boshqa chek — ogohlantirish yo'q",
              await svc.find_duplicate_receipt(s, "UNIQ_BBB", d3.id) is None)
        check("belgisiz chek — ogohlantirish yo'q",
              await svc.find_duplicate_receipt(s, None, d3.id) is None)

        section("Qarorni qaytarish")
        # Tasdiqlangandan keyin
        await svc.undo_decision(s, d1)
        check("tasdiq qaytarildi -> tekshiruvga", d1.status == BookingStatus.RECEIPT_SENT)
        check("qaror izlari tozalandi", d1.decided_at is None and d1.decided_by is None)

        # Rad etilgandan keyin
        await svc.reject_booking(s, d3, admin.id, "Xato bosildi")
        check("rad etildi", d3.status == BookingStatus.REJECTED)
        await svc.undo_decision(s, d3)
        check("rad etish qaytarildi", d3.status == BookingStatus.RECEIPT_SENT)
        check("sabab tozalandi", d3.reject_reason is None)

        # Joy to'lgan bo'lsa tiklab bo'lmaydi
        tight = Job(
            category="yuk", title="Bitta joyli", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=4), start_time="08:00",
            salary=100_000, fee=10_000, slots_total=1, created_by=1,
        )
        s.add(tight)
        await s.commit()
        t1 = await svc.apply_to_job(s, tight.id, w1.id)
        await svc.attach_receipt(s, t1, "F1", "U1")
        await svc.reject_booking(s, t1, admin.id, None)      # joy bo'shadi
        t2 = await svc.apply_to_job(s, tight.id, w2.id)      # boshqa odam egalladi
        await svc.attach_receipt(s, t2, "F2", "U2")
        await svc.confirm_booking(s, t2, admin.id)
        try:
            await svc.undo_decision(s, t1)
            check("to'lgan joyga qaytarib bo'lmaydi", False)
        except svc.UndoError as e:
            check("to'lgan joyga qaytarib bo'lmaydi", "to'lgan" in str(e))

        # Boshlangan ishga qaytarib bo'lmaydi
        try:
            await svc.undo_decision(s, pb2)
            check("boshlangan ishda qaytarib bo'lmaydi", False)
        except svc.UndoError:
            check("boshlangan ishda qaytarib bo'lmaydi", True)

        section("Kanal atributsiyasi")
        att_job = Job(
            category="yuk", title="Manba testi", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=5), start_time="08:00",
            salary=100_000, fee=0, slots_total=10, created_by=1,
        )
        s.add(att_job)
        await s.commit()

        a1 = await svc.apply_to_job(s, att_job.id, w1.id)
        a1.source_channel_id = c_chi.id
        a2 = await svc.apply_to_job(s, att_job.id, w2.id)
        a2.source_channel_id = c_chi.id
        a3 = await svc.apply_to_job(s, att_job.id, w3.id)
        a3.source_channel_id = c_all.id
        await s.commit()

        rows = await svc.channel_attribution(s)
        by_channel = {cid: n for cid, n in rows}
        check("kanal bo'yicha sanaldi", by_channel.get(c_chi.id) == 2)
        check("ikkinchi kanal sanaldi", by_channel.get(c_all.id) == 1)
        check("manbasizlar ham sanaldi", by_channel.get(None, 0) > 0)
        check("ko'p olib kelgani birinchi", rows[0][1] >= rows[-1][1])

        section("Zaxira kanali sozlamasi")
        check("standart holatda ulanmagan", store.backup_chat() is None)
        await store.set_value(s, "backup_chat_id", "-1001112223334")
        await store.set_value(s, "backup_chat_title", "Zaxira arxivi")
        check("ulangandan keyin o'qildi", store.backup_chat() == -1001112223334)
        check("nomi saqlandi", store.get("backup_chat_title") == "Zaxira arxivi")
        await store.set_value(s, "backup_chat_id", "")
        check("uzilgandan keyin bo'sh", store.backup_chat() is None)

        section("Kunlik hisobot")
        since = datetime.now(timezone.utc) - timedelta(days=1)
        rep = await svc.daily_summary(s, since)
        check("yangi foydalanuvchilar sanaldi", rep["new_users"] > 0)
        check("yangi e'lonlar sanaldi", rep["new_jobs"] > 0)
        check("tasdiqlanganlar sanaldi", rep["confirmed"] > 0)
        check("tekshiruvdagi cheklar sanaldi", rep["waiting"] >= 0)
        check("ertangi bo'sh joylar ro'yxati", isinstance(rep["gaps"], list))

        old_since = datetime.now(timezone.utc) + timedelta(days=1)
        rep_empty = await svc.daily_summary(s, old_since)
        check("kelajakdagi davr -> 0", rep_empty["new_users"] == 0)

        text = texts.daily_report(rep, "04.08.2026")
        check("hisobot matni yasaldi", "Kunlik hisobot" in text and len(text) > 100)
        check("chiqish darajasi ko'rsatildi", "%" in text or "—" in text)

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

        # Tushum hisobi: aniq songa emas, FARQqa qaraymiz — testga yangi
        # ariza qo'shilganda buzilmaydi.
        rev_before = (await svc.stats(s))["revenue"]

        # 1) Bepul e'lon — tushum oshmasligi kerak
        free_rev = Job(
            category="yuk", title="Bepul (tushum testi)", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=6), start_time="08:00",
            salary=100_000, fee=0, slots_total=5, created_by=1,
        )
        s.add(free_rev)
        await s.commit()
        await svc.apply_to_job(s, free_rev.id, w1.id)
        check("bepul yozilish tushumni oshirmadi",
              (await svc.stats(s))["revenue"] == rev_before)

        # 2) Bonus bilan — ham oshmasligi kerak
        paid_rev = Job(
            category="yuk", title="Pulli (tushum testi)", description="test",
            secret_details="test", region="Chilonzor",
            work_date=local_today() + timedelta(days=6), start_time="08:00",
            salary=100_000, fee=25_000, slots_total=5, created_by=1,
        )
        s.add(paid_rev)
        await s.commit()
        w2.free_credits = 1
        await s.commit()
        await svc.apply_to_job(s, paid_rev.id, w2.id, use_credit=True)
        check("bonus bilan yozilish tushumni oshirmadi",
              (await svc.stats(s))["revenue"] == rev_before)

        # 3) Haqiqiy to'lov — aynan e'lon narxicha oshishi kerak
        real = await svc.apply_to_job(s, paid_rev.id, w3.id)
        await svc.attach_receipt(s, real, "F_REV", "U_REV")
        await svc.confirm_booking(s, real, admin.id)
        check("haqiqiy to'lov tushumga qo'shildi",
              (await svc.stats(s))["revenue"] == rev_before + 25_000)

        st = await svc.stats(s)
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
