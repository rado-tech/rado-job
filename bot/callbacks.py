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
    """Ishchi ro'yxatidagi navigatsiya va filtr."""

    action: str  # page | filter | setreg | setcat | setday | reset | open
    value: str = ""
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


class ChatCB(CallbackData, prefix="c"):
    """Bot yangi chatga qo'shilganda: uni kanal yoki moderatsiya chati
    sifatida belgilash, yoki o'sha chatdan chiqarib yuborish."""

    kind: str  # channel | moderation | leave
    chat_id: int


class NavCB(CallbackData, prefix="n"):
    to: str  # menu | feed | mybookings | admin | noop
