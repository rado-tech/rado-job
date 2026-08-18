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
    ChanListCB,
    EditCB,
    FeedCB,
    JobCB,
    JobEditCB,
    JobModCB,
    LogCB,
    ModCB,
    NavCB,
    PickCB,
    ProfCB,
    PubCB,
    RateCB,
    RejCB,
    ReportCB,
    SetCB,
    StaffCB,
    UserCB,
    UsersCB,
    WorkerCB,
)
from bot.config import (
    CATEGORIES,
    CATEGORY_NAMES,
    QUICK_SALARIES,
    QUICK_SLOTS,
    QUICK_TIMES,
    REGIONS,
    category_items,
    category_name,
)
from bot.db.models import Channel, Job, JobStatus, Role, User
from bot.permissions import is_admin, is_staff
from bot import texts
from bot.i18n import LANGS, is_ru
from bot.utils import local_today

# ---------------------------------------------------------------- reply

# Ishchi/ish beruvchi ko'radigan tugmalar ikki tilda.
#
# Muhim nozik joy: handler'lar tugma MATNI bo'yicha filtrlaydi. Shuning
# uchun har tugmaning ikkala varianti ham kerak — odam tilni almashtirsa,
# ekranida eski klaviatura qolgan bo'lsa ham tugma ishlashda davom etadi.
_LABELS: dict[str, tuple[str, str]] = {
    "find": ("🔎 Ish qidirish", "🔎 Поиск работы"),
    "my": ("📋 Mening ishlarim", "📋 Мои работы"),
    "profile": ("👤 Profil", "👤 Профиль"),
    "post": ("➕ E'lon berish", "➕ Разместить работу"),
    "myads": ("📢 E'lonlarim", "📢 Мои объявления"),
    "admin": ("🛠 Admin", "🛠 Админ"),
    "back": ("⬅️ Orqaga", "⬅️ Назад"),
}


def label(key: str) -> str:
    """Joriy tildagi tugma matni."""
    uz_text, ru_text = _LABELS[key]
    return ru_text if is_ru() else uz_text


def variants(key: str) -> set[str]:
    """Filtr uchun: tugmaning BARCHA tillardagi variantlari."""
    return set(_LABELS[key])


# Eski nomlar (o'zbekcha) — admin paneli va kod ichidagi havolalar uchun.
BTN_FIND = _LABELS["find"][0]
BTN_MY = _LABELS["my"][0]
BTN_PROFILE = _LABELS["profile"][0]
BTN_POST = _LABELS["post"][0]
BTN_MY_ADS = _LABELS["myads"][0]
BTN_ADMIN = _LABELS["admin"][0]

BTN_NEW_JOB = "➕ Yangi e'lon"
BTN_PAYMENTS = "💳 To'lovlar"
BTN_REVIEW = "🕓 Tasdiq kutayotgan e'lonlar"
BTN_ALL_ADS = "📢 Barcha e'lonlar"
BTN_STATS = "📊 Statistika"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_USERS = "👥 Foydalanuvchilar"
BTN_ADS = "📣 Reklama"
BTN_REPORTS = "🆘 Murojaatlar"
BTN_BACK = _LABELS["back"][0]


def phone_kb() -> ReplyKeyboardMarkup:
    text = "📱 Отправить номер" if is_ru() else "📱 Raqamni yuborish"
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def lang_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, name in LANGS.items():
        kb.button(text=name, callback_data=PickCB(field="lang", value=code).pack())
    kb.adjust(1)
    return kb.as_markup()


def main_menu(user: User) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    if user.role == Role.EMPLOYER:
        kb.button(text=label("post"))
        kb.button(text=label("myads"))
        kb.button(text=label("profile"))
        kb.adjust(2, 1)
    else:
        kb.button(text=label("find"))
        kb.button(text=label("my"))
        kb.button(text=label("profile"))
        if is_staff(user):
            kb.button(text=label("admin"))
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
    kb.button(text=texts.BTN_SKIP, callback_data=PickCB(field=field, value="__skip__").pack())
    return kb.as_markup()


