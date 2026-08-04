"""Русский перевод — то, что видит РАБОТНИК.

Админ-панель остаётся на узбекском: ею пользуетесь вы и модераторы.
Если какого-то имени здесь нет, `bot/texts.py` автоматически возьмёт
узбекский вариант — пустого места никогда не будет.
"""

from __future__ import annotations

from datetime import date

from bot.config import category_name
from bot.db.models import Booking, BookingStatus, Job, JobStatus
from bot.utils import local_today

WEEKDAYS = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def money(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " сум"


def fmt_date(d: date) -> str:
    delta = (d - local_today()).days
    if delta == 0:
        return f"Сегодня, {d.day} {MONTHS[d.month - 1]}"
    if delta == 1:
        return f"Завтра, {d.day} {MONTHS[d.month - 1]}"
    return f"{d.day} {MONTHS[d.month - 1]} ({WEEKDAYS[d.weekday()]})"


def short_date(d: date) -> str:
    delta = (d - local_today()).days
    if delta == 0:
        return "Сегодня"
    if delta == 1:
        return "Завтра"
    return f"{d.day}.{d.month:02d}"


# ================================================================ общее

CHOOSE_ROLE = (
    "👋 <b>Здравствуйте!</b>\n\n"
    "Через этого бота вы найдёте <b>подённую работу</b> или <b>наймёте "
    "работников</b>.\n\n"
    "Кто вы?"
)

START_WORKER = (
    "🔎 Продолжаем как <b>соискатель</b>.\n\n"
    "Как это работает:\n"
    "1️⃣ Выбираете подходящее объявление\n"
    "2️⃣ Оплачиваете запись и отправляете скриншот чека\n"
    "3️⃣ После подтверждения получаете адрес и контакты\n\n"
    "Для начала отправьте свой номер телефона 👇"
)

START_EMPLOYER = (
    "🏢 Продолжаем как <b>работодатель</b>.\n\n"
    "Вы размещаете объявление — мы находим работников. Объявление "
    "публикуется после проверки администратором.\n\n"
    "Для начала отправьте свой номер телефона 👇"
)

ASK_PHONE_BUTTON_ONLY = (
    "❗️ Не пишите номер вручную — нажмите кнопку "
    "<b>«📱 Отправить номер»</b> внизу. Это нужно, чтобы проверить, что "
    "номер настоящий."
)
ASK_REGION = "📍 В каком районе ищете работу? По нему отфильтруем объявления."
ASK_CATEGORIES = (
    "🧰 <b>Какая работа вам интересна?</b>\n\n"
    "По выбранным категориям будем сразу сообщать о новых объявлениях.\n"
    "Можно выбрать несколько. Если ничего не выбрать — придут все."
)

REGISTERED_WORKER = (
    "✅ <b>Готово!</b>\n\n"
    "Нажмите «🔎 Поиск работы», чтобы посмотреть открытые объявления."
)
REGISTERED_EMPLOYER = (
    "✅ <b>Готово!</b>\n\n"
    "Нажмите «➕ Разместить работу», чтобы создать первое объявление."
)

MAIN_MENU = "🏠 Главное меню"
BLOCKED = "🚫 Ваш аккаунт заблокирован. По поводу причины свяжитесь с администратором."
TOO_FAST = "⏳ Чуть помедленнее, пожалуйста."

NO_JOBS = (
    "😔 По этому фильтру объявлений нет.\n\n"
    "Попробуйте расширить фильтр или подождите — как только появится "
    "новое объявление, мы сообщим."
)


# ================================================================ объявление

def job_card(
    job: Job,
    taken: int,
    *,
    secret: bool = False,
    show_slots: bool = True,
    waitlist: int = 0,
) -> str:
    free = max(job.slots_total - taken, 0)
    status_line = {
        JobStatus.OPEN: f"🟢 Свободных мест: <b>{free}/{job.slots_total}</b>",
        JobStatus.FULL: "🔴 <b>МЕСТ НЕТ</b>",
        JobStatus.CLOSED: "⚪️ <b>Закрыто</b>",
        JobStatus.CANCELLED: "❌ <b>Отменено</b>",
        JobStatus.PENDING_REVIEW: "🕓 <b>На проверке</b>",
        JobStatus.DECLINED: "🚫 <b>Отклонено</b>",
    }[job.status]

    text = (
        f"💼 <b>{job.title}</b>\n"
        f"<i>{category_name(job.category)}</i>\n\n"
        f"{job.description}\n\n"
        f"📍 Район: <b>{job.region}</b>\n"
        f"📅 Дата: <b>{fmt_date(job.work_date)}</b>\n"
        f"🕗 Начало: <b>{job.start_time}</b>\n"
        f"💰 Оплата: <b>{money(job.salary)}</b>\n"
        f"👥 Нужно: <b>{job.slots_total} чел.</b>\n"
    )
    if show_slots:
        text += f"{status_line}\n"
        if waitlist:
            text += f"⏳ В очереди: <b>{waitlist} чел.</b>\n"

    fee_line = (
        "🆓 <b>Запись БЕСПЛАТНО</b>" if job.fee <= 0
        else f"🎫 Плата за запись: <b>{money(job.fee)}</b>"
    )
    text += f"\n{fee_line}\n🆔 <code>#{job.id}</code>"

    if secret:
        text += (
            "\n\n➖➖➖➖➖➖➖➖➖➖\n"
            "🔓 <b>ЗАКРЫТАЯ ИНФОРМАЦИЯ</b> (только для вас):\n\n"
            f"{job.secret_details}"
        )
    return text


def job_row(job: Job, taken: int) -> str:
    free = max(job.slots_total - taken, 0)
    mark = f"🟢{free}" if job.status == JobStatus.OPEN else "🔴"
    tag = " 🆓" if job.fee <= 0 else ""
    return f"{mark}{tag} {short_date(job.work_date)} · {job.title} · {money(job.salary)}"


def payment_instruction(job: Job, minutes: int, card_number: str, card_holder: str) -> str:
    return (
        f"🎫 Место на работе <b>«{job.title}»</b> забронировано.\n\n"
        f"⏳ У вас <b>{minutes} минут</b>. Если чек не придёт за это время, "
        f"место автоматически перейдёт другому.\n\n"
        f"💳 <b>Сумма:</b> {money(job.fee)}\n"
        f"<b>Карта:</b> <code>{card_number}</code>\n"
        f"<b>Владелец карты:</b> {card_holder}\n\n"
        f"📸 Оплатите и отправьте <b>скриншот чека сюда КАРТИНКОЙ.</b>\n\n"
        f"⚠️ Не файлом, а картинкой. На чеке должны быть видны сумма и время."
    )


RECEIPT_RECEIVED = (
    "✅ <b>Чек принят.</b>\n\n"
    "Администратор проверит — обычно 5–15 минут. После подтверждения адрес "
    "и контакты придут сюда.\n\n"
    "Ваше место сохраняется, не волнуйтесь."
)

NOT_A_PHOTO = (
    "❗️ Это не картинка. Отправьте чек <b>картинкой (photo)</b> — снимите "
    "галочку «отправить файлом»."
)


def booking_confirmed(job: Job) -> str:
    if job.fee <= 0:
        head = "🎉 <b>Вы записаны! Эта работа БЕСПЛАТНА.</b>"
        tail = (
            "\n\n📌 Приходите <b>вовремя</b>.\n"
            "⚠️ Если не придёте — отметим как «не вышел», и после нескольких "
            "раз бесплатные работы станут недоступны.\n\n"
            "Не сможете прийти — <b>отмените заранее</b>, место достанется "
            "другому."
        )
    else:
        head = "🎉 <b>Оплата подтверждена!</b>"
        tail = (
            "\n\n📌 Приходите <b>вовремя</b>. Если не придёте, оплата не "
            "возвращается и в дальнейшем возможны ограничения."
        )
    return head + "\n\n" + job_card(job, 0, secret=True, show_slots=False) + tail


def booking_rejected(job: Job, reason: str | None) -> str:
    text = f"❌ Оплата за работу <b>«{job.title}»</b> <b>отклонена</b>.\n\n"
    if reason:
        text += f"Причина: <i>{reason}</i>\n\n"
    text += "Место освобождено. Если это ошибка — свяжитесь с администратором."
    return text


def booking_expired(job: Job) -> str:
    return (
        f"⌛️ Ваше место на работе <b>«{job.title}»</b> отменено — чек не был "
        f"отправлен вовремя.\n\n"
        f"Если места ещё есть, вы можете записаться заново."
    )


def waitlist_joined(job: Job, position: int) -> str:
    return (
        f"⏳ <b>Вы в очереди.</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)}\n"
        f"🔢 Ваше место в очереди: <b>{position}</b>\n\n"
        f"<b>Сейчас вы ничего не платите.</b> Как только освободится место, "
        f"мы сообщим вам первому и дадим время на оплату.\n\n"
        f"Не удаляйте бота — сообщение придёт сюда."
    )


def waitlist_promoted_free(job: Job) -> str:
    return (
        f"🔔 <b>МЕСТО ОСВОБОДИЛОСЬ — оно ваше!</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)} · 🕗 {job.start_time}\n\n"
        f"Работа бесплатная, поэтому место сразу за вами. Подробности ниже 👇"
    )


def waitlist_promoted(job: Job, minutes: int, card_number: str, card_holder: str) -> str:
    return (
        f"🔔 <b>МЕСТО ОСВОБОДИЛОСЬ!</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)} · 🕗 {job.start_time}\n\n"
        f"⏳ Место держим за вами <b>{minutes} минут</b>.\n\n"
        f"💳 <b>Оплата:</b> {money(job.fee)}\n"
        f"<b>Карта:</b> <code>{card_number}</code>\n"
        f"<b>Владелец:</b> {card_holder}\n\n"
        f"📸 Отправьте скриншот чека сюда."
    )


BOOKING_STATUS_LABEL = {
    BookingStatus.WAITLIST: "⏳ В очереди",
    BookingStatus.PENDING_PAYMENT: "💳 Ожидается оплата",
    BookingStatus.RECEIPT_SENT: "🔎 На проверке",
    BookingStatus.CONFIRMED: "✅ Подтверждено",
    BookingStatus.COMPLETED: "🏁 Вышел на работу",
    BookingStatus.REJECTED: "❌ Отклонено",
    BookingStatus.CANCELLED: "🚫 Отменено",
    BookingStatus.LATE_CANCEL: "⚠️ Поздняя отмена",
    BookingStatus.EXPIRED: "⌛️ Время истекло",
    BookingStatus.NO_SHOW: "🚷 Не вышел",
}


def my_booking_line(b: Booking) -> str:
    return (
        f"{BOOKING_STATUS_LABEL[b.status]} — <b>{b.job.title}</b>\n"
        f"    📅 {fmt_date(b.job.work_date)} · 🕗 {b.job.start_time} · "
        f"📍 {b.job.region}"
    )


# ================================================================ напоминания

def remind_evening(job: Job) -> str:
    return (
        f"⏰ <b>Завтра у вас работа!</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)}\n"
        f"🕗 Начало в <b>{job.start_time}</b>\n"
        f"📍 {job.region}\n\n"
        f"🔒 <b>Адрес:</b>\n{job.secret_details}\n\n"
        f"Если не сможете прийти — <b>отмените сейчас</b>, место достанется "
        f"другому. «📋 Мои работы» → откройте объявление."
    )


def remind_soon(job: Job, minutes: int) -> str:
    hours = minutes // 60
    left = f"{hours} ч." if hours else f"{minutes} мин."
    return (
        f"🔔 <b>До работы осталось {left}!</b>\n\n"
        f"💼 {job.title}\n"
        f"🕗 <b>{job.start_time}</b>\n\n"
        f"🔒 <b>Адрес:</b>\n{job.secret_details}\n\n"
        f"Выезжайте 🚶"
    )


def ask_attendance(job: Job) -> str:
    return (
        f"❓ <b>Вы вышли на работу?</b>\n\n"
        f"💼 {job.title}\n"
        f"📅 {fmt_date(job.work_date)}\n\n"
        f"<i>Ответьте честно — это записывается в вашу надёжность и "
        f"помогает при следующих работах.</i>"
    )


ATTENDANCE_THANKS = (
    "🏁 Спасибо! Отметили, что вы вышли на работу.\n\n"
    "Ваш показатель надёжности вырос — это даёт преимущество в следующих "
    "объявлениях."
)
ATTENDANCE_NOSHOW = (
    "📝 Отмечено: вы не вышли на работу.\n\n"
    "В следующий раз, если не сможете прийти, пожалуйста, <b>отмените "
    "заранее</b> — место достанется другому, а ваш показатель не пострадает."
)


def cancel_warning(job: Job, minutes_left: int) -> str:
    hours = minutes_left // 60
    left = f"{hours} ч. {minutes_left % 60} мин." if hours else f"{minutes_left} мин."
    return (
        f"⚠️ <b>Внимание!</b>\n\n"
        f"До работы «{job.title}» осталось всего <b>{left}</b>.\n\n"
        f"Если отменить сейчас, это будет записано как <b>«не вышел»</b> — "
        f"за такое время найти замену сложно.\n\n"
        f"Всё равно отменить?"
    )


CANCEL_LATE_DONE = (
    "⚠️ Отменено и записано как «не вышел».\n\n"
    "Спасибо, что предупредили — место достанется другому."
)
CANCEL_DONE = "🚫 Отменено. Место освобождено."


# ================================================================ рефералы

def referral_info(link: str, invited: int, credits: int, reward: int) -> str:
    return (
        f"🎁 <b>Пригласите друга — получите бесплатную запись</b>\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Когда друг перейдёт по ней и <b>запишется на первую работу</b>, "
        f"вы получите <b>{reward} бесплатных записей</b>.\n\n"
        f"👥 Приглашено: <b>{invited}</b>\n"
        f"🎫 Бонусов: <b>{credits}</b>\n\n"
        f"<i>Бонус можно потратить на любое платное объявление — без оплаты.</i>"
    )


def referral_rewarded(friend_name: str, reward: int, total: int) -> str:
    return (
        f"🎁 <b>Вы получили бонус!</b>\n\n"
        f"{friend_name} перешёл по вашей ссылке и записался на первую работу.\n\n"
        f"➕ {reward} бесплатных записей\n"
        f"🎫 Всего бонусов: <b>{total}</b>"
    )


def credit_used(left: int) -> str:
    return (
        f"🎁 <b>Бонус использован — вы ничего не платите!</b>\n\n"
        f"Осталось бонусов: <b>{left}</b>"
    )


# ================================================================ обращения

ASK_REPORT = (
    "🆘 <b>Жалоба или вопрос</b>\n\n"
    "Опишите проблему подробно: какая работа, что произошло.\n\n"
    "<i>Например: пришёл на работу #12, по адресу никого не было.</i>\n\n"
    "Отмена: /cancel"
)

REPORT_SENT = (
    "✅ <b>Ваше обращение принято.</b>\n\n"
    "Администратор рассмотрит и ответит здесь."
)


def report_answer(text: str) -> str:
    return f"💬 <b>Ответ на ваше обращение:</b>\n\n{text}"
