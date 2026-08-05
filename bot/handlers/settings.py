"""«⚙️ Sozlamalar» — kanallar, moderatorlar, karta, summalar, zaxira.

Faqat ADMIN uchun (moderatorlar bu bo'limni ko'rmaydi).

Eng muhim g'oya: chat ID sini QO'LDA yozdirmaslik. Bot kanalga qo'shilganda
uni o'zi aniqlaydi. Qo'lda yozishda uchraydigan xatolar (noto'g'ri raqam,
guruh supergruppaga aylangani, `-100` prefiksini unutish) yo'qoladi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.callbacks import ChanCB, ChatCB, PickCB, SetCB, StaffCB
from bot.config import CATEGORY_NAMES
from bot.db.base import integrity_check
from bot.db.models import STAFF_ROLES, Channel, JobPost, Role, User
from bot.keyboards import (
    BTN_SETTINGS,
    single_chat_kb,
    admin_menu,
    category_options,
    channel_kb,
    channels_kb,
    multi_pick_kb,
    region_options,
    settings_kb,
    staff_kb,
)
from bot.permissions import IsAdmin, is_owner
from bot.services import backup, channels as ch, health, jobs as svc, publisher
from bot.services import settings_store as store
from bot.states import Setup
from bot.utils import parse_int

log = logging.getLogger(__name__)
router = Router(name="settings")

router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _view(session: AsyncSession) -> str:
    all_ch = await ch.all_channels(session)
    active = sum(1 for c in all_ch if c.is_active)
    channel_line = f"{len(all_ch)} ta ({active} faol)" if all_ch else "❌ ulanmagan"
    mod = store.get("moderation_chat_title") or store.get("moderation_chat_id")
    backup_line = store.get("backup_chat_title") or store.get("backup_chat_id")
    return texts.settings_view(
        channel=channel_line,
        moderation=f"🟢 {mod}" if mod else "❌ ulanmagan (cheklar adminlarga)",
        backup=f"🟢 {backup_line}" if backup_line else "❌ ulanmagan (adminlarga)",
        card=store.card_number(),
        holder=store.card_holder(),
        fee=store.default_fee(),
        hold=store.hold_minutes(),
        wait=store.waitlist_minutes(),
        free_mode=store.free_mode(),
        no_show=store.max_no_show(),
    ) + (
        f"\n\n⏰ <b>Eslatma:</b> oldingi kuni soat {store.remind_evening_hour()}:00 "
        f"va ishgacha {store.remind_before_minutes()} daqiqa qolganda\n"
        f"❓ <b>Davomat so'rovi:</b> ish boshlangandan {store.attendance_after_hours()} soat keyin\n"
        f"🚫 <b>Bekor qilish oynasi:</b> {store.cancel_window_minutes()} daqiqa\n"
        f"🎁 <b>Referal mukofoti:</b> {store.referral_reward()} ta bepul yozilish"
    )


@router.message(F.text == BTN_SETTINGS)
@router.message(Command("sozlama"))
async def settings_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    await message.answer(await _view(session), reply_markup=settings_kb(store.free_mode()))


@router.callback_query(SetCB.filter())
async def settings_action(
    call: CallbackQuery, callback_data: SetCB, state: FSMContext,
    session: AsyncSession, bot: Bot
) -> None:
    action = callback_data.action

    if action == "channels":
        await show_channels(call.message, session)
        await call.answer()
        return

    if action == "staff":
        await show_staff(call.message, session)
        await call.answer()
        return

    if action == "backup":
        await call.answer("Zaxira olinyapti…")
        await do_backup(call.message, session)
        return

    # --- bitta chat: moderatsiya guruhi va zaxira kanali
    if action in ("moderation", "backupchat"):
        await show_single_chat(call.message, "moderation" if action == "moderation" else "backup")
        await call.answer()
        return

    if action.startswith("test_"):
        kind = action.removeprefix("test_")
        await call.answer("Tekshirilyapti…")
        await call.message.answer(await _test_single(bot, kind))
        return

    if action.startswith("off_"):
        kind = action.removeprefix("off_")
        await store.set_value(session, f"{_key(kind)}", "")
        await store.set_value(session, f"{_key(kind)[:-3]}_title", "")
        await call.answer("🔌 Uzildi")
        await show_single_chat(call.message, kind)
        return

    if action.startswith("link_"):
        kind = action.removeprefix("link_")
        if store.get(_key(kind)):
            await call.answer("Avval hozirgisini uzing.", show_alert=True)
            return
        await state.set_state(Setup.moderation if kind == "moderation" else Setup.backup_chat)
        await call.message.answer(
            texts.CONNECT_MODERATION if kind == "moderation" else texts.CONNECT_BACKUP
        )
        await call.answer()
        return

    if action == "freemode":
        turning_on = not store.free_mode()
        if not turning_on and not (store.get("card_number") and store.get("card_holder")):
            await call.answer(
                "Avval karta rekvizitlarini to'ldiring — aks holda ishchilar "
                "to'lovni qayerga qilishini bilmaydi.",
                show_alert=True,
            )
            return
        await store.set_value(session, "free_mode", "1" if turning_on else "0")
        await call.answer("✅ O'zgartirildi")
        await call.message.answer(texts.free_mode_switched(turning_on))
        await call.message.answer(await _view(session), reply_markup=settings_kb(turning_on))
        return

    prompts = {
        "channel": (Setup.channel, texts.CONNECT_CHANNEL),
        "card": (Setup.card_number, texts.ASK_CARD_NUMBER),
        "holder": (Setup.card_holder, texts.ASK_CARD_HOLDER),
        "fee": (Setup.fee, texts.ASK_FEE),
        "hold": (Setup.hold, texts.ASK_HOLD),
        "noshow": (Setup.no_show, texts.ASK_NO_SHOW),
        "addstaff": (Setup.add_staff, texts.ASK_STAFF),
    }
    if action not in prompts:
        await call.answer()
        return
    state_obj, prompt = prompts[action]
    await state.set_state(state_obj)
    await call.message.answer(prompt)
    await call.answer()


# ================================================================ kanallar

async def show_channels(message: Message, session: AsyncSession) -> None:
    items = await ch.all_channels(session)
    if not items:
        await message.answer(texts.CHANNELS_EMPTY, reply_markup=channels_kb([]))
        return
    active = sum(1 for c in items if c.is_active)
    await message.answer(
        texts.channels_view(len(items), active), reply_markup=channels_kb(items)
    )


async def show_channel(message: Message, session: AsyncSession, channel_id: int) -> None:
    channel = await session.get(Channel, channel_id)
    if channel is None:
        await message.answer("❌ Kanal topilmadi.")
        return
    posts = int(
        (await session.scalar(
            select(func.count()).select_from(JobPost).where(JobPost.chat_id == channel.chat_id)
        )) or 0
    )
    regions = ", ".join(channel.region_list) or "barchasi"
    cats = ", ".join(CATEGORY_NAMES.get(k, k) for k in channel.category_list) or "barchasi"
    text = texts.channel_view(
        channel.title or str(channel.chat_id), channel.chat_id,
        channel.is_active, regions, cats, posts,
    )
    if channel.last_error:
        text += f"\n\n⚠️ Oxirgi xato: <i>{channel.last_error}</i>"
    await message.answer(text, reply_markup=channel_kb(channel))


@router.callback_query(ChanCB.filter(F.action == "view"))
async def channel_view_cb(call: CallbackQuery, callback_data: ChanCB, session: AsyncSession) -> None:
    await show_channel(call.message, session, callback_data.channel_id)
    await call.answer()


@router.callback_query(ChanCB.filter(F.action == "toggle"))
async def channel_toggle(call: CallbackQuery, callback_data: ChanCB, session: AsyncSession) -> None:
    channel = await ch.toggle(session, callback_data.channel_id)
    await call.answer("✅ O'zgartirildi" if channel else "Topilmadi")
    await show_channel(call.message, session, callback_data.channel_id)


@router.callback_query(ChanCB.filter(F.action == "del"))
async def channel_delete(call: CallbackQuery, callback_data: ChanCB, session: AsyncSession) -> None:
    await ch.remove(session, callback_data.channel_id)
    await call.answer("🗑 O'chirildi")
    await show_channels(call.message, session)


@router.callback_query(ChanCB.filter(F.action == "test"))
async def channel_test(
    call: CallbackQuery, callback_data: ChanCB, session: AsyncSession, bot: Bot
) -> None:
    from bot.db.models import Channel

    channel = await session.get(Channel, callback_data.channel_id)
    if channel is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer("Tekshirilyapti…")
    await call.message.answer(await publisher.test_channel(bot, session, channel))


@router.callback_query(ChanCB.filter(F.action.in_({"regions", "cats"})))
async def channel_filter_start(
    call: CallbackQuery, callback_data: ChanCB, state: FSMContext, session: AsyncSession
) -> None:
    from bot.db.models import Channel

    channel = await session.get(Channel, callback_data.channel_id)
    if channel is None:
        await call.answer("Topilmadi", show_alert=True)
        return

    await state.update_data(channel_id=channel.id)
    if callback_data.action == "regions":
        await state.set_state(Setup.channel_regions)
        await call.message.answer(
            "📍 Shu kanalga qaysi hududlarning e'lonlari borsin?\n"
            "<i>Hech narsa tanlamasangiz — barchasi.</i>",
            reply_markup=multi_pick_kb("chreg", region_options(), channel.region_list),
        )
    else:
        await state.set_state(Setup.channel_categories)
        await call.message.answer(
            "🧰 Shu kanalga qaysi kasblarning e'lonlari borsin?\n"
            "<i>Hech narsa tanlamasangiz — barchasi.</i>",
            reply_markup=multi_pick_kb("chcat", category_options(), channel.category_list),
        )
    await call.answer()


@router.callback_query(PickCB.filter(F.field.in_({"chreg", "chcat"})))
async def channel_filter_pick(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext, session: AsyncSession
) -> None:
    from bot.db.models import Channel

    data = await state.get_data()
    channel = await session.get(Channel, data.get("channel_id", 0))
    if channel is None:
        await call.answer("Kanal topilmadi", show_alert=True)
        return

    is_region = callback_data.field == "chreg"
    field = "regions" if is_region else "categories"
    current = channel.region_list if is_region else channel.category_list

    if callback_data.value == "__done__":
        await state.set_state(None)
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("✅ Saqlandi")
        await show_channel(call.message, session, channel.id)
        return

    if callback_data.value == "__all__":
        current = []
    elif callback_data.value in current:
        current.remove(callback_data.value)
    else:
        current.append(callback_data.value)

    await ch.set_filter(session, channel.id, field, current)
    options = region_options() if is_region else category_options()
    await call.message.edit_reply_markup(
        reply_markup=multi_pick_kb(callback_data.field, options, current)
    )
    await call.answer()


# ================================================================ chat ulash

def _chat_id_from(message: Message) -> tuple[int | str | None, str]:
    """Forward qilingan xabardan manba chat ID sini ajratadi.

    MUHIM cheklov: Telegram forward'da manba chatni FAQAT kanal uchun
    beradi. Oddiy guruhdan forward qilinganda faqat yuboruvchi odam
    ko'rinadi. Shuning uchun guruhlar uchun boshqa usullar bor:
    botni guruhga qo'shish (bot o'zi aniqlaydi) yoki guruhda /id.
    """
    origin = message.forward_origin
    if origin is not None:
        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if chat is not None:
            return chat.id, chat.title or str(chat.id)

    text = (message.text or "").strip()
    if text.startswith("@") and len(text) > 3:
        return text, text
    if text.lstrip("-").isdigit():
        return int(text), text
    return None, ""


@router.message(Setup.channel)
async def add_channel(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    chat_id, title = _chat_id_from(message)
    if chat_id is None:
        await message.answer(texts.FORWARD_NOT_RECOGNIZED)
        return

    # @username berilgan bo'lsa haqiqiy raqamli ID ni olamiz — u barqarorroq
    # (kanal username'ini o'zgartirsa ham ishlayveradi).
    kind = "channel"
    if isinstance(chat_id, str):
        try:
            info = await bot.get_chat(chat_id)
            chat_id, title, kind = info.id, info.title or title, info.type
        except Exception as e:
            await message.answer(f"❌ Topilmadi: {e}"[:300])
            return

    channel = await ch.add(session, int(chat_id), title, kind)
    await state.set_state(None)
    await message.answer(f"✅ Qo'shildi: <b>{channel.title}</b>", reply_markup=admin_menu())
    await message.answer(await publisher.test_channel(bot, session, channel))
    await show_channel(message, session, channel.id)


def _key(kind: str) -> str:
    return "moderation_chat_id" if kind == "moderation" else "backup_chat_id"


def _title_key(kind: str) -> str:
    return "moderation_chat_title" if kind == "moderation" else "backup_chat_title"


async def show_single_chat(message: Message, kind: str) -> None:
    """Ulangan chatni ko'rsatadi — nomi, ID si va tugmalari bilan."""
    chat_id = store.get(_key(kind))
    title = store.get(_title_key(kind)) or chat_id
    await message.answer(
        texts.single_chat_view(kind, title, chat_id),
        reply_markup=single_chat_kb(kind, bool(chat_id)),
    )