def _page_nav(kb: InlineKeyboardBuilder, *, page: int, total: int, per_page: int, make) -> None:  # noqa: ANN001
    """◀️ 2/5 ▶️ qatori. `make(p)` — sahifa tugmasining callback matni."""
    pages = max((total + per_page - 1) // per_page, 1)
    if pages <= 1:
        return
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=make(page - 1)))
    nav.append(
        InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=NavCB(to="noop").pack())
    )
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=make(page + 1)))
    kb.row(*nav)


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
        kb.button(
            text=texts.BTN_ALL_CATEGORIES,
            callback_data=PickCB(field=field, value="*").pack(),
        )
    for key, name in category_items():
        kb.button(text=name, callback_data=PickCB(field=field, value=key).pack())
    kb.adjust(2)
    return kb.as_markup()


def categories_multi_kb(selected: list[str]) -> InlineKeyboardMarkup:
    """Ko'p tanlovli obuna: bosilgani ✅ bilan belgilanadi."""
    kb = InlineKeyboardBuilder()
    for key, name in category_items():
        mark = "✅ " if key in selected else "▫️ "
        kb.button(text=mark + name, callback_data=PickCB(field="cat", value=key).pack())
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(
            text=texts.BTN_DONE, callback_data=PickCB(field="cat", value="__done__").pack()
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
            text=texts.job_row(job, taken),
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
            text=f"📍 {region or texts.ALL_LABEL}",
            callback_data=FeedCB(action="filter", value="region").pack(),
        ),
        InlineKeyboardButton(
            text=f"🧰 {category or texts.ALL_LABEL}",
            callback_data=FeedCB(action="filter", value="category").pack(),
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text=f"📅 {day or texts.ALL_DAYS_LABEL}",
            callback_data=FeedCB(action="filter", value="day").pack(),
        ),
        InlineKeyboardButton(
            text=texts.BTN_CLEAR_FILTER, callback_data=FeedCB(action="reset").pack()
        ),
    )
    return kb.as_markup()


def days_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🌐 {texts.ALL_DAYS_LABEL}", callback_data=PickCB(field="fday", value="*").pack())
    today = local_today()
    for i in range(7):
        d = today + timedelta(days=i)
        kb.button(text=texts.short_date(d), callback_data=PickCB(field="fday", value=d.isoformat()).pack())
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
            text=texts.BTN_CANCEL_BOOKING,
            callback_data=JobCB(action="cancel", job_id=job.id).pack(),
        )
        kb.button(
            text=texts.BTN_COMPLAIN, callback_data=JobCB(action="report", job_id=job.id).pack()
        )
    elif mine:
        kb.button(
            text=texts.BTN_CANCEL_BOOKING,
            callback_data=JobCB(action="cancel", job_id=job.id).pack(),
        )
    elif job.status == JobStatus.OPEN and free > 0:
        label = (
            texts.BTN_APPLY_FREE
            if job.fee <= 0
            else f"{texts.BTN_APPLY} · {texts.money(job.fee)}"
        )
        kb.button(text=label, callback_data=JobCB(action="apply", job_id=job.id).pack())
        # Bonus bor va e'lon pulli — tanlov beramiz, avtomat sarflamaymiz.
        # Odam bonusini qaysi ishga ishlatishni o'zi hal qilsin.
        if job.fee > 0 and credits > 0:
            kb.button(
                text=texts.btn_credit(credits),
                callback_data=JobCB(action="credit", job_id=job.id).pack(),
            )
    elif can_wait and job.status in (JobStatus.OPEN, JobStatus.FULL):
        kb.button(
            text=texts.BTN_WAITLIST,
            callback_data=JobCB(action="wait", job_id=job.id).pack(),
        )

    kb.button(text=texts.BTN_TO_LIST, callback_data=NavCB(to="feed").pack())
    kb.adjust(1)
    return kb.as_markup()


def cancel_confirm_kb(job_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=texts.BTN_CANCEL_YES,
        callback_data=JobCB(action="cancelyes", job_id=job_id).pack(),
    )
    kb.button(text=texts.BTN_CANCEL_NO, callback_data=JobCB(action="view", job_id=job_id).pack())
    kb.adjust(1)
    return kb.as_markup()


