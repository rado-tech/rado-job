"""Barcha matnlar shu yerda.

Matnni tahrirlash uchun kod ichida qidirib yurmaysiz, va ertaga rus tili
qo'shmoqchi bo'lsangiz — faqat shu fayl ko'chiriladi.
"""

from __future__ import annotations

from datetime import date

from bot.config import category_name
from bot.db.models import Booking, BookingStatus, Job, JobStatus, User
from bot.utils import local_today

WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]


def money(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " so'm"


def fmt_date(d: date) -> str:
    today = local_today()
    delta = (d - today).days
    if delta == 0:
        return f"Bugun, {d.day}-{MONTHS[d.month - 1]}"
    if delta == 1:
        return f"Ertaga, {d.day}-{MONTHS[d.month - 1]}"
    return f"{d.day}-{MONTHS[d.month - 1]} ({WEEKDAYS[d.weekday()]})"


def short_date(d: date) -> str:
    delta = (d - local_today()).days
    if delta == 0:
        return "Bugun"
    if delta == 1:
        return "Ertaga"
    return f"{d.day}.{d.month:02d}"


# ================================================================ umumiy

CHOOSE_ROLE = (
    "👋 <b>Assalomu alaykum!</b>\n\n"
    "Bu bot orqali <b>kunlik ish</b> topasiz yoki <b>ishchi</b> yollaysiz.\n\n"
    "Kim sifatida kirasiz?"
)

START_WORKER = (
    "🔎 <b>Ish qidiruvchi</b> sifatida davom etamiz.\n\n"
    "Qanday ishlaydi:\n"
    "1️⃣ O'zingizga mos e'lonni tanlaysiz\n"
    "2️⃣ Yozilish to'lovini qilib, chek skrinshotini yuborasiz\n"
    "3️⃣ Tasdiqlangach ish manzili va aloqa raqami sizga keladi\n\n"
    "Boshlash uchun telefon raqamingizni yuboring 👇"
)

START_EMPLOYER = (
    "🏢 <b>Ish beruvchi</b> sifatida davom etamiz.\n\n"
    "Siz e'lon berasiz, biz ishchi topib beramiz. E'lon administrator "
    "tekshiruvidan o'tgach kanalda va botda chiqadi.\n\n"
    "Boshlash uchun telefon raqamingizni yuboring 👇"
)

ASK_PHONE_BUTTON_ONLY = (
    "❗️ Raqamni qo'lda yozmang — pastdagi <b>«📱 Raqamni yuborish»</b> "
    "tugmasini bosing. Bu raqam haqiqiy ekanini tekshirish uchun kerak."
)
ASK_REGION = "📍 Qaysi hududdasiz? Shu bo'yicha e'lonlarni filtrlab beramiz."
ASK_CATEGORIES = (
    "🧰 <b>Qanday ishlar sizga qiziq?</b>\n\n"
    "Tanlaganlaringiz bo'yicha yangi e'lon chiqqanda darhol xabar beramiz.\n"
    "Bir nechtasini tanlashingiz mumkin. Hech narsa tanlamasangiz — "
    "barcha e'lonlar keladi."
)

REGISTERED_WORKER = (
    "✅ <b>Tayyor!</b>\n\n"
    "«🔎 Ish qidirish» tugmasi orqali ochiq e'lonlarni ko'ring."
)
REGISTERED_EMPLOYER = (
    "✅ <b>Tayyor!</b>\n\n"
    "«➕ E'lon berish» tugmasi orqali birinchi e'loningizni joylang."
)

MAIN_MENU = "🏠 Asosiy menyu"
BLOCKED = "🚫 Hisobingiz bloklangan. Sabab bo'yicha administrator bilan bog'laning."
TOO_FAST = "⏳ Biroz sekinroq, iltimos."

NO_JOBS = (
    "😔 Bu filtrga mos e'lon topilmadi.\n\n"
    "Filtrni kengaytirib ko'ring yoki kuting — yangi e'lon chiqishi bilan "
    "sizga xabar beramiz."
)


# ================================================================ e'lon

def job_card(
    job: Job,
    taken: int,
    *,
    secret: bool = False,
    show_slots: bool = True,
    waitlist: int = 0,
) -> str:
    """Bitta e'lonning to'liq ko'rinishi.

    secret=True — to'lovi tasdiqlangan ishchi uchun maxfiy ma'lumot ham
    qo'shiladi. Shu bitta bayroq butun biznes modelini ushlab turadi,
    shuning uchun maxfiy ma'lumot boshqa hech qayerda chiqmaydi.
    """
    free = max(job.slots_total - taken, 0)
    status_line = {
        JobStatus.OPEN: f"🟢 Bo'sh joy: <b>{free}/{job.slots_total}</b>",
        JobStatus.FULL: "🔴 <b>TO'LDI</b>",
        JobStatus.CLOSED: "⚪️ <b>Yopilgan</b>",
        JobStatus.CANCELLED: "❌ <b>Bekor qilingan</b>",
        JobStatus.PENDING_REVIEW: "🕓 <b>Tekshiruvda</b>",
        JobStatus.DECLINED: "🚫 <b>Rad etilgan</b>",
    }[job.status]

    text = (
        f"💼 <b>{job.title}</b>\n"
        f"<i>{category_name(job.category)}</i>\n\n"
        f"{job.description}\n\n"
        f"📍 Hudud: <b>{job.region}</b>\n"
        f"📅 Sana: <b>{fmt_date(job.work_date)}</b>\n"
        f"🕗 Boshlanish: <b>{job.start_time}</b>\n"
        f"💰 Ish haqi: <b>{money(job.salary)}</b>\n"
        f"👥 Kerak: <b>{job.slots_total} kishi</b>\n"
    )
    if show_slots:
        text += f"{status_line}\n"
        if waitlist:
            text += f"⏳ Navbatda: <b>{waitlist} kishi</b>\n"
    fee_line = (
        "🆓 <b>Yozilish BEPUL</b>" if job.fee <= 0
        else f"🎫 Yozilish to'lovi: <b>{money(job.fee)}</b>"
    )
    text += f"\n{fee_line}\n🆔 <code>#{job.id}</code>"
    if secret:
        text += (
            "\n\n➖➖➖➖➖➖➖➖➖➖\n"
            "🔓 <b>MAXFIY MA'LUMOT</b> (faqat siz uchun):\n\n"
            f"{job.secret_details}"
        )
    return text


def job_row(job: Job, taken: int) -> str:
    """Ro'yxatdagi bitta qator (tugma matni)."""
    free = max(job.slots_total - taken, 0)
    mark = f"🟢{free}" if job.status == JobStatus.OPEN else "🔴"
    tag = " 🆓" if job.fee <= 0 else ""
    return f"{mark}{tag} {short_date(job.work_date)} · {job.title} · {money(job.salary)}"


def payment_instruction(job: Job, minutes: int, card_number: str, card_holder: str) -> str:
    return (
        f"🎫 <b>«{job.title}»</b> ishiga joy band qilindi.\n\n"
        f"⏳ Sizda <b>{minutes} daqiqa</b> vaqt bor. Shu vaqtda chek kelmasa, "
        f"joy avtomat boshqa ishchiga o'tadi.\n\n"
        f"💳 <b>To'lov summasi:</b> {money(job.fee)}\n"
        f"<b>Karta:</b> <code>{card_number}</code>\n"
        f"<b>Karta egasi:</b> {card_holder}\n\n"
        f"📸 To'lovni qilib, <b>chek skrinshotini shu yerga RASM ko'rinishida "
        f"yuboring.</b>\n\n"
        f"⚠️ Fayl emas, rasm qilib yuboring. Chekda summa va vaqt ko'rinsin."
    )


RECEIPT_RECEIVED = (
    "✅ <b>Chek qabul qilindi.</b>\n\n"
    "Administrator tekshirib chiqadi — odatda 5-15 daqiqa. Tasdiqlangach "
    "ish manzili va aloqa raqami shu yerga keladi.\n\n"
    "Joyingiz saqlanib turibdi, xavotir olmang."
)

NOT_A_PHOTO = (
    "❗️ Bu rasm emas. Chekni <b>rasm (photo)</b> ko'rinishida yuboring — "
    "«fayl sifatida yuborish» belgisini olib tashlang."
)


def booking_confirmed(job: Job) -> str:
    if job.fee <= 0:
        head = "🎉 <b>Yozildingiz! Bu ish BEPUL.</b>"
        tail = (
            "\n\n📌 Ishga <b>o'z vaqtida</b> yetib boring.\n"
            "⚠️ Bormasangiz «ishga chiqmadi» deb belgilanadi va bir necha "
            "martadan keyin bepul ishlarga yozila olmaysiz.\n\n"
            "Bora olmasangiz — <b>oldindan bekor qiling</b>, joy boshqa "
            "odamga o'tsin."
        )
    else:
        head = "🎉 <b>To'lovingiz tasdiqlandi!</b>"
        tail = (
            "\n\n📌 Ishga <b>o'z vaqtida</b> yetib boring. Bormasangiz to'lov "
            "qaytarilmaydi va keyingi e'lonlarda cheklov qo'yilishi mumkin."
        )
    return head + "\n\n" + job_card(job, 0, secret=True, show_slots=False) + tail


def booking_rejected(job: Job, reason: str | None) -> str:
    text = f"❌ <b>«{job.title}»</b> ishiga to'lovingiz <b>rad etildi</b>.\n\n"
    if reason:
        text += f"Sabab: <i>{reason}</i>\n\n"
    text += "Joy bo'shatildi. Xato bo'lsa administrator bilan bog'laning."
    return text


def booking_expired(job: Job) -> str:
    return (
        f"⌛️ <b>«{job.title}»</b> ishidagi joyingiz bekor qilindi — "
        f"belgilangan vaqtda chek yubormadingiz.\n\n"
        f"Joy bo'sh bo'lsa qaytadan yozilishingiz mumkin."
    )


def waitlist_joined(job: Job, position: int) -> str:
    return (
        f"⏳ <b>Navbatga yozildingiz.</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)}\n"
        f"🔢 Navbatdagi o'rningiz: <b>{position}</b>\n\n"
        f"<b>Hozircha hech narsa to'lamaysiz.</b> Joy bo'shashi bilan sizga "
        f"birinchi bo'lib xabar beramiz va to'lov uchun vaqt beriladi.\n\n"
        f"Botni o'chirmang — xabar shu yerga keladi."
    )


def waitlist_promoted_free(job: Job) -> str:
    return (
        f"🔔 <b>JOY BO'SHADI — sizniki!</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)} · 🕗 {job.start_time}\n\n"
        f"Bu ish bepul, shuning uchun joy darhol sizga berildi. "
        f"Tafsilotlar pastda 👇"
    )


def waitlist_promoted(job: Job, minutes: int, card_number: str, card_holder: str) -> str:
    return (
        f"🔔 <b>JOY BO'SHADI!</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)} · 🕗 {job.start_time}\n\n"
        f"⏳ Joy sizga <b>{minutes} daqiqaga</b> ushlab turildi.\n\n"
        f"💳 <b>To'lov:</b> {money(job.fee)}\n"
        f"<b>Karta:</b> <code>{card_number}</code>\n"
        f"<b>Karta egasi:</b> {card_holder}\n\n"
        f"📸 Chek skrinshotini shu yerga yuboring."
    )


BOOKING_STATUS_LABEL = {
    BookingStatus.WAITLIST: "⏳ Navbatda",
    BookingStatus.PENDING_PAYMENT: "💳 To'lov kutilyapti",
    BookingStatus.RECEIPT_SENT: "🔎 Tekshiruvda",
    BookingStatus.CONFIRMED: "✅ Tasdiqlangan",
    BookingStatus.COMPLETED: "🏁 Ishga chiqqan",
    BookingStatus.REJECTED: "❌ Rad etilgan",
    BookingStatus.CANCELLED: "🚫 Bekor qilingan",
    BookingStatus.LATE_CANCEL: "⚠️ Kech bekor qilingan",
    BookingStatus.EXPIRED: "⌛️ Vaqti o'tgan",
    BookingStatus.NO_SHOW: "🚷 Ishga chiqmagan",
}


# ================================================================ eslatmalar

def remind_evening(job: Job) -> str:
    return (
        f"⏰ <b>Ertaga ishingiz bor!</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)}\n"
        f"🕗 <b>{job.start_time}</b> da boshlanadi\n"
        f"📍 {job.region}\n\n"
        f"🔒 <b>Manzil:</b>\n{job.secret_details}\n\n"
        f"Bora olmasangiz — <b>hozir bekor qiling</b>, joy boshqa odamga o'tsin. "
        f"«📋 Mening ishlarim» → e'lonni oching."
    )


def remind_soon(job: Job, minutes: int) -> str:
    hours = minutes // 60
    left = f"{hours} soat" if hours else f"{minutes} daqiqa"
    return (
        f"🔔 <b>Ishgacha {left} qoldi!</b>\n\n"
        f"💼 {job.title}\n"
        f"🕗 <b>{job.start_time}</b>\n\n"
        f"🔒 <b>Manzil:</b>\n{job.secret_details}\n\n"
        f"Yo'lga chiqing 🚶"
    )


def ask_attendance(job: Job) -> str:
    return (
        f"❓ <b>Ishga chiqdingizmi?</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)}\n\n"
        f"<i>Rost javob bering — bu sizning ishonchlilik ko'rsatkichingizga "
        f"yoziladi va keyingi ishlarda yordam beradi.</i>"
    )


ATTENDANCE_THANKS = (
    "🏁 Rahmat! Ishga chiqqaningiz belgilandi.\n\n"
    "Ishonchlilik ko'rsatkichingiz oshdi — keyingi e'lonlarda ustunlik beradi."
)
ATTENDANCE_NOSHOW = (
    "📝 Belgilandi: ishga chiqmagansiz.\n\n"
    "Iltimos, keyingi safar bora olmasangiz <b>oldindan bekor qiling</b> — "
    "joy boshqa odamga o'tadi va sizning ko'rsatkichingiz tushmaydi."
)


def cancel_warning(job: Job, minutes_left: int) -> str:
    hours = minutes_left // 60
    left = f"{hours} soat {minutes_left % 60} daqiqa" if hours else f"{minutes_left} daqiqa"
    return (
        f"⚠️ <b>Diqqat!</b>\n\n"
        f"«{job.title}» ishigacha atigi <b>{left}</b> qoldi.\n\n"
        f"Hozir bekor qilsangiz bu <b>«ishga chiqmagan»</b> deb yoziladi — "
        f"chunki bu vaqtda o'rningizga boshqa odam topish qiyin.\n\n"
        f"Baribir bekor qilasizmi?"
    )


CANCEL_LATE_DONE = (
    "⚠️ Bekor qilindi va «ishga chiqmagan» deb belgilandi.\n\n"
    "Aytganingiz uchun rahmat — joy boshqa odamga o'tadi."
)
CANCEL_DONE = "🚫 Bekor qilindi. Joy bo'shatildi."


# ================================================================ referal

def referral_info(link: str, invited: int, credits: int, reward: int) -> str:
    return (
        f"🎁 <b>Do'st chaqiring — bepul ish oling</b>\n\n"
        f"Havolangiz:\n<code>{link}</code>\n\n"
        f"Do'stingiz shu havola orqali kirib <b>birinchi ishga yozilsa</b>, "
        f"sizga <b>{reward} ta bepul yozilish</b> beriladi.\n\n"
        f"👥 Chaqirganlaringiz: <b>{invited}</b>\n"
        f"🎫 Bepul yozilish bonusi: <b>{credits}</b>\n\n"
        f"<i>Bonusni istalgan pulli e'longa ishlatasiz — to'lov qilmasdan.</i>"
    )


def referral_rewarded(friend_name: str, reward: int, total: int) -> str:
    return (
        f"🎁 <b>Bonus oldingiz!</b>\n\n"
        f"{friend_name} siz chaqirgan havola orqali kelib, birinchi ishga "
        f"yozildi.\n\n"
        f"➕ {reward} ta bepul yozilish\n"
        f"🎫 Jami bonusingiz: <b>{total}</b>"
    )


def credit_used(left: int) -> str:
    return (
        f"🎁 <b>Bonus ishlatildi — to'lov qilmadingiz!</b>\n\n"
        f"Qolgan bonus: <b>{left}</b>"
    )


# ================================================================ shikoyat

ASK_REPORT = (
    "🆘 <b>Shikoyat yoki savol</b>\n\n"
    "Muammoni batafsil yozing: qaysi ish, nima bo'ldi.\n\n"
    "<i>Masalan: #12 ishga bordim, manzilda hech kim yo'q edi.</i>\n\n"
    "Bekor qilish: /cancel"
)

REPORT_SENT = (
    "✅ <b>Murojaatingiz qabul qilindi.</b>\n\n"
    "Administrator ko'rib chiqadi va shu yerga javob yozadi."
)


def report_card(report) -> str:  # noqa: ANN001
    job_line = f"💼 E'lon: <b>{report.job.title}</b> (#{report.job.id})\n" if report.job else ""
    return (
        f"🆘 <b>YANGI MUROJAAT</b> <code>#{report.id}</code>\n\n"
        f"👤 {report.user.mention}\n"
        f"📱 <code>{report.user.phone or '—'}</code>\n"
        f"📊 {report.user.reliability}\n"
        f"{job_line}\n"
        f"<b>Matn:</b>\n{report.text}"
    )


ASK_REPORT_ANSWER = (
    "✍️ Javobingizni yozing — foydalanuvchiga shu matn boradi.\n\n"
    "Bekor qilish: /cancel"
)


def report_answer(text: str) -> str:
    return f"💬 <b>Murojaatingizga javob:</b>\n\n{text}"


def my_booking_line(b: Booking) -> str:
    return (
        f"{BOOKING_STATUS_LABEL[b.status]} — <b>{b.job.title}</b>\n"
        f"    📅 {fmt_date(b.job.work_date)} · 🕗 {b.job.start_time} · "
        f"📍 {b.job.region}"
    )


# ================================================================ e'lon yaratish

NEW_JOB_CATEGORY = "📝 <b>1/8 · Ish turi</b>\n\nQaysi sohaga tegishli?"
NEW_JOB_TITLE = (
    "📝 <b>2/8 · Ish nomi</b>\n\n"
    "Qisqa va aniq yozing.\n"
    "<i>Masalan: Omborga yuk tashish</i>"
)
NEW_JOB_DESC = (
    "📝 <b>3/8 · Tavsif</b> — buni <b>hamma ko'radi</b>.\n\n"
    "Nima ish qilinadi, qanday talab bor.\n"
    "❗️ Manzil va telefonni bu yerga YOZMANG — u keyingi qadamda.\n\n"
    "<i>Masalan: Qurilish materiallarini mashinadan tushirish. 8 soat. "
    "Jismonan baquvvat erkaklar kerak. Tushlik beriladi.</i>"
)
NEW_JOB_SECRET = (
    "🔒 <b>4/8 · Maxfiy ma'lumot</b> — faqat <b>to'lov qilganlar</b> ko'radi.\n\n"
    "Aniq manzil, mo'ljal, mas'ul odam va uning telefoni.\n\n"
    "<i>Masalan: Chilonzor 19-kvartal, «Metro» ombori, 3-darvoza. "
    "Mas'ul: Aziz aka, +998 90 123 45 67. Soat 07:45 da darvoza oldida.</i>"
)
NEW_JOB_LOCATION = (
    "🗺 <b>Lokatsiya</b> (ixtiyoriy) — buni ham <b>faqat to'lov qilganlar</b> "
    "ko'radi.\n\n"
    "Xaritadagi aniq nuqtani yuboring: 📎 → <b>Location</b> → xaritada joyni "
    "tanlang → yuboring.\n\n"
    "Ishchi uni bosib «Marshrut» ola oladi — manzil matnidan ancha foydali, "
    "ayniqsa mo'ljal tushunarsiz bo'lsa."
)
NEW_JOB_REGION = "📍 <b>5/8 · Hudud</b>"
NEW_JOB_DATE = "📅 <b>6/8 · Sana</b>\n\nTugmani bosing yoki yozing: <code>05.08.2026</code>"
NEW_JOB_TIME = "🕗 <b>7/8 · Boshlanish vaqti</b>\n\nTugmani bosing yoki yozing: <code>08:00</code>"
NEW_JOB_SALARY = "💰 <b>8/8 · Ishchi oladigan haq</b>\n\nTugmani bosing yoki raqam yozing."
NEW_JOB_SLOTS = "👥 <b>Necha kishi kerak?</b>"
NEW_JOB_FEE = "🎫 <b>Yozilish to'lovi</b>"

NEW_JOB_PUBLISHED = "✅ E'lon joylandi!"
NEW_JOB_SENT_TO_REVIEW = (
    "📨 <b>E'lon administratorga yuborildi.</b>\n\n"
    "Tasdiqlangach kanalda va botda chiqadi, sizga xabar beramiz. "
    "Odatda 10-30 daqiqa."
)
NEW_JOB_CANCELLED = "🚫 E'lon bekor qilindi."

BAD_NUMBER = "❗️ Faqat raqam kiriting. <i>Masalan: 200000</i>"
BAD_DATE = "❗️ Sanani tushunmadim. <code>05.08.2026</code> ko'rinishida yozing."
BAD_TIME = "❗️ Vaqtni <code>08:00</code> ko'rinishida yozing."
TOO_SHORT = "❗️ Juda qisqa. Kamida {n} ta harf yozing."

PAYMENT_NOT_READY = (
    "⚠️ <b>Karta rekvizitlari sozlanmagan.</b>\n\n"
    "E'lon berishdan oldin «⚙️ Sozlamalar» → «💳 Karta» dan karta raqami va "
    "egasining ismini kiriting. Aks holda ishchilar to'lovni qayerga "
    "qilishini bilmaydi."
)


# ================================================================ admin

ADMIN_WELCOME = "🛠 <b>Admin panel</b>"


def moderation_caption(b: Booking, taken: int) -> str:
    return (
        f"💳 <b>YANGI TO'LOV CHEKI</b>\n\n"
        f"👤 {b.user.mention}\n"
        f"📱 <code>{b.user.phone}</code>\n"
        f"📍 {b.user.region} · {b.user.reliability}\n\n"
        f"💼 <b>{b.job.title}</b> (#{b.job.id})\n"
        f"📅 {fmt_date(b.job.work_date)} · 🕗 {b.job.start_time}\n"
        f"🎫 Summa: <b>{money(b.job.fee)}</b>\n"
        f"👥 Band: <b>{taken}/{b.job.slots_total}</b>\n\n"
        f"🆔 Ariza: <code>#{b.id}</code>"
    )


def job_review_caption(job: Job, author: User) -> str:
    return (
        "🕓 <b>YANGI E'LON — TASDIQ KUTILYAPTI</b>\n\n"
        f"👤 {author.mention}\n"
        f"📱 <code>{author.phone}</code>\n\n"
        + job_card(job, 0, secret=True, show_slots=False)
    )


ASK_REJECT_REASON = (
    "✍️ Rad etish sababini yozing (ishchiga shu matn boradi).\n\n"
    "Sababsiz o'tkazish uchun /skip"
)
ASK_DECLINE_REASON = (
    "✍️ E'lonni rad etish sababini yozing (muallifga boradi).\n\n"
    "Sababsiz o'tkazish uchun /skip"
)


# ================================================================ sozlamalar

def settings_view(
    channel: str, moderation: str, card: str, holder: str, fee: int,
    hold: int, wait: int, free_mode: bool, no_show: int,
) -> str:
    mode = (
        "🆓 <b>BEPUL REJIM</b> — yangi e'lonlar avtomat bepul bo'ladi.\n"
        "<i>Auditoriya yig'ish bosqichi uchun. Pulli rejimga o'tganda "
        "eski e'lonlarga tegilmaydi.</i>"
        if free_mode else
        "💳 <b>PULLI REJIM</b> — yangi e'lonlarda yozilish to'lovi so'raladi.\n"
        "<i>Har bir e'lonni alohida bepul qilish mumkin.</i>"
    )
    return (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"{mode}\n\n"
        f"📢 <b>Kanallar:</b> {channel}\n"
        f"👮 <b>Moderatsiya chati:</b> {moderation}\n\n"
        f"💳 <b>Karta:</b> <code>{card}</code>\n"
        f"👤 <b>Karta egasi:</b> {holder}\n"
        f"🎫 <b>Standart to'lov:</b> {money(fee)}\n\n"
        f"⏳ <b>Bron muddati:</b> {hold} daqiqa\n"
        f"🔔 <b>Navbatdan keyingi muddat:</b> {wait} daqiqa\n"
        f"🚷 <b>No-show limiti:</b> {no_show if no_show else 'yo‘q'} "
        f"<i>(bepul ishlar uchun)</i>"
    )


def daily_report(s: dict, day: str) -> str:
    """Kunlik hisobot — kechqurun adminlarga.

    Eng qimmatli qismi oxirida: ERTANGI to'lmagan joylar. Bu bugun
    kechqurun nima qilish kerakligini aytadi.
    """
    total_marked = s["completed"] + s["no_show"]
    rate = f"{s['completed'] * 100 // total_marked}%" if total_marked else "—"

    text = (
        f"📊 <b>Kunlik hisobot · {day}</b>\n\n"
        f"👤 Yangi foydalanuvchi: <b>{s['new_users']}</b>\n"
        f"📢 Yangi e'lon: <b>{s['new_jobs']}</b>\n"
        f"✅ Tasdiqlangan yozilish: <b>{s['confirmed']}</b>\n"
        f"❌ Rad etilgan: {s['rejected']}\n"
        f"🏁 Ishga chiqqan: {s['completed']} · 🚷 chiqmagan: {s['no_show']} "
        f"(<b>{rate}</b>)\n"
        f"💰 Tushum: <b>{money(s['revenue'])}</b>\n"
    )

    if s["waiting"] or s["review_jobs"]:
        text += "\n⚠️ <b>E'tibor kerak:</b>\n"
        if s["waiting"]:
            text += f"🔎 {s['waiting']} ta chek tekshirilmagan\n"
        if s["review_jobs"]:
            text += f"🕓 {s['review_jobs']} ta e'lon tasdiq kutmoqda\n"

    gaps = s["gaps"]
    if gaps:
        text += f"\n🔔 <b>Ertaga to'lmagan joylar ({len(gaps)} e'lon):</b>\n"
        for job, free in gaps[:10]:
            text += f"• {job.title} — <b>{free}</b> joy · {job.start_time} · {job.region}\n"
        if len(gaps) > 10:
            text += f"<i>…va yana {len(gaps) - 10} ta</i>\n"
        text += "\n<i>Reklama tarqatib yoki bepul qilib to'ldirishingiz mumkin.</i>"
    else:
        text += "\n✅ Ertangi barcha e'lonlar to'lgan."

    return text


ASK_NO_SHOW = (
    "🚷 <b>No-show limiti</b>\n\n"
    "Bepul ishga yozilib, necha marta chiqmaganidan keyin odam bepul "
    "ishlarga yozila olmasin?\n\n"
    "<i>Pulli ishlarga bu cheklov qo'llanmaydi — u yerda odam puli ketgani "
    "uchun baribir boradi.</i>\n\n"
    "0 = cheklov yo'q. Tavsiya: 2"
)


def free_mode_switched(on: bool) -> str:
    if on:
        return (
            "🆓 <b>Bepul rejim yoqildi.</b>\n\n"
            "Endi yangi e'lonlar avtomat bepul bo'ladi va ishchilar chek "
            "yubormasdan darhol ish tafsilotlarini oladi.\n\n"
            "Allaqachon joylangan e'lonlarga tegilmadi."
        )
    return (
        "💳 <b>Pulli rejim yoqildi.</b>\n\n"
        "Endi yangi e'lonlarda yozilish to'lovi so'raladi. Karta "
        "rekvizitlari to'ldirilganiga ishonch hosil qiling.\n\n"
        "Allaqachon joylangan bepul e'lonlar bepulligicha qoladi — "
        "kerak bo'lsa har birini alohida pulli qilishingiz mumkin."
    )


CONNECT_CHANNEL = (
    "📢 <b>Kanal/guruh qo'shish</b>\n\n"
    "<b>Eng oson yo'l:</b> botni kanalga <b>administrator</b> qilib qo'shing "
    "(«Xabar joylash» + «Xabarlarni tahrirlash») — bot o'zi sizga tugma "
    "yuboradi.\n\n"
    "<b>Yoki:</b> o'sha kanaldagi istalgan xabarni <b>shu yerga forward "
    "qiling</b>, yoki <code>@kanal_nomi</code> deb yozing.\n\n"
    "<b>Guruh uchun:</b> guruhda <code>/id</code> yozing va chiqqan raqamni "
    "shu yerga yuboring.\n\n"
    "Bekor qilish: /cancel"
)

CONNECT_MODERATION = (
    "👮 <b>Moderatsiya chatini ulash</b>\n\n"
    "To'lov cheklari shu chatga tushadi va istalgan admin tasdiqlay oladi.\n\n"
    "<b>Eng oson yo'l:</b> guruh yarating va <b>botni qo'shing</b> — bot "
    "o'zi sizga «shu chatni ishlataymi?» degan tugma yuboradi.\n\n"
    "<b>Yoki:</b> o'sha guruhda <code>/id</code> yozing va chiqqan raqamni "
    "shu yerga yuboring.\n\n"
    "Bo'sh qoldirsangiz cheklar to'g'ridan-to'g'ri sizga keladi.\n\n"
    "Bekor qilish: /cancel"
)

FORWARD_NOT_RECOGNIZED = (
    "❗️ Chatni aniqlay olmadim.\n\n"
    "<b>Kanal uchun:</b> kanaldagi xabarni «Forward» qilib shu yerga yuboring, "
    "yoki <code>@kanal_nomi</code> deb yozing.\n\n"
    "<b>Guruh uchun:</b> Telegram forward'da guruh nomini bermaydi. "
    "Guruhda <code>/id</code> yozing va chiqqan raqamni shu yerga yuboring.\n\n"
    "Bekor qilish: /cancel"
)

CHANNELS_EMPTY = (
    "📢 <b>Kanallar</b>\n\n"
    "Hali kanal ulanmagan — e'lonlar faqat bot ichida ko'rinadi.\n\n"
    "Bir nechta kanal/guruh ulashingiz mumkin va har biriga <b>filtr</b> "
    "qo'yishingiz mumkin: masalan «Chilonzor ishlari» kanaliga faqat "
    "Chilonzor e'lonlari boradi."
)


def channels_view(count: int, active: int) -> str:
    return (
        f"📢 <b>Kanallar: {count} ta</b> (faol: {active})\n\n"
        f"Har biriga hudud va kasb filtri qo'yish mumkin — shunda bir odam "
        f"bitta e'lonni bir necha kanalda takror ko'rmaydi.\n\n"
        f"Sozlash uchun tanlang 👇"
    )


def channel_view(title: str, chat_id: int, active: bool, regions: str, cats: str, posts: int) -> str:
    return (
        f"{'🟢 Faol' if active else '⚪️ To‘xtatilgan'} · <b>{title}</b>\n"
        f"ID: <code>{chat_id}</code>\n\n"
        f"📍 Hududlar: {regions}\n"
        f"🧰 Kasblar: {cats}\n"
        f"📄 Joylangan e'lonlar: {posts}"
    )


STAFF_EMPTY = (
    "🛡 <b>Moderatorlar</b>\n\n"
    "Hali moderator yo'q. Moderator quyidagilarni qila oladi:\n"
    "• to'lov cheklarini tasdiqlash/rad etish\n"
    "• e'lon joylash va yopish\n"
    "• yozilganlarni ko'rish, ishga chiqqanini belgilash\n\n"
    "Moderator <b>sozlamalarni</b>, <b>moliyaviy statistikani</b> va "
    "<b>foydalanuvchilarni bloklashni</b> ko'ra olmaydi."
)

ASK_STAFF = (
    "🛡 <b>Moderator qo'shish</b>\n\n"
    "Uning Telegram ID sini yoki @username ini yuboring.\n\n"
    "❗️ Muhim: u avval botga <code>/start</code> yozgan bo'lishi kerak, "
    "aks holda bazada topilmaydi.\n\n"
    "Bekor qilish: /cancel"
)

ASK_CARD_NUMBER = "💳 Karta raqamini yuboring.\n\n<i>Masalan: 8600 1234 5678 9012</i>"
ASK_CARD_HOLDER = "👤 Karta egasining ism-familiyasini yuboring."
ASK_FEE = "🎫 Standart yozilish to'lovini yozing (so'mda).\n\n<i>Masalan: 10000</i>"
ASK_HOLD = "⏳ Bron muddatini yozing (daqiqada, 3-120).\n\n<i>Masalan: 15</i>"
SAVED = "✅ Saqlandi."