async def _test_single(bot: Bot, kind: str) -> str:
    target = store.chat_id(_key(kind))
    if target is None:
        return "❌ Ulanmagan."
    try:
        info = await bot.get_chat(target)
        me = await bot.get_chat_member(target, (await bot.get_me()).id)
    except Exception as e:
        return f"❌ Ulanib bo'lmadi: {e}"[:300]
    if me.status in ("left", "kicked"):
        return f"❌ <b>{info.title}</b> — bot bu chatda yo'q. Uni qayta qo'shing."
    return f"✅ <b>{info.title}</b> — ishlayapti"


async def _connect_single(
    message: Message, state: FSMContext, session: AsyncSession, kind: str
) -> None:
    """Bitta chatni ulaydi. Allaqachon ulangan bo'lsa — rad etadi."""
    if store.get(_key(kind)):
        await state.set_state(None)
        await message.answer(texts.ALREADY_CONNECTED)
        await show_single_chat(message, kind)
        return

    chat_id, title = _chat_id_from(message)
    if chat_id is None:
        await message.answer(texts.FORWARD_NOT_RECOGNIZED)
        return

    await store.set_value(session, _key(kind), str(chat_id))
    await store.set_value(session, _title_key(kind), title[:128])
    await state.set_state(None)
    await message.answer(
        texts.CONNECTED_MODERATION if kind == "moderation" else texts.CONNECTED_BACKUP,
        reply_markup=admin_menu(),
    )
    await show_single_chat(message, kind)