def attendance_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_ATT_YES, callback_data=AttendCB(action="yes", booking_id=booking_id).pack())
    kb.button(text=texts.BTN_ATT_NO, callback_data=AttendCB(action="no", booking_id=booking_id).pack())
    kb.adjust(2)
    return kb.as_markup()


def profile_kb(user: User) -> InlineKeyboardMarkup:
    """Profil ostidagi tugmalar — buyruq yozish shart bo'lmasin.

    Ishchi va ish beruvchi turli tugmalar ko'radi: xabarnoma va
    qiziqishlar faqat ishchiga tegishli.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_P_LANG, callback_data=ProfCB(action="lang").pack())
    kb.button(text=texts.BTN_P_REGION, callback_data=ProfCB(action="region").pack())
    if user.role == Role.WORKER:
        kb.button(text=texts.BTN_P_CATS, callback_data=ProfCB(action="cats").pack())
        kb.button(
            text=texts.BTN_P_NOTIFY_ON if user.notify else texts.BTN_P_NOTIFY_OFF,
            callback_data=ProfCB(action="notify").pack(),
        )
    kb.button(text=texts.BTN_P_INVITE, callback_data=ProfCB(action="invite").pack())
    kb.button(text=texts.BTN_P_COMPLAIN, callback_data=ProfCB(action="complain").pack())
    # Xodimning roli almashmaydi — tugmani ko'rsatishning ma'nosi yo'q.
    if not is_staff(user):
        kb.button(text=texts.BTN_P_ROLE, callback_data=ProfCB(action="role").pack())
    kb.button(text=texts.BTN_P_HELP, callback_data=ProfCB(action="help").pack())
    kb.adjust(2, 2, 2, 2)
    return kb.as_markup()


def rate_kb(kind: str, ref: int) -> InlineKeyboardMarkup:
    """1-5 baho. kind: "e" — ish beruvchiga, "w" — ishchiga."""
    kb = InlineKeyboardBuilder()
    for n in range(1, 6):
        kb.button(text=f"{n}⭐", callback_data=RateCB(kind=kind, ref=ref, stars=n).pack())
    kb.button(text=texts.BTN_SKIP, callback_data=RateCB(kind=kind, ref=ref, stars=0).pack())
    kb.adjust(5, 1)
    return kb.as_markup()


def report_kb(report_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Javob berish", callback_data=ReportCB(action="answer", report_id=report_id).pack())
    kb.button(text="✅ Yopish", callback_data=ReportCB(action="close", report_id=report_id).pack())
    kb.adjust(2)
    return kb.as_markup()


def channel_post_kb(
    bot_username: str, job: Job, *, open_: bool, channel_id: int | None = None
) -> InlineKeyboardMarkup:
    """Kanaldagi post ostidagi tugma.

    Bu URL-tugma, callback emas. Kanal a'zosi bosganda to'g'ridan-to'g'ri bot
    lichkasi ochiladi va /start job_12 yuboriladi. Callback tugma bo'lsa odam
    kanalda qolib ketardi va biz unga shaxsiy xabar yoza olmasdik — Telegram
    ruxsat bermaydi.
    """
    # Havolaga kanal belgisi qo'shiladi: job_12_c3. Shu orqali qaysi kanal
    # odam olib kelganini bilamiz — reklamani qayerga sarflash shundan
    # ma'lum bo'ladi.
    payload = f"job_{job.id}" + (f"_c{channel_id}" if channel_id else "")

    kb = InlineKeyboardBuilder()
    if open_:
        label = "🆓 Bepul yozilish" if job.fee <= 0 else "✅ Yozilish"
        kb.button(text=label, url=f"https://t.me/{bot_username}?start={payload}")
    else:
        kb.button(
            text="⏳ Navbatga yozilish",
            url=f"https://t.me/{bot_username}?start={payload}",
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
        kb.button(text=texts.money(s), callback_data=PickCB(field="salary", value=str(s)).pack())
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
        kb.button(text=texts.money(v), callback_data=PickCB(field="fee", value=str(v)).pack())
    kb.button(text="🆓 Bepul", callback_data=PickCB(field="fee", value="0").pack())
    kb.adjust(2)
    return kb.as_markup()


def dates_kb(field: str = "date") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    today = local_today()
    for i in range(8):
        d = today + timedelta(days=i)
        kb.button(text=texts.short_date(d), callback_data=PickCB(field=field, value=d.isoformat()).pack())
    kb.adjust(2)
    return kb.as_markup()


EDIT_FIELD_KEYS = [
    "category", "title", "description", "secret",
    "region", "work_date", "start_time", "salary", "slots", "fee",
]


def edit_fields() -> list[tuple[str, str]]:
    """Tahrirlash tugmalari — joriy tildagi qisqa nomlar bilan."""
    return [(key, texts.FIELD_SHORT[key]) for key in EDIT_FIELD_KEYS]


# Eski nom — kod ichidagi havolalar uchun.
EDIT_FIELDS = [(k, k) for k in EDIT_FIELD_KEYS]


def preview_kb(*, is_admin: bool) -> InlineKeyboardMarkup:
    """Oldindan ko'rish: har maydonni alohida tuzatish mumkin.

    Avval bitta xatoda butun jarayonni qaytadan boshlash kerak edi —
    10 qadam. Endi faqat o'sha maydonga qaytiladi.
    """
    kb = InlineKeyboardBuilder()
    kb.button(
        text=texts.BTN_PUBLISH if is_admin else texts.BTN_SEND_REVIEW,
        callback_data=PickCB(field="confirm", value="yes").pack(),
    )
    kb.adjust(1)
    for field, label in edit_fields():
        kb.button(text=f"✏️ {label}", callback_data=EditCB(field=field).pack())
    kb.adjust(1, 3, 3, 3, 1)
    kb.row(
        InlineKeyboardButton(
            text=texts.BTN_CANCEL, callback_data=PickCB(field="confirm", value="no").pack()
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


REJECT_REASONS = {
    "fake": "Chek soxta ko'rinadi",
    "amount": "Summa noto'g'ri",
    "old": "Eski chek qayta yuborilgan",
    "notfound": "To'lov kelib tushmadi",
}


def reject_reasons_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Tayyor sabablar.

    Moderator ko'p hollarda matn yozmasligi kerak — bu tez va xatosiz.
    «Boshqa sabab» tanlansa yozish so'raladi.
    """
    kb = InlineKeyboardBuilder()
    for key, label in REJECT_REASONS.items():
        kb.button(text=label, callback_data=RejCB(key=key, booking_id=booking_id).pack())
    kb.button(text="✍️ Boshqa sabab", callback_data=RejCB(key="other", booking_id=booking_id).pack())
    kb.button(text="⬅️ Bekor qilish", callback_data=RejCB(key="back", booking_id=booking_id).pack())
    kb.adjust(1)
    return kb.as_markup()


