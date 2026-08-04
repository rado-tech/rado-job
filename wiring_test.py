"""Yig'ilish testi: bot Telegramsiz to'g'ri yig'iladimi?

Ishga tushirish:
    .venv\\Scripts\\python.exe wiring_test.py

smoke_test.py biznes QOIDALARINI tekshiradi. Bu esa boshqa xatolar
sinfini ushlaydi:
  * import xatolari, aylanma importlar
  * handler'lar routerga to'g'ri yig'ilishi
  * tugmalar yasalishi (callback ma'lumoti 64 baytdan oshmasligi —
    Telegram cheklovi, oshsa tugma umuman ishlamaydi)
  * maxfiy ma'lumot faqat kerakli joyda chiqishi
  * sana/vaqt/raqam parserlari

Bu tekshiruvlar sekundlar ichida o'tadi va botni ochmasdan katta
qismini himoya qiladi.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Sozlamalar import paytida o'qiladi — namuna qiymatlar beramiz.
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("DATA_DIR", ".")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import date  # noqa: E402

from aiogram import Dispatcher  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402

from bot import keyboards as kb  # noqa: E402
from bot.callbacks import (  # noqa: E402
    AdminJobCB,
    AttendCB,
    ChanCB,
    ChatCB,
    FeedCB,
    JobCB,
    JobModCB,
    ModCB,
    PickCB,
    ReportCB,
    SetCB,
    StaffCB,
    WorkerCB,
)
from bot.db.models import Channel, Job, JobStatus, Role, User  # noqa: E402
from bot.handlers import build_router  # noqa: E402
from bot.middlewares import (  # noqa: E402
    DbSessionMiddleware,
    PrivateOnlyMiddleware,
    ThrottleMiddleware,
    UserMiddleware,
)
from bot import texts as texts_mod  # noqa: E402
from bot.utils import clean, local_today, parse_date, parse_int, parse_time  # noqa: E402

failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global failures
    print(("  ✓" if cond else "  ✗") + f" {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures += 1


def count_handlers(router, kind: str) -> int:
    total = len(getattr(router, kind).handlers)
    for sub in router.sub_routers:
        total += count_handlers(sub, kind)
    return total


print("\n── Router va middleware")

dp = Dispatcher(storage=MemoryStorage())
for observer in (dp.message, dp.callback_query):
    observer.outer_middleware(ThrottleMiddleware())
    observer.outer_middleware(DbSessionMiddleware())
    observer.outer_middleware(UserMiddleware())
    observer.outer_middleware(PrivateOnlyMiddleware())
dp.my_chat_member.outer_middleware(DbSessionMiddleware())

root = build_router()
dp.include_router(root)

messages = count_handlers(root, "message")
callbacks = count_handlers(root, "callback_query")
print(f"  message handler: {messages}")
print(f"  callback handler: {callbacks}")
check("message handler'lar yig'ildi", messages > 40)
check("callback handler'lar yig'ildi", callbacks > 30)


print("\n── Tugmalar yasaladi")

job = Job(
    id=1, category="yuk", title="Test ish", description="tavsif",
    secret_details="MAXFIY MANZIL", region="Chilonzor", work_date=local_today(),
    start_time="08:00", salary=200_000, fee=10_000, slots_total=5,
    status=JobStatus.OPEN, created_by=1,
)
free_job = Job(
    id=2, category="yuk", title="Bepul ish", description="tavsif",
    secret_details="MAXFIY", region="Chilonzor", work_date=local_today(),
    start_time="08:00", salary=200_000, fee=0, slots_total=5,
    status=JobStatus.OPEN, created_by=1,
)
channel = Channel(id=1, chat_id=-100123, title="Kanal", kind="channel")
worker = User(id=2, full_name="W", role=Role.WORKER, region="Chilonzor", phone="+998")
employer = User(id=3, full_name="E", role=Role.EMPLOYER, region="Chilonzor", phone="+998")
moderator = User(id=4, full_name="M", role=Role.MODERATOR, region="Chilonzor", phone="+998")
admin = User(id=5, full_name="A", role=Role.ADMIN, region="Chilonzor", phone="+998")

try:
    kb.role_kb()
    kb.regions_kb("rregion")
    kb.regions_kb("freg", with_all=True)
    kb.categories_kb("njcat")
    kb.categories_multi_kb(["yuk"])
    kb.multi_pick_kb("chreg", kb.region_options(), ["Chilonzor"])
    kb.multi_pick_kb("chcat", kb.category_options(), ["yuk"])
    kb.days_kb()
    kb.dates_kb("njdate")
    kb.times_kb()
    kb.salaries_kb()
    kb.slots_kb()
    kb.fee_kb(10_000)
    kb.skip_kb("njloc")
    kb.preview_kb(is_admin=True)
    kb.preview_kb(is_admin=False)
    kb.feed_kb([(job, 2)], page=0, total=20, per_page=8, region="Chilonzor", category="", day="")
    kb.job_view_kb(job, taken=2, mine=False, can_wait=True)
    kb.job_view_kb(job, taken=2, mine=False, can_wait=True, credits=3)
    kb.job_view_kb(job, taken=5, mine=False, can_wait=True)
    kb.job_view_kb(job, taken=2, mine=True, can_wait=True)
    kb.job_view_kb(job, taken=2, mine=True, can_wait=False, confirmed=True)
    kb.job_view_kb(free_job, taken=0, mine=False, can_wait=True)
    kb.cancel_confirm_kb(1)
    kb.attendance_kb(1)
    kb.report_kb(1)
    kb.channel_post_kb("mybot", job, open_=True)
    kb.channel_post_kb("mybot", job, open_=False)
    kb.moderation_kb(1)
    kb.job_review_kb(1)
    kb.admin_job_kb(job)
    kb.admin_job_kb(free_job)
    kb.admin_job_kb(job, owner_view=True)
    kb.jobs_list_kb([job])
    kb.worker_actions_kb(1)
    kb.settings_kb(free_mode=True)
    kb.settings_kb(free_mode=False)
    kb.channels_kb([channel])
    kb.channel_kb(channel)
    kb.staff_kb([moderator])
    for u in (worker, employer, moderator, admin):
        kb.main_menu(u)
    kb.admin_menu(admin)
    kb.admin_menu(moderator)
    kb.phone_kb()
    ok, detail = True, ""
except Exception as e:  # noqa: BLE001
    ok, detail = False, f"{type(e).__name__}: {e}"
check("barcha klaviaturalar yasaldi", ok, detail)


print("\n── Callback ma'lumoti Telegram chegarasida (64 bayt)")

samples = {
    "JobCB": JobCB(action="cancelyes", job_id=999_999).pack(),
    "FeedCB": FeedCB(action="filter", value="category", page=99).pack(),
    "ModCB": ModCB(action="ok", booking_id=999_999).pack(),
    "JobModCB": JobModCB(action="ok", job_id=999_999).pack(),
    "AdminJobCB": AdminJobCB(action="workers", job_id=999_999).pack(),
    "AttendCB": AttendCB(action="yes", booking_id=999_999).pack(),
    "ReportCB": ReportCB(action="answer", report_id=999_999).pack(),
    "WorkerCB": WorkerCB(action="noshow", booking_id=999_999).pack(),
    "ChanCB": ChanCB(action="regions", channel_id=999).pack(),
    "ChatCB": ChatCB(kind="moderation", chat_id=-1_009_999_999_999).pack(),
    "StaffCB": StaffCB(action="demote", user_id=9_999_999_999).pack(),
    "SetCB": SetCB(action="testchannel").pack(),
    "PickCB": PickCB(field="njreg", value="Mirzo Ulug'bek").pack(),
}
too_long = {name: len(v.encode()) for name, v in samples.items() if len(v.encode()) > 64}
check("hammasi 64 baytdan kichik", not too_long, str(too_long) if too_long else "")


print("\n── Maxfiylik")

check("sir ma'lumot secret=True da chiqadi", "MAXFIY MANZIL" in texts_mod.job_card(job, 2, secret=True))
check("sir ma'lumot oddiy kartada YO'Q", "MAXFIY MANZIL" not in texts_mod.job_card(job, 2))
check("kanal postida sir YO'Q", "MAXFIY MANZIL" not in texts_mod.job_card(job, 2, waitlist=3))
check("bepul e'lon belgilanadi", "BEPUL" in texts_mod.job_card(free_job, 0))
check("pulli e'londa summa ko'rinadi", "10 000" in texts_mod.job_card(job, 0))


print("\n── Ko'p tillilik")

from bot.i18n import LANGS, current_lang, set_lang  # noqa: E402

set_lang("uz")
uz_card = texts_mod.job_card(job, 2)
uz_money = texts_mod.money(150_000)
uz_status = texts_mod.BOOKING_STATUS_LABEL[__import__(
    "bot.db.models", fromlist=["BookingStatus"]).BookingStatus.CONFIRMED]

set_lang("ru")
ru_card = texts_mod.job_card(job, 2)
ru_money = texts_mod.money(150_000)
ru_status = texts_mod.BOOKING_STATUS_LABEL[__import__(
    "bot.db.models", fromlist=["BookingStatus"]).BookingStatus.CONFIRMED]
ru_admin = texts_mod.ADMIN_WELCOME  # tarjimasi yo'q -> o'zbekchaga qaytadi

check("tillar ro'yxati", set(LANGS) == {"uz", "ru"})
check("o'zbekcha karta", "Bo'sh joy" in uz_card and "so'm" in uz_money)
check("ruscha karta", "Свободных мест" in ru_card and "сум" in ru_money)
check("ikkalasi farq qiladi", uz_card != ru_card)
check("holat yorlig'i tarjima qilindi", "Tasdiqlangan" in uz_status and "Подтверждено" in ru_status)
check("tarjimasi yo'q matn o'zbekchaga qaytdi", "Admin panel" in ru_admin)
check("maxfiylik ruschada ham saqlanadi",
      "MAXFIY MANZIL" not in ru_card and "MAXFIY MANZIL" in texts_mod.job_card(job, 2, secret=True))

# Tugma matnlari ikki tilda va filtrlar ikkalasini ham ushlaydi
set_lang("ru")
ru_btn = kb.label("find")
set_lang("uz")
uz_btn = kb.label("find")
check("tugma matni tilga qarab o'zgaradi", ru_btn != uz_btn)
check("filtr ikkala variantni ushlaydi",
      {uz_btn, ru_btn} == kb.variants("find"))

set_lang("uz")

# Regressiya himoyasi: texts dan to'g'ridan-to'g'ri import qilish tarjimani
# import paytida "qotirib" qo'yadi — ya'ni ruscha foydalanuvchi o'zbekcha
# matn ko'radi. Buni odam ko'zi bilan payqash deyarli imkonsiz.
import pathlib  # noqa: E402

bad = []
for path in pathlib.Path("bot").rglob("*.py"):
    if "locales" in path.parts or path.name == "texts.py":
        continue
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("from bot.texts import"):
            bad.append(f"{path}:{i}")
check("texts dan to'g'ridan-to'g'ri import yo'q", not bad, ", ".join(bad))


print("\n── Parserlar")

check("parse_int '200 000'", parse_int("200 000") == 200_000)
check("parse_int matn -> None", parse_int("abc") is None)
check("parse_date 'bugun'", parse_date("bugun") == local_today())
check("parse_date '05.08.2026'", parse_date("05.08.2026") == date(2026, 8, 5))
check("parse_date axlat -> None", parse_date("qwerty") is None)
check("parse_time '8:00' -> '08:00'", parse_time("8:00") == "08:00")
check("parse_time '25:00' -> None", parse_time("25:00") is None)
check("clean HTML ekranlaydi", clean("<b>hack</b>") == "&lt;b&gt;hack&lt;/b&gt;")


print()
if failures:
    print(f"❌ {failures} ta tekshiruv muvaffaqiyatsiz")
    sys.exit(1)
print("✅ Yig'ilish testi o'tdi")
