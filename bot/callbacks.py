"""Inline tugmalar uchun callback ma'lumotlari.

Nega oddiy matn ("apply_12") emas? aiogram ning CallbackData klassi tugma
ma'lumotini avtomat yig'adi/ajratadi va turini tekshiradi. Qo'lda split("_")
qilib yurish — eng ko'p xato chiqadigan joy.

Telegram callback ma'lumoti uchun 64 bayt beradi, shuning uchun prefikslar
qisqa.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class JobCB(CallbackData, prefix="j"):
    action: str  # view | apply | credit | wait | cancel | cancelyes | report
    job_id: int


class AttendCB(CallbackData, prefix="at"):
    """Ish tugagach: «chiqdingizmi?» so'roviga javob."""

    action: str  # yes | no
    booking_id: int


class ReportCB(CallbackData, prefix="rp"):
    action: str  # answer | close
    report_id: int


class FeedCB(CallbackData, prefix="f"):
    """Ishchi ro'yxatidagi navigatsiya va filtr.

    DIQQAT: `value` ixtiyoriy, shuning uchun turi `str | None`.
    Ilgari u `str = ""` edi va bu jimgina buzuq tugmalar yasardi:
    FeedCB(action="reset") -> "f:reset::0" bo'lib qadoqlanardi, lekin
    ochilayotganda o'rtadagi bo'sh bo'lak None bo'lib qaytadi va pydantic
    uni `str` deb qabul qilmasdi. Natijada «♻️ Filtrni tozalash» va
    sahifalash tugmalari HAR DOIM «Xatolik yuz berdi» berardi.

    Shu sabab wiring_test barcha tugmalarni qadoqlab-ochib tekshiradi.
    """

    action: str  # page | filter | setreg | setcat | setday | reset | open
    value: str | None = None
    page: int = 0


class ModCB(CallbackData, prefix="m"):
    action: str  # ok | no | undo
    booking_id: int


class RejCB(CallbackData, prefix="rj"):
    """Rad etishning tayyor sababi — guruhda matn yozish shart bo'lmasin."""

    key: str  # fake | amount | old | notfound | other | back
    booking_id: int


class JobModCB(CallbackData, prefix="jm"):
    """Ish beruvchi yuborgan e'lonni tasdiqlash/rad etish."""

    action: str  # ok | no
    job_id: int


class AdminJobCB(CallbackData, prefix="aj"):
    action: str  # view | close | reopen | workers | clone | repost | edit | cancel | fee
    job_id: int


class JobEditCB(CallbackData, prefix="je"):
    """Joylangan e'lonning bitta maydonini tahrirlash."""

    field: str
    job_id: int


class WorkerCB(CallbackData, prefix="w"):
    action: str  # noshow | done | block
    booking_id: int


class PickCB(CallbackData, prefix="p"):
    """E'lon yaratish/ro'yxatdan o'tishdagi tanlov tugmalari."""

    field: str
    value: str


class EditCB(CallbackData, prefix="e"):
    """Oldindan ko'rishdan aniq bir maydonni tahrirlash."""

    field: str


class SetCB(CallbackData, prefix="s"):
    """Sozlamalar menyusi."""

    action: str


class ChanCB(CallbackData, prefix="ch"):
    """Kanallar ro'yxatini boshqarish."""

    action: str  # view | toggle | del | regions | cats | test | clear
    channel_id: int


class StaffCB(CallbackData, prefix="st"):
    """Moderatorlarni boshqarish."""

    action: str  # demote
    user_id: int


class UserCB(CallbackData, prefix="u"):
    """Bitta foydalanuvchi ustidagi amallar."""

    action: str  # view | block | unblock | mod | unmod
    user_id: int


class UsersCB(CallbackData, prefix="ul"):
    """Foydalanuvchilar ro'yxati: sahifalash va filtr."""

    action: str  # page | search | blocked | all
    page: int = 0


class ChatCB(CallbackData, prefix="c"):
    """Bot yangi chatga qo'shilganda: uni kanal yoki moderatsiya chati
    sifatida belgilash, yoki o'sha chatdan chiqarib yuborish."""

    kind: str  # channel | moderation | leave
    chat_id: int


class RateCB(CallbackData, prefix="rt"):
    """Ish yakunida 1-5 baho.

    kind: "e" — ishchi ish beruvchini, "w" — ish beruvchi ishchini baholaydi.
    ref: kind="e" da job_id (kim baholanishi ish muallifidan topiladi),
         kind="w" da booking_id (undan ishchi va ish topiladi).
    stars=0 — «o'tkazib yuborish».
    """

    kind: str  # e | w
    ref: int
    stars: int


class PubCB(CallbackData, prefix="pb"):
    """E'lonni kanallarga joylash tanlovi: mos / barcha / qo'lda / joylamaslik.

    value ko'p vazifali: auto/all/skip/pick da «tarqatish kerakmi» belgisi
    (1 — obunachilarga ham yuboriladi, 0 — faqat kanallar, masalan qayta
    joylashda), t da kanal ID, page da sahifa raqami.
    """

    action: str  # auto | all | pick | skip | t | page | done
    job_id: int
    value: int = 0


class LogCB(CallbackData, prefix="lg"):
    """Moderator harakatlari jurnalini varaqlash."""

    page: int = 0


class ChanListCB(CallbackData, prefix="chl"):
    """Kanallar ro'yxatini varaqlash (40-50 kanal sig'ishi uchun)."""

    page: int = 0


class RestoreCB(CallbackData, prefix="rs"):
    """Bazani tiklash tasdig'i. Qaytarib bo'lmaydigan amal — shuning
    uchun alohida, tasodifan bosilmaydigan tugma."""

    action: str  # yes | no


class ProfCB(CallbackData, prefix="pr"):
    """Profil sozlamalari tugmalari.

    Ilgari bu amallar faqat buyruq orqali ishlardi (/til, /kasb, /dost…):
    odam profil matnidagi ro'yxatni o'qib, buyruqni QO'LDA yozishi kerak
    edi. Telefonda bu noqulay va ko'pchilik topmasdi ham.
    """

    action: str  # lang | region | cats | notify | invite | complain | role | help


class NavCB(CallbackData, prefix="n"):
    to: str  # menu | feed | mybookings | admin | noop