def undo_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Qaror qabul qilingandan keyin — xatoni tuzatish imkoni."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="↩️ Qarorni qaytarish",
        callback_data=ModCB(action="undo", booking_id=booking_id).pack(),
    )
    return kb.as_markup()


def job_review_kb(job_id: int) -> InlineKeyboardMarkup:
    """Tasdiq kartochkasi.

    «Tahrirlash» ham shu yerda: ma'lumot aralash bo'lsa (manzil tavsifga
    tushib qolgan, telefon noto'g'ri) moderator uni RAD ETMASDAN tuzatib
    yuborishi kerak. Ilgari buning uchun boshqa bo'limdan e'lonni qidirib
    topish kerak edi va moderator buni bilmasligi mumkin edi.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=JobModCB(action="ok", job_id=job_id).pack())
    kb.button(text="❌ Rad etish", callback_data=JobModCB(action="no", job_id=job_id).pack())
    kb.button(text="✏️ Tahrirlash", callback_data=AdminJobCB(action="edit", job_id=job_id).pack())
    kb.adjust(2, 1)
    return kb.as_markup()


# ---------------------------------------------------------------- admin

def admin_job_kb(job: Job, *, owner_view: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Yozilganlar", callback_data=AdminJobCB(action="workers", job_id=job.id).pack())
    kb.button(text="♻️ Takrorlash", callback_data=AdminJobCB(action="clone", job_id=job.id).pack())
    kb.button(text="📨 Xabar yuborish", callback_data=AdminJobCB(action="msg", job_id=job.id).pack())
    if job.status in (JobStatus.OPEN, JobStatus.FULL, JobStatus.PENDING_REVIEW):
        kb.button(text="✏️ Tahrirlash", callback_data=AdminJobCB(action="edit", job_id=job.id).pack())
        # Narx faqat xodim qo'lida — ish beruvchi uni ko'rmaydi ham.
        # Bekor qilish — yopishdan farqli: yozilganlarga XABAR beriladi.
        kb.button(
            text="❌ Ishni bekor qilish",
            callback_data=AdminJobCB(action="cancel", job_id=job.id).pack(),
        )
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
    kb.adjust(2, 2, 2, 2)
    return kb.as_markup()


def edit_job_kb(job_id: int) -> InlineKeyboardMarkup:
    """Joylangan e'lonning qaysi maydonini tahrirlash."""
    kb = InlineKeyboardBuilder()
    for field, label in edit_fields():
        if field == "fee":
            continue  # narx alohida tugma orqali o'zgaradi
        kb.button(text=label, callback_data=JobEditCB(field=field, job_id=job_id).pack())
    # Lokatsiya EDIT_FIELD_KEYS da yo'q, lekin tahrirlash mumkin bo'lishi kerak.
    kb.button(
        text=texts.FIELD_SHORT["location"],
        callback_data=JobEditCB(field="location", job_id=job_id).pack(),
    )
    kb.adjust(3)
    kb.row(
        InlineKeyboardButton(
            text=texts.BTN_BACK_SHORT,
            callback_data=AdminJobCB(action="view", job_id=job_id).pack(),
        )
    )
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
            text=f"{icon[j.status]} #{j.id} {j.title} · {texts.short_date(j.work_date)}",
            callback_data=AdminJobCB(action="view", job_id=j.id).pack(),
        )
    kb.adjust(1)
    return kb.as_markup()


