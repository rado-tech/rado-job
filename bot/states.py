"""FSM holatlari — ko'p qadamli suhbatlar.

aiogram foydalanuvchining "hozir qaysi qadamda turgani"ni shu holatlar orqali
eslab qoladi. Shuning uchun "chek yubor" bilan "e'lon nomini yoz" bir-biriga
aralashib ketmaydi.
"""

from aiogram.fsm.state import State, StatesGroup


class Reg(StatesGroup):
    lang = State()
    role = State()
    phone = State()
    region = State()
    categories = State()


class NewJob(StatesGroup):
    category = State()
    title = State()
    description = State()
    secret = State()
    location = State()
    region = State()
    work_date = State()
    start_time = State()
    salary = State()
    slots = State()
    fee = State()
    preview = State()


class CloneJob(StatesGroup):
    """Eski e'lonni takrorlash — faqat sana so'raladi."""

    work_date = State()


class EditJob(StatesGroup):
    """Joylangan e'lonning bitta maydonini tahrirlash."""

    value = State()
    cancel_reason = State()
    message = State()


class Pay(StatesGroup):
    receipt = State()


class Moderation(StatesGroup):
    reject_reason = State()
    decline_reason = State()


class Setup(StatesGroup):
    channel = State()
    moderation = State()
    card_number = State()
    card_holder = State()
    fee = State()
    hold = State()
    no_show = State()
    backup_chat = State()
    add_staff = State()
    channel_regions = State()
    channel_categories = State()


class Ad(StatesGroup):
    """Reklama tarqatish."""

    content = State()
    button = State()
    audience = State()
    pick = State()
    confirm = State()


class Search(StatesGroup):
    user_query = State()


class ReportFlow(StatesGroup):
    text = State()
    answer = State()
