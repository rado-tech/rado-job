"""Barcha tugmalar.

Reply-klaviatura (pastdagi doimiy tugmalar) — asosiy navigatsiya.
Inline-klaviatura (xabar ostidagi tugmalar) — aniq bir obyekt ustidagi amal.
"""

from __future__ import annotations

from datetime import date, timedelta

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.callbacks import (
    AdminJobCB,
    AttendCB,
    ChanCB,
    EditCB,
    FeedCB,
    JobCB,
    JobModCB,
    ModCB,
    NavCB,
    PickCB,
    ReportCB,
    SetCB,
    StaffCB,
    WorkerCB,
)
from bot.config import (
    CATEGORIES,
    CATEGORY_NAMES,
    QUICK_SALARIES,
    QUICK_SLOTS,
    QUICK_TIMES,
    REGIONS,
)
from bot.db.models import Channel, Job, JobStatus, Role, User
from bot.permissions import is_admin, is_staff
from bot.texts import job_row, money, short_date
from bot.utils import local_today

# ---------------------------------------------------------------- reply

BTN_FIND = "🔎 Ish qidirish"
BTN_MY = "📋 Mening ishlarim"
BTN_PROFILE = "👤 Profil"
BTN_POST = "➕ E'lon berish"
BTN_MY_ADS = "📢 E'lonlarim"
BTN_ADMIN = "🛠 Admin"

BTN_NEW_JOB = "➕ Yangi e'lon"
BTN_PAYMENTS = "💳 To'lovlar"
BTN_REVIEW = "🕓 Tasdiq kutayotgan e'lonlar"
BTN_ALL_ADS = "📢 Barcha e'lonlar"
BTN_STATS = "📊 Statistika"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_USERS = "👥 Foydalanuvchilar"
BTN_ADS = "📣 Reklama"
BTN_REPORTS = "🆘 Murojaatlar"
BTN_BACK = "⬅️ Orqaga"


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu(user: User) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    if user.role == Role.EMPLOYER:
        kb.button(text=BTN_POST)
        kb.button(text=BTN_MY_ADS)
        kb.button(text=BTN_PROFILE)
        kb.adjust(2, 1)
    else:
        kb.button(text=BTN_FIND)
        kb.button(text=BTN_MY)
        kb.button(text=BTN_PROFILE)
        if is_staff(user):
            kb.button(text=BTN_ADMIN)
            kb.adjust(2, 2)
        else:
            kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)


def admin_menu(user: User | None = None) -> ReplyKeyboardMarkup:
    """Moderator kamroq tugma ko'radi.

    Moderator: chek tekshiradi, e'lon joylaydi, yozilganlarni ko'radi.
    Faqat admin: sozlamalar, moliyaviy statistika, foydalanuvchilar.
    """
    full = user is None or is_admin(user)
    kb = ReplyKeyboardBuilder()
    kb.button(text=BTN_NEW_JOB)
    kb.button(text=BTN_PAYMENTS)
    kb.button(text=BTN_REVIEW)
    kb.button(text=BTN_REPORTS)
    kb.button(text=BTN_ALL_ADS)
    if full:
        kb.button(text=BTN_STATS)
        kb.button(text=BTN_ADS)
        kb.button(text=BTN_USERS)
        kb.button(text=BTN_SETTINGS)
        kb.button(text=BTN_BACK)
        kb.adjust(2, 2, 2, 2, 2)
    else:
        kb.button(text=BTN_BACK)
        kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True)