def worker_actions_kb(booking_id: int, *, can_block: bool = True) -> InlineKeyboardMarkup:
    """Ishchini belgilash. Ish beruvchiga bloklash tugmasi ko'rsatilmaydi —
    u baribir ishlamaydi (faqat admin bloklaydi) va faqat chalg'itadi."""
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_MARK_DONE, callback_data=WorkerCB(action="done", booking_id=booking_id).pack())
    kb.button(text=texts.BTN_MARK_NOSHOW, callback_data=WorkerCB(action="noshow", booking_id=booking_id).pack())
    if can_block:
        kb.button(text=texts.BTN_MARK_BLOCK, callback_data=WorkerCB(action="block", booking_id=booking_id).pack())
        kb.adjust(2, 1)
    else:
        kb.adjust(2)
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
    kb.button(text="👮 Moderatsiya guruhi", callback_data=SetCB(action="moderation").pack())
    kb.button(text="💾 Zaxira kanali", callback_data=SetCB(action="backupchat").pack())
    kb.button(text="💳 Karta raqami", callback_data=SetCB(action="card").pack())
    kb.button(text="👤 Karta egasi", callback_data=SetCB(action="holder").pack())
    kb.button(text="🎫 Standart to'lov", callback_data=SetCB(action="fee").pack())
    kb.button(text="⏳ Bron muddati", callback_data=SetCB(action="hold").pack())
    kb.button(text="🚷 No-show limiti", callback_data=SetCB(action="noshow").pack())
    kb.button(text="📋 Jurnal", callback_data=SetCB(action="journal").pack())
    # Ilgari faqat /health va /hisobot buyruqlari orqali ochilardi — ularni
    # bilish uchun README o'qish kerak edi.
    kb.button(text="🩺 Bot holati", callback_data=SetCB(action="health").pack())
    kb.button(text="📈 Kunlik hisobot", callback_data=SetCB(action="report").pack())
    kb.button(text="💾 Zaxira nusxa olish", callback_data=SetCB(action="backup").pack())
    kb.adjust(1, 2, 2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def single_chat_kb(kind: str, connected: bool) -> InlineKeyboardMarkup:
    """Bitta chat uchun kartochka: tekshirish va uzish.

    Moderatsiya guruhi va zaxira kanali — har biri FAQAT BITTA bo'ladi.
    Yangisini ulash uchun avval eskisini uzish kerak: shunda chek yoki
    zaxira ikki joyga bo'linib ketmaydi.
    """
    kb = InlineKeyboardBuilder()
    if connected:
        kb.button(text="🧪 Tekshirish", callback_data=SetCB(action=f"test_{kind}").pack())
        kb.button(text="🔌 Uzish", callback_data=SetCB(action=f"off_{kind}").pack())
        kb.adjust(2)
    else:
        kb.button(text="🔗 Ulash", callback_data=SetCB(action=f"link_{kind}").pack())
        kb.adjust(1)
    return kb.as_markup()


# ---------------------------------------------------------------- kanallar

CHANNELS_PER_PAGE = 10


def channels_kb(channels: list[Channel], page: int = 0) -> InlineKeyboardMarkup:
    """Kanallar ro'yxati — 10 tadan sahifalab.

    40-50 kanal ulanganida bitta uzun ro'yxat ekranga sig'may, tugmalar
    orasidan kerakli kanalni topish qiynalardi.
    """
    kb = InlineKeyboardBuilder()
    start = page * CHANNELS_PER_PAGE
    for c in channels[start : start + CHANNELS_PER_PAGE]:
        mark = "🟢" if c.is_active else "⚪️"
        scope = []
        if c.region_list:
            scope.append(f"{len(c.region_list)} hudud")
        if c.category_list:
            scope.append(f"{len(c.category_list)} kasb")
        tail = f" · {', '.join(scope)}" if scope else " · barchasi"
        kb.button(
            text=f"{mark} {c.title or c.chat_id}{tail}"[:60],
            callback_data=ChanCB(action="view", channel_id=c.id).pack(),
        )
    kb.adjust(1)
    _page_nav(
        kb,
        page=page,
        total=len(channels),
        per_page=CHANNELS_PER_PAGE,
        make=lambda p: ChanListCB(page=p).pack(),
    )
    kb.row(
        InlineKeyboardButton(
            text="➕ Kanal/guruh qo'shish", callback_data=SetCB(action="channel").pack()
        )
    )
    return kb.as_markup()


def publish_choice_kb(
    job_id: int, matching: int, total: int, *, broadcast: bool
) -> InlineKeyboardMarkup:
    """E'lonni qayerga joylashni tanlash.

    Standart yo'l — «mos kanallarga» (kanal teglari bo'yicha). «Barchaga»
    va «qo'lda tanlash» maxsus holatlar uchun: masalan shoshilinch ish
    hamma kanalda chiqsin yoki aksincha faqat bitta tuman kanalida.
    """
    bc = 1 if broadcast else 0
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"📤 Mos kanallarga ({matching} ta)",
        callback_data=PubCB(action="auto", job_id=job_id, value=bc).pack(),
    )
    kb.button(
        text=f"📢 Barcha kanallarga ({total} ta)",
        callback_data=PubCB(action="all", job_id=job_id, value=bc).pack(),
    )
    kb.button(text="🗂 Qo'lda tanlash", callback_data=PubCB(action="pick", job_id=job_id, value=bc).pack())
    kb.button(text="🚫 Kanalga joylamaslik", callback_data=PubCB(action="skip", job_id=job_id, value=bc).pack())
    kb.adjust(1)
    return kb.as_markup()