@router.message(Setup.moderation)
async def set_moderation(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _connect_single(message, state, session, "moderation")


@router.message(Setup.backup_chat)
async def set_backup_chat(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _connect_single(message, state, session, "backup")


@router.my_chat_member()
async def bot_added_to_chat(
    event: ChatMemberUpdated, session: AsyncSession, bot: Bot
) -> None:
    """Bot biror kanal/guruhga qo'shilganda ishlaydi.

    Sozlashning eng qulay yo'li: admin botni qo'shadi, bot o'sha zahoti
    unga «shu chatni ishlataymi?» degan tugma yuboradi. ID ni qidirish,
    forward qilish, qo'lda yozish — hech biri kerak emas.
    """
    if event.chat.type == "private":
        return

    title = event.chat.title or str(event.chat.id)
    known = await ch.get_by_chat(session, event.chat.id)

    if event.new_chat_member.status in ("left", "kicked"):
        if known:
            known.is_active = False
            known.last_error = "bot chatdan chiqarib yuborilgan"
            await session.commit()
            await publisher.notify_admins(
                bot,
                texts.CHAT_KICKED_WARNING.format(
                    title=title,
                    what="Kanal to'xtatildi — e'lonlar u yerga joylanmaydi.",
                ),
            )

        # Moderatsiya guruhi yoki zaxira kanali bo'lsa — bu jimgina
        # o'tib ketmasligi kerak. Cheklar adminlarga qaytadi, lekin siz
        # buni bilishingiz shart.
        if str(event.chat.id) == store.get("moderation_chat_id"):
            await publisher.notify_admins(
                bot,
                texts.CHAT_KICKED_WARNING.format(
                    title=title,
                    what="Bu MODERATSIYA guruhi edi. Cheklar endi "
                         "adminlarga shaxsan boradi.",
                ),
            )
        if str(event.chat.id) == store.get("backup_chat_id"):
            await publisher.notify_admins(
                bot,
                texts.CHAT_KICKED_WARNING.format(
                    title=title,
                    what="Bu ZAXIRA kanali edi. Nusxalar endi adminlarga "
                         "shaxsan boradi.",
                ),
            )
        return

    # Botni ADMIN bo'lmagan odam qo'shdi: hech narsa sozlamaymiz.
    if event.from_user is None or not is_owner(event.from_user.id):
        adder = await session.get(User, event.from_user.id) if event.from_user else None
        if adder is None or adder.role != Role.ADMIN:
            kb = InlineKeyboardBuilder()
            kb.button(
                text="🚪 Botni o'sha chatdan chiqarish",
                callback_data=ChatCB(kind="leave", chat_id=event.chat.id).pack(),
            )
            await publisher.notify_admins(
                bot,
                f"ℹ️ <b>Begona chat</b>\n\n"
                f"{event.from_user.full_name if event.from_user else '—'} "
                f"(<code>{event.from_user.id if event.from_user else '—'}</code>) "
                f"botni «{title}» ga qo'shdi.\n"
                f"Turi: {event.chat.type} · ID: <code>{event.chat.id}</code>\n\n"
                f"⚠️ Bu chatga bot HECH NARSA yubormaydi va u yerda buyruqlarga "
                f"javob bermaydi — xavf yo'q.",
                reply_markup=kb.as_markup(),
            )
            return

    is_admin_here = event.new_chat_member.status == "administrator"
    lines = [
        f"🤖 Bot <b>«{title}»</b> ga qo'shildi.",
        f"Turi: {event.chat.type} · ID: <code>{event.chat.id}</code>",
    ]
    if event.chat.type == "channel" and not is_admin_here:
        lines.append(
            "\n⚠️ Bot bu kanalda ADMIN emas — e'lon joylay olmaydi.\n"
            "Kanal sozlamalari → Administratorlar → botga «Xabar joylash» va "
            "«Xabarlarni tahrirlash» huquqlarini bering."
        )
    lines.append("\nShu chatni nima sifatida ishlatamiz?")

    kb = InlineKeyboardBuilder()
    kb.button(
        text="📢 E'lonlar kanali (ro'yxatga qo'shish)",
        callback_data=ChatCB(kind="channel", chat_id=event.chat.id).pack(),
    )
    if not store.get("moderation_chat_id"):
        kb.button(
            text="👮 Moderatsiya guruhi",
            callback_data=ChatCB(kind="moderation", chat_id=event.chat.id).pack(),
        )
    if not store.get("backup_chat_id"):
        kb.button(
            text="💾 Zaxira kanali",
            callback_data=ChatCB(kind="backup", chat_id=event.chat.id).pack(),
        )
    kb.adjust(1)
    try:
        await bot.send_message(event.from_user.id, "\n".join(lines), reply_markup=kb.as_markup())
    except Exception as e:
        log.warning("Adminga chat haqida xabar bormadi: %s", e)


@router.callback_query(ChatCB.filter(F.kind == "leave"))
async def leave_chat(call: CallbackQuery, callback_data: ChatCB, bot: Bot) -> None:
    try:
        await bot.leave_chat(callback_data.chat_id)
        await call.answer("🚪 Chiqdi")
        await call.message.edit_text(
            (call.message.text or "") + "\n\n🚪 <b>Bot chatdan chiqdi.</b>", reply_markup=None
        )
    except Exception as e:
        await call.answer(f"Chiqib bo'lmadi: {e}"[:190], show_alert=True)


@router.callback_query(ChatCB.filter())
async def use_chat(
    call: CallbackQuery, callback_data: ChatCB, session: AsyncSession, bot: Bot
) -> None:
    await call.message.edit_reply_markup(reply_markup=None)

    if callback_data.kind == "channel":
        try:
            info = await bot.get_chat(callback_data.chat_id)
            title, kind = info.title or "", info.type
        except Exception:
            title, kind = "", "channel"
        channel = await ch.add(session, callback_data.chat_id, title, kind)
        await call.answer("✅ Qo'shildi")
        await call.message.answer(await publisher.test_channel(bot, session, channel))
        await show_channel(call.message, session, channel.id)
        return

    kind = callback_data.kind  # moderation | backup
    if store.get(_key(kind)):
        await call.answer("Allaqachon ulangan — avval uzing.", show_alert=True)
        return

    try:
        info = await bot.get_chat(callback_data.chat_id)
        title = info.title or str(callback_data.chat_id)
    except Exception:
        title = str(callback_data.chat_id)

    await store.set_value(session, _key(kind), str(callback_data.chat_id))
    await store.set_value(session, _title_key(kind), title[:128])
    await call.answer("✅ Saqlandi")
    await call.message.answer(
        texts.CONNECTED_MODERATION if kind == "moderation" else texts.CONNECTED_BACKUP
    )
    await show_single_chat(call.message, kind)


# ================================================================ moderatorlar

async def show_staff(message: Message, session: AsyncSession) -> None:
    members = list(
        (await session.scalars(select(User).where(User.role.in_(STAFF_ROLES)))).all()
    )
    mods = [m for m in members if not is_owner(m.id)]
    if not mods:
        await message.answer(texts.STAFF_EMPTY, reply_markup=staff_kb([]))
        return
    lines = "\n".join(
        f"• {m.mention} — {'🛡 moderator' if m.role == Role.MODERATOR else '👑 admin'}"
        for m in mods
    )
    await message.answer(
        f"🛡 <b>Moderatorlar</b>\n\n{lines}\n\n"
        f"O'chirish uchun ismini bosing.",
        reply_markup=staff_kb(mods),
    )


@router.message(Setup.add_staff, F.text)
async def add_staff(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    target = await svc.find_user(session, message.text)
    if target is None:
        await message.answer(
            "❌ Topilmadi. U avval botga /start yozgan bo'lishi kerak.\n\n"
            "Bekor qilish: /cancel"
        )
        return
    if is_owner(target.id):
        await message.answer("Bu odam allaqachon asosiy admin.")
        return

    target.role = Role.MODERATOR
    await session.commit()
    await state.set_state(None)
    await message.answer(f"✅ {target.mention} endi <b>moderator</b>.", reply_markup=admin_menu())

    try:
        await bot.send_message(
            target.id,
            "🛡 <b>Sizga moderator huquqi berildi.</b>\n\n"
            "Endi to'lov cheklarini tasdiqlay olasiz va e'lon joylay olasiz.\n"
            "/start bosib menyuni yangilang.",
        )
    except Exception:
        pass
    await show_staff(message, session)


@router.callback_query(StaffCB.filter(F.action == "demote"))
async def demote_staff(
    call: CallbackQuery, callback_data: StaffCB, session: AsyncSession, bot: Bot
) -> None:
    target = await session.get(User, callback_data.user_id)
    if target is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    if is_owner(target.id):
        await call.answer("Asosiy adminni o'chirib bo'lmaydi.", show_alert=True)
        return

    target.role = Role.WORKER
    await session.commit()
    await call.answer("🗑 O'chirildi")
    try:
        await bot.send_message(target.id, "ℹ️ Moderator huquqingiz olib tashlandi.")
    except Exception:
        pass
    await show_staff(call.message, session)


@router.message(Command("mod"))
async def mod_command(message: Message, command, session: AsyncSession, bot: Bot) -> None:  # noqa: ANN001
    """Tez usul: /mod 123456789 yoki /mod @username"""
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Ishlatilishi: <code>/mod 123456789</code> yoki <code>/mod @username</code>")
        return
    target = await svc.find_user(session, arg)
    if target is None:
        await message.answer("❌ Topilmadi. U avval botga /start yozishi kerak.")
        return
    if is_owner(target.id):
        await message.answer("Bu odam asosiy admin — roli o'zgarmaydi.")
        return

    if target.role == Role.MODERATOR:
        target.role = Role.WORKER
        note = "🗑 moderator emas"
    else:
        target.role = Role.MODERATOR
        note = "🛡 moderator"
    await session.commit()
    await message.answer(f"{target.mention} → {note}")


# ================================================================ zaxira

async def do_backup(message: Message, session: AsyncSession) -> None:
    try:
        path = await backup.create()
    except Exception as e:
        log.exception("Zaxira olishda xato")
        await message.answer(f"❌ Zaxira olinmadi: {e}"[:300])
        return
    if path is None:
        await message.answer("ℹ️ Baza SQLite emas — zaxira uchun pg_dump ishlating.")
        return

    size_kb = path.stat().st_size / 1024
    await message.answer_document(
        FSInputFile(path),
        caption=(
            f"💾 <b>Zaxira nusxa</b>\n{path.name} · {size_kb:.0f} KB\n\n"
            f"Bu faylni saqlab qo'ying. Tiklash uchun:\n"
            f"<code>python restore.py {path.name}</code>"
        ),
    )


@router.message(Command("backup"))
async def backup_command(message: Message, session: AsyncSession) -> None:
    await do_backup(message, session)


@router.message(Command("health"))
async def health_command(message: Message, session: AsyncSession) -> None:
    """Bot va bazaning ahvoli — bir qarashda."""
    age = backup.age_hours()
    backup_line = (
        "❌ hali olinmagan" if age is None
        else f"{age:.0f} soat oldin ({backup.latest().name})"
    )
    verdict = await integrity_check()
    stats = await svc.stats(session)

    await message.answer(
        f"🩺 <b>Bot holati</b>\n\n"
        f"⏱ Ishlab turgani: <b>{health.human(health.uptime())}</b>\n"
        f"💾 Baza: <b>{backup.db_size_kb():.0f} KB</b>\n"
        f"🗄 Oxirgi zaxira: <b>{backup_line}</b>\n"
        f"🔬 Baza butunligi: <b>{'✅ soz' if verdict == 'ok' else '🚨 ' + verdict}</b>\n\n"
        f"👤 Foydalanuvchi: {stats['users']} (faol: {stats['active']})\n"
        f"📢 Ochiq e'lon: {stats['open_jobs']}\n"
        f"🔎 Tekshiruvda: {stats['waiting']}"
    )


# ================================================================ oddiy maydonlar

@router.message(Setup.card_number, F.text)
async def set_card(message: Message, state: FSMContext, session: AsyncSession) -> None:
    digits = "".join(c for c in message.text if c.isdigit())
    if not (12 <= len(digits) <= 20):
        await message.answer("❗️ Karta raqami noto'g'ri. 16 xonali raqamni yuboring.")
        return
    pretty = " ".join(digits[i : i + 4] for i in range(0, len(digits), 4))
    await store.set_value(session, "card_number", pretty)
    await _done(message, state, session)


@router.message(Setup.card_holder, F.text)
async def set_holder(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = message.text.strip()[:64]
    if len(value) < 3:
        await message.answer("❗️ Juda qisqa.")
        return
    await store.set_value(session, "card_holder", value)
    await _done(message, state, session)


@router.message(Setup.fee, F.text)
async def set_fee(message: Message, state: FSMContext, session: AsyncSession) -> None:
    v = parse_int(message.text)
    if v is None:
        await message.answer(texts.BAD_NUMBER)
        return
    await store.set_value(session, "default_fee", str(v))
    await _done(message, state, session)


@router.message(Setup.hold, F.text)
async def set_hold(message: Message, state: FSMContext, session: AsyncSession) -> None:
    v = parse_int(message.text)
    if v is None or not (3 <= v <= 120):
        await message.answer("❗️ 3 dan 120 gacha son kiriting.")
        return
    await store.set_value(session, "hold_minutes", str(v))
    await _done(message, state, session)


@router.message(Setup.no_show, F.text)
async def set_no_show(message: Message, state: FSMContext, session: AsyncSession) -> None:
    v = parse_int(message.text)
    if v is None or v > 20:
        await message.answer("❗️ 0 dan 20 gacha son kiriting.")
        return
    await store.set_value(session, "max_no_show", str(v))
    await _done(message, state, session)


async def _done(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    await message.answer(texts.SAVED)
    await message.answer(await _view(session), reply_markup=settings_kb(store.free_mode()))