def skip_kb(field: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭ O'tkazib yuborish", callback_data=PickCB(field=field, value="__skip__").pack())
    return kb.as_markup()


# ---------------------------------------------------------------- ro'yxatdan o'tish

def role_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 Ish qidiryapman", callback_data=PickCB(field="role", value="worker").pack())
    kb.button(text="🏢 Ishchi kerak", callback_data=PickCB(field="role", value="employer").pack())
    kb.adjust(1)
    return kb.as_markup()


def regions_kb(field: str, *, with_all: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if with_all:
        kb.button(text="🌍 Barcha hududlar", callback_data=PickCB(field=field, value="*").pack())
    for r in REGIONS:
        kb.button(text=r, callback_data=PickCB(field=field, value=r).pack())
    kb.adjust(2)
    return kb.as_markup()


def categories_kb(field: str, *, with_all: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if with_all:
        kb.button(text="🌐 Barchasi", callback_data=PickCB(field=field, value="*").pack())
    for key, name in CATEGORIES:
        kb.button(text=name, callback_data=PickCB(field=field, value=key).pack())
    kb.adjust(2)
    return kb.as_markup()


def categories_multi_kb(selected: list[str]) -> InlineKeyboardMarkup:
    """Ko'p tanlovli obuna: bosilgani ✅ bilan belgilanadi."""
    kb = InlineKeyboardBuilder()
    for key, name in CATEGORIES:
        mark = "✅ " if key in selected else "▫️ "
        kb.button(text=mark + name, callback_data=PickCB(field="cat", value=key).pack())
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(
            text="✔️ Tayyor", callback_data=PickCB(field="cat", value="__done__").pack()
        )
    )
    return kb.as_markup()


# ---------------------------------------------------------------- ishchi

def feed_kb(
    rows: list[tuple[Job, int]],
    *,
    page: int,
    total: int,
    per_page: int,
    region: str,
    category: str,
    day: str,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for job, taken in rows:
        kb.button(
            text=job_row(job, taken),
            callback_data=JobCB(action="view", job_id=job.id).pack(),
        )
    kb.adjust(1)

    # Sahifalash
    pages = max((total + per_page - 1) // per_page, 1)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=FeedCB(action="page", page=page - 1).pack()
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{pages}", callback_data=NavCB(to="noop").pack()
            )
        )
        if page + 1 < pages:
            nav.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=FeedCB(action="page", page=page + 1).pack()
                )
            )
        kb.row(*nav)

    # Filtr holati tugmalarda ko'rinib turadi — odam nima yoqilganini biladi
    kb.row(
        InlineKeyboardButton(
            text=f"📍 {region or 'Barchasi'}",
            callback_data=FeedCB(action="filter", value="region").pack(),
        ),
        InlineKeyboardButton(
            text=f"🧰 {category or 'Barchasi'}",
            callback_data=FeedCB(action="filter", value="category").pack(),
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text=f"📅 {day or 'Barcha kunlar'}",
            callback_data=FeedCB(action="filter", value="day").pack(),
        ),
        InlineKeyboardButton(
            text="♻️ Filtrni tozalash", callback_data=FeedCB(action="reset").pack()
        ),
    )
    return kb.as_markup()


def days_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Barcha kunlar", callback_data=PickCB(field="fday", value="*").pack())
    today = local_today()
    for i in range(7):
        d = today + timedelta(days=i)
        kb.button(text=short_date(d), callback_data=PickCB(field="fday", value=d.isoformat()).pack())
    kb.adjust(1, 2)
    return kb.as_markup()