def publish_pick_kb(
    channels: list[Channel], picked: list[int], *, job_id: int, page: int
) -> InlineKeyboardMarkup:
    """Qo'lda kanal tanlash — ko'p tanlovli, 10 tadan sahifalab."""
    kb = InlineKeyboardBuilder()
    start = page * CHANNELS_PER_PAGE
    for c in channels[start : start + CHANNELS_PER_PAGE]:
        mark = "✅ " if c.id in picked else "▫️ "
        kb.button(
            text=(mark + (c.title or str(c.chat_id)))[:60],
            callback_data=PubCB(action="t", job_id=job_id, value=c.id).pack(),
        )
    kb.adjust(1)
    _page_nav(
        kb,
        page=page,
        total=len(channels),
        per_page=CHANNELS_PER_PAGE,
        make=lambda p: PubCB(action="page", job_id=job_id, value=p).pack(),
    )
    kb.row(
        InlineKeyboardButton(
            text=f"📨 Yuborish ({len(picked)} ta)",
            callback_data=PubCB(action="done", job_id=job_id).pack(),
        )
    )
    return kb.as_markup()


def journal_kb(page: int, total: int, per_page: int = 10) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _page_nav(kb, page=page, total=total, per_page=per_page, make=lambda p: LogCB(page=p).pack())
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

def ad_channels_kb(items: list[Channel], picked: list[int], page: int = 0) -> InlineKeyboardMarkup:
    """Reklama uchun kanal tanlash (ko'p tanlovli, 10 tadan sahifalab)."""
    kb = InlineKeyboardBuilder()
    start = page * CHANNELS_PER_PAGE
    for c in items[start : start + CHANNELS_PER_PAGE]:
        mark = "✅ " if c.id in picked else "▫️ "
        kb.button(
            text=(mark + (c.title or str(c.chat_id)))[:60],
            callback_data=PickCB(field="adch", value=str(c.id)).pack(),
        )
    kb.adjust(1)
    _page_nav(
        kb,
        page=page,
        total=len(items),
        per_page=CHANNELS_PER_PAGE,
        make=lambda p: PickCB(field="adch", value=f"__page_{p}__").pack(),
    )
    kb.row(
        InlineKeyboardButton(
            text=f"✔️ Tayyor ({len(picked)} ta)",
            callback_data=PickCB(field="adch", value="__done__").pack(),
        )
    )
    return kb.as_markup()


ROLE_ICON = {
    Role.WORKER: "👷",
    Role.EMPLOYER: "🏢",
    Role.MODERATOR: "🛡",
    Role.ADMIN: "👑",
}


def users_list_kb(
    users: list[User], *, page: int, total: int, per_page: int, only_blocked: bool
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for u in users:
        mark = "🚫 " if u.is_blocked else ROLE_ICON.get(u.role, "👤") + " "
        name = u.full_name or str(u.id)
        tag = f" @{u.username}" if u.username else ""
        kb.button(
            text=f"{mark}{name}{tag}"[:60],
            callback_data=UserCB(action="view", user_id=u.id).pack(),
        )
    kb.adjust(1)

    pages = max((total + per_page - 1) // per_page, 1)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=UsersCB(action="page", page=page - 1).pack()
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
                    text="▶️", callback_data=UsersCB(action="page", page=page + 1).pack()
                )
            )
        kb.row(*nav)

    kb.row(
        InlineKeyboardButton(text="🔎 Qidirish", callback_data=UsersCB(action="search").pack()),
        InlineKeyboardButton(
            text="👥 Hammasi" if only_blocked else "🚫 Bloklanganlar",
            callback_data=UsersCB(action="all" if only_blocked else "blocked").pack(),
        ),
    )
    return kb.as_markup()


def user_card_kb(target: User, *, is_owner_account: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not is_owner_account:
        if target.is_blocked:
            kb.button(
                text="✅ Blokdan chiqarish",
                callback_data=UserCB(action="unblock", user_id=target.id).pack(),
            )
        else:
            kb.button(
                text="🚫 Bloklash",
                callback_data=UserCB(action="block", user_id=target.id).pack(),
            )
        if target.role == Role.MODERATOR:
            kb.button(
                text="🛡 Moderatorlikdan olish",
                callback_data=UserCB(action="unmod", user_id=target.id).pack(),
            )
        elif target.role in (Role.WORKER, Role.EMPLOYER):
            kb.button(
                text="🛡 Moderator qilish",
                callback_data=UserCB(action="mod", user_id=target.id).pack(),
            )
    kb.button(text="⬅️ Ro'yxatga", callback_data=UsersCB(action="page", page=0).pack())
    kb.adjust(1)
    return kb.as_markup()


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