def job_view_kb(
    job: Job,
    *,
    taken: int,
    mine: bool,
    can_wait: bool,
    confirmed: bool = False,
    credits: int = 0,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    free = job.slots_total - taken

    if confirmed:
        kb.button(
            text="🚫 Bekor qilish", callback_data=JobCB(action="cancel", job_id=job.id).pack()
        )
        kb.button(
            text="🆘 Shikoyat", callback_data=JobCB(action="report", job_id=job.id).pack()
        )
    elif mine:
        kb.button(
            text="🚫 Bekor qilish",
            callback_data=JobCB(action="cancel", job_id=job.id).pack(),
        )
    elif job.status == JobStatus.OPEN and free > 0:
        label = "🆓 Bepul yozilish" if job.fee <= 0 else f"✅ Yozilish · {money(job.fee)}"
        kb.button(text=label, callback_data=JobCB(action="apply", job_id=job.id).pack())
        # Bonus bor va e'lon pulli — tanlov beramiz, avtomat sarflamaymiz.
        # Odam bonusini qaysi ishga ishlatishni o'zi hal qilsin.
        if job.fee > 0 and credits > 0:
            kb.button(
                text=f"🎁 Bonus bilan bepul ({credits} ta)",
                callback_data=JobCB(action="credit", job_id=job.id).pack(),
            )
    elif can_wait and job.status in (JobStatus.OPEN, JobStatus.FULL):
        kb.button(
            text="⏳ Navbatga yozilish (bepul)",
            callback_data=JobCB(action="wait", job_id=job.id).pack(),
        )

    kb.button(text="⬅️ Ro'yxatga", callback_data=NavCB(to="feed").pack())
    kb.adjust(1)
    return kb.as_markup()


def cancel_confirm_kb(job_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Ha, baribir bekor qilaman",
        callback_data=JobCB(action="cancelyes", job_id=job_id).pack(),
    )
    kb.button(text="⬅️ Yo'q, qoldiraman", callback_data=JobCB(action="view", job_id=job_id).pack())
    kb.adjust(1)
    return kb.as_markup()


def attendance_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha, chiqdim", callback_data=AttendCB(action="yes", booking_id=booking_id).pack())
    kb.button(text="❌ Yo'q", callback_data=AttendCB(action="no", booking_id=booking_id).pack())
    kb.adjust(2)
    return kb.as_markup()


def report_kb(report_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Javob berish", callback_data=ReportCB(action="answer", report_id=report_id).pack())
    kb.button(text="✅ Yopish", callback_data=ReportCB(action="close", report_id=report_id).pack())
    kb.adjust(2)
    return kb.as_markup()


def channel_post_kb(bot_username: str, job: Job, *, open_: bool) -> InlineKeyboardMarkup:
    """Kanaldagi post ostidagi tugma.

    Bu URL-tugma, callback emas. Kanal a'zosi bosganda to'g'ridan-to'g'ri bot
    lichkasi ochiladi va /start job_12 yuboriladi. Callback tugma bo'lsa odam
    kanalda qolib ketardi va biz unga shaxsiy xabar yoza olmasdik — Telegram
    ruxsat bermaydi.
    """
    kb = InlineKeyboardBuilder()
    if open_:
        label = "🆓 Bepul yozilish" if job.fee <= 0 else "✅ Yozilish"
        kb.button(text=label, url=f"https://t.me/{bot_username}?start=job_{job.id}")
    else:
        kb.button(
            text="⏳ Navbatga yozilish",
            url=f"https://t.me/{bot_username}?start=job_{job.id}",
        )
        kb.button(text="🔎 Boshqa ishlar", url=f"https://t.me/{bot_username}?start=feed")
    kb.adjust(1)
    return kb.as_markup()


# ---------------------------------------------------------------- e'lon yaratish

def times_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in QUICK_TIMES:
        # Diqqat: aiogram callback ma'lumotini ':' bilan ajratadi, shuning
        # uchun "08:00" ni qiymat sifatida yubora olmaymiz. '-' ga
        # almashtiramiz, qabul qilishda parse_time uni qaytaradi.
        kb.button(text=t, callback_data=PickCB(field="time", value=t.replace(":", "-")).pack())
    kb.adjust(3)
    return kb.as_markup()


def salaries_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in QUICK_SALARIES:
        kb.button(text=money(s), callback_data=PickCB(field="salary", value=str(s)).pack())
    kb.adjust(2)
    return kb.as_markup()


def slots_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in QUICK_SLOTS:
        kb.button(text=f"{n} kishi", callback_data=PickCB(field="slots", value=str(n)).pack())
    kb.adjust(3)
    return kb.as_markup()


def fee_kb(default_fee: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for v in {default_fee, 5000, 10000, 15000, 20000}:
        kb.button(text=money(v), callback_data=PickCB(field="fee", value=str(v)).pack())
    kb.button(text="🆓 Bepul", callback_data=PickCB(field="fee", value="0").pack())
    kb.adjust(2)
    return kb.as_markup()


def dates_kb(field: str = "date") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    today = local_today()
    for i in range(8):
        d = today + timedelta(days=i)
        kb.button(text=short_date(d), callback_data=PickCB(field=field, value=d.isoformat()).pack())
    kb.adjust(2)
    return kb.as_markup()


EDIT_FIELDS = [
    ("category", "🧰 Tur"),
    ("title", "📝 Nom"),
    ("description", "📄 Tavsif"),
    ("secret", "🔒 Maxfiy"),
    ("region", "📍 Hudud"),
    ("work_date", "📅 Sana"),
    ("start_time", "🕗 Vaqt"),
    ("salary", "💰 Haq"),
    ("slots", "👥 Kishi"),
    ("fee", "🎫 To'lov"),
]


def preview_kb(*, is_admin: bool) -> InlineKeyboardMarkup:
    """Oldindan ko'rish: har maydonni alohida tuzatish mumkin.

    Avval bitta xatoda butun jarayonni qaytadan boshlash kerak edi —
    8 qadam. Endi faqat o'sha maydonga qaytiladi.
    """
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ E'lon qilish" if is_admin else "📨 Tasdiqqa yuborish",
        callback_data=PickCB(field="confirm", value="yes").pack(),
    )
    kb.adjust(1)
    for field, label in EDIT_FIELDS:
        kb.button(text=f"✏️ {label}", callback_data=EditCB(field=field).pack())
    kb.adjust(1, 3, 3, 3, 1)
    kb.row(
        InlineKeyboardButton(
            text="🚫 Bekor qilish", callback_data=PickCB(field="confirm", value="no").pack()
        )
    )
    return kb.as_markup()


# ---------------------------------------------------------------- moderatsiya

def moderation_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=ModCB(action="ok", booking_id=booking_id).pack())
    kb.button(text="❌ Rad etish", callback_data=ModCB(action="no", booking_id=booking_id).pack())
    kb.adjust(2)
    return kb.as_markup()


def job_review_kb(job_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=JobModCB(action="ok", job_id=job_id).pack())
    kb.button(text="❌ Rad etish", callback_data=JobModCB(action="no", job_id=job_id).pack())
    kb.adjust(2)
    return kb.as_markup()


# ---------------------------------------------------------------- admin

def admin_job_kb(job: Job, *, owner_view: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Yozilganlar", callback_data=AdminJobCB(action="workers", job_id=job.id).pack())
    kb.button(text="♻️ Takrorlash", callback_data=AdminJobCB(action="clone", job_id=job.id).pack())
    if not owner_view:
        kb.button(
            text="💳 Pulli qilish" if job.fee <= 0 else "🆓 Bepul qilish",
            callback_data=AdminJobCB(action="fee", job_id=job.id).pack(),
        )
        if job.status in (JobStatus.OPEN, JobStatus.FULL):
            kb.button(text="🔒 Yopish", callback_data=AdminJobCB(action="close", job_id=job.id).pack())
        else:
            kb.button(text="🔓 Ochish", callback_data=AdminJobCB(action="reopen", job_id=job.id).pack())
        kb.button(
            text="📢 Kanallarga joylash",
            callback_data=AdminJobCB(action="repost", job_id=job.id).pack(),
        )
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def jobs_list_kb(jobs: list[Job]) -> InlineKeyboardMarkup:
    icon = {
        JobStatus.OPEN: "🟢",
        JobStatus.FULL: "🔴",
        JobStatus.CLOSED: "⚪️",
        JobStatus.CANCELLED: "❌",
        JobStatus.PENDING_REVIEW: "🕓",
        JobStatus.DECLINED: "🚫",
    }
    kb = InlineKeyboardBuilder()
    for j in jobs:
        kb.button(
            text=f"{icon[j.status]} #{j.id} {j.title} · {short_date(j.work_date)}",
            callback_data=AdminJobCB(action="view", job_id=j.id).pack(),
        )
    kb.adjust(1)
    return kb.as_markup()


def worker_actions_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ishga chiqdi", callback_data=WorkerCB(action="done", booking_id=booking_id).pack())
    kb.button(text="🚷 Chiqmadi", callback_data=WorkerCB(action="noshow", booking_id=booking_id).pack())
    kb.button(text="🚫 Bloklash", callback_data=WorkerCB(action="block", booking_id=booking_id).pack())
    kb.adjust(2, 1)
    return kb.as_markup()


def settings_kb(free_mode: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🆓 Bepul rejim: YOQILGAN" if free_mode else "💳 Pulli rejim: YOQILGAN",
        callback_data=SetCB(action="freemode").pack(),
    )
    kb.adjust(1)
    kb.button(text="📢 Kanallar", callback_data=SetCB(action="channels").pack())
    kb.button(text="🛡 Moderatorlar", callback_data=SetCB(action="staff").pack())
    kb.button(text="👮 Moderatsiya chati", callback_data=SetCB(action="moderation").pack())
    kb.button(text="💳 Karta raqami", callback_data=SetCB(action="card").pack())
    kb.button(text="👤 Karta egasi", callback_data=SetCB(action="holder").pack())
    kb.button(text="🎫 Standart to'lov", callback_data=SetCB(action="fee").pack())
    kb.button(text="⏳ Bron muddati", callback_data=SetCB(action="hold").pack())
    kb.button(text="🚷 No-show limiti", callback_data=SetCB(action="noshow").pack())
    kb.button(text="💾 Zaxira nusxa", callback_data=SetCB(action="backup").pack())
    kb.adjust(1, 2, 1, 2, 2, 1, 1)
    return kb.as_markup()


# ---------------------------------------------------------------- kanallar

def channels_kb(channels: list[Channel]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in channels:
        mark = "🟢" if c.is_active else "⚪️"
        scope = []
        if c.region_list:
            scope.append(f"{len(c.region_list)} hudud")
        if c.category_list:
            scope.append(f"{len(c.category_list)} kasb")
        tail = f" · {', '.join(scope)}" if scope else " · barchasi"
        kb.button(
            text=f"{mark} {c.title or c.chat_id}{tail}",
            callback_data=ChanCB(action="view", channel_id=c.id).pack(),
        )
    kb.adjust(1)
    kb.row(
        InlineKeyboardButton(
            text="➕ Kanal/guruh qo'shish", callback_data=SetCB(action="channel").pack()
        )
    )
    return kb.as_markup()


def channel_kb(channel: Channel) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📍 Hudud filtri", callback_data=ChanCB(action="regions", channel_id=channel.id).pack())
    kb.button(text="🧰 Kasb filtri", callback_data=ChanCB(action="cats", channel_id=channel.id).pack())
    kb.button(text="🧪 Tekshirish", callback_data=ChanCB(action="test", channel_id=channel.id).pack())
    kb.button(
        text="⏸ To'xtatish" if channel.is_active else "▶️ Yoqish",
        callback_data=ChanCB(action="toggle", channel_id=channel.id).pack(),
    )
    kb.button(text="🗑 O'chirish", callback_data=ChanCB(action="del", channel_id=channel.id).pack())
    kb.button(text="⬅️ Ro'yxat", callback_data=SetCB(action="channels").pack())
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def multi_pick_kb(
    field: str, options: list[tuple[str, str]], selected: list[str]
) -> InlineKeyboardMarkup:
    """Ko'p tanlovli ro'yxat: bosilgani ✅ bilan belgilanadi."""
    kb = InlineKeyboardBuilder()
    for key, label in options:
        mark = "✅ " if key in selected else "▫️ "
        kb.button(text=mark + label, callback_data=PickCB(field=field, value=key).pack())
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(
            text="🌐 Barchasi (filtrsiz)",
            callback_data=PickCB(field=field, value="__all__").pack(),
        ),
        InlineKeyboardButton(
            text="✔️ Tayyor", callback_data=PickCB(field=field, value="__done__").pack()
        ),
    )
    return kb.as_markup()


def region_options() -> list[tuple[str, str]]:
    return [(r, r) for r in REGIONS]


def category_options() -> list[tuple[str, str]]:
    return [(k, CATEGORY_NAMES[k]) for k, _ in CATEGORIES]


# ---------------------------------------------------------------- xodimlar

def staff_kb(members: list[User]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in members:
        kb.button(
            text=f"🗑 {m.full_name or m.id}",
            callback_data=StaffCB(action="demote", user_id=m.id).pack(),
        )
    kb.adjust(1)
    kb.row(
        InlineKeyboardButton(
            text="➕ Moderator qo'shish", callback_data=SetCB(action="addstaff").pack()
        )
    )
    return kb.as_markup()
