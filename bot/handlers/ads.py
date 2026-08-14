"""📣 Reklama tarqatish — daromadning ikkinchi manbasi.

Admin botga istalgan xabarni yuboradi (matn, rasm, video, rasm+izoh),
auditoriyani tanlaydi va bot uni hammaga tarqatadi.

Muhim tafsilotlar:
  * Xabar NUSXALANADI, forward qilinmaydi — «Forwarded from» yozuvi
    chiqmaydi va reklama tabiiy ko'rinadi.
  * Yuborishdan oldin aynan qanday ko'rinishini va necha kishiga
    borishini ko'rsatamiz. Ming kishiga xato reklama yuborish — qaytarib
    bo'lmaydigan xato.
  * Tarqatish fon rejimida, sekundiga 25 xabar. Botni bloklaganlar
    avtomat belgilanadi.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.callbacks import PickCB
from bot.config import CATEGORY_NAMES
from bot.db.base import SessionMaker
from bot.keyboards import BTN_ADS, ad_channels_kb, admin_menu, categories_kb, regions_kb
from bot.permissions import IsAdmin
from bot.services import audit, broadcast, channels as ch, jobs as svc
from bot.states import Ad

log = logging.getLogger(__name__)
router = Router(name="ads")

# Reklama — pul va obro' masalasi, faqat admin.
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(F.text == BTN_ADS)
@router.message(Command("reklama"))
async def ad_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Ad.content)
    await message.answer(
        "📣 <b>Reklama tarqatish</b>\n\n"
        "Tarqatmoqchi bo'lgan xabarni <b>shu yerga yuboring</b> — matn, rasm, "
        "video, rasm+izoh, nima bo'lsa ham.\n\n"
        "Bot uni xuddi shu ko'rinishda tarqatadi.\n\n"
        "Bekor qilish: /cancel"
    )


@router.message(Ad.content, ~F.text.startswith("/"))
async def ad_content(message: Message, state: FSMContext) -> None:
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Ad.button)
    await message.answer(
        "🔗 <b>Tugma qo'shasizmi?</b>\n\n"
        "Format: <code>Tugma matni - https://havola</code>\n"
        "<i>Masalan: Buyurtma berish - https://t.me/mening_kanalim</i>\n\n"
        "Tugmasiz davom etish: /skip"
    )


@router.message(Ad.button, Command("skip"))
async def ad_no_button(message: Message, state: FSMContext) -> None:
    await state.update_data(btn_text=None, btn_url=None)
    await _ask_audience(message, state)


@router.message(Ad.button, F.text)
async def ad_button(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if "-" not in raw or "http" not in raw:
        await message.answer(
            "❗️ Format: <code>Tugma matni - https://havola</code>\n"
            "Yoki tugmasiz davom eting: /skip"
        )
        return
    text, url = raw.rsplit("-", 1)
    text, url = text.strip()[:32], url.strip()
    if not url.startswith("http") or not text:
        await message.answer("❗️ Havola <code>https://</code> bilan boshlanishi kerak.")
        return
    await state.update_data(btn_text=text, btn_url=url)
    await _ask_audience(message, state)


async def _ask_audience(message: Message, state: FSMContext) -> None:
    await state.set_state(Ad.audience)
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Barcha foydalanuvchilar", callback_data=PickCB(field="adaud", value="all").pack())
    kb.button(text="📍 Hudud bo'yicha", callback_data=PickCB(field="adaud", value="region").pack())
    kb.button(text="🧰 Kasb bo'yicha", callback_data=PickCB(field="adaud", value="category").pack())
    kb.button(text="📢 Barcha kanallarga", callback_data=PickCB(field="adaud", value="channels").pack())
    kb.button(text="📡 Tanlangan kanallarga", callback_data=PickCB(field="adaud", value="pickch").pack())
    kb.adjust(1)
    await message.answer("👥 <b>Kimga yuboramiz?</b>", reply_markup=kb.as_markup())


@router.callback_query(Ad.audience, PickCB.filter(F.field == "adaud"))
async def ad_audience(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext, session: AsyncSession
) -> None:
    choice = callback_data.value
    await state.update_data(mode=choice)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()

    if choice == "region":
        await state.set_state(Ad.pick)
        await call.message.answer("📍 Hududni tanlang:", reply_markup=regions_kb("adreg"))
        return
    if choice == "category":
        await state.set_state(Ad.pick)
        await call.message.answer("🧰 Kasbni tanlang:", reply_markup=categories_kb("adcat"))
        return

    if choice == "pickch":
        items = await ch.all_channels(session, only_active=True)
        if not items:
            await call.message.answer("❌ Faol kanal yo'q.")
            await state.clear()
            return
        await state.set_state(Ad.pick)
        await state.update_data(picked=[])
        await call.message.answer(
            "📡 <b>Qaysi kanallarga?</b>\n\nBir nechtasini tanlashingiz mumkin.",
            reply_markup=ad_channels_kb(items, []),
        )
        return

    await _preview(call.message, state, session)


@router.callback_query(Ad.pick, PickCB.filter(F.field == "adch"))
async def ad_pick_channels(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    picked: list[int] = list(data.get("picked", []))
    page = int(data.get("ad_page", 0))

    if callback_data.value == "__done__":
        if not picked:
            await call.answer("Kamida bittasini tanlang.", show_alert=True)
            return
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer()
        await _preview(call.message, state, session)
        return

    # Sahifalash: 40-50 kanal bitta ro'yxatga sig'maydi.
    if callback_data.value.startswith("__page_"):
        page = int(callback_data.value[7:-2])
        await state.update_data(ad_page=page)
    else:
        cid = int(callback_data.value)
        if cid in picked:
            picked.remove(cid)
        else:
            picked.append(cid)
        await state.update_data(picked=picked)

    items = await ch.all_channels(session, only_active=True)
    await call.message.edit_reply_markup(reply_markup=ad_channels_kb(items, picked, page))
    await call.answer()


@router.callback_query(Ad.pick, PickCB.filter(F.field.in_({"adreg", "adcat"})))
async def ad_pick(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext, session: AsyncSession
) -> None:
    key = "region" if callback_data.field == "adreg" else "category"
    await state.update_data(**{key: callback_data.value})
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await _preview(call.message, state, session)


def _markup(data: dict):  # noqa: ANN201
    if not data.get("btn_url"):
        return None
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=data["btn_text"], url=data["btn_url"]))
    return kb.as_markup()


async def _preview(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Yuborishdan oldin aynan qanday ko'rinishini ko'rsatamiz.

    Ming kishiga xato reklama yuborish — qaytarib bo'lmaydigan xato.
    Shuning uchun tasdiqlash majburiy.
    """
    data = await state.get_data()
    bot = message.bot

    if data["mode"] in ("channels", "pickch"):
        targets = await _ad_channels(session, data)
        count = len(targets)
        names = ", ".join(t.title or str(t.chat_id) for t in targets[:3])
        who = f"{count} ta kanal" + (f" ({names}…)" if count > 3 else f" ({names})")
    else:
        ids = await svc.audience(
            session, region=data.get("region"), category=data.get("category")
        )
        await state.update_data(user_ids=ids)
        count = len(ids)
        scope = []
        if data.get("region"):
            scope.append(f"📍 {data['region']}")
        if data.get("category"):
            scope.append(f"🧰 {CATEGORY_NAMES.get(data['category'], data['category'])}")
        who = f"{count} ta foydalanuvchi" + (f" ({', '.join(scope)})" if scope else "")

    await message.answer("👀 <b>Shunday ko'rinadi:</b>")
    await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=data["from_chat_id"],
        message_id=data["message_id"],
        reply_markup=_markup(data),
    )

    if count == 0:
        await state.clear()
        await message.answer("❌ Bu filtrga mos hech kim topilmadi. Bekor qilindi.")
        return

    minutes = max(count // (broadcast.RATE_PER_SECOND * 60), 0)
    eta = f"~{minutes} daqiqa" if minutes >= 1 else "bir daqiqadan kam"

    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Yuborish", callback_data=PickCB(field="adgo", value="yes").pack())
    kb.button(text="🚫 Bekor qilish", callback_data=PickCB(field="adgo", value="no").pack())
    kb.adjust(2)

    await state.set_state(Ad.confirm)
    await message.answer(
        f"📊 <b>Qabul qiluvchilar:</b> {who}\n"
        f"⏱ <b>Taxminiy vaqt:</b> {eta}\n\n"
        f"Yuborilsinmi? Yuborilgandan keyin qaytarib bo'lmaydi.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(Ad.confirm, PickCB.filter(F.field == "adgo"))
async def ad_confirm(
    call: CallbackQuery, callback_data: PickCB, state: FSMContext,
    session: AsyncSession, bot: Bot
) -> None:
    if callback_data.value == "no":
        await state.clear()
        await call.message.edit_text("🚫 Reklama bekor qilindi.")
        await call.answer()
        return

    data = await state.get_data()
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("🚀 Boshlandi")

    if data["mode"] in ("channels", "pickch"):
        await audit.log_action(
            session, call.from_user.id, "ad_sent",
            "kanallarga" if data["mode"] == "channels" else "tanlangan kanallarga",
        )
        await _send_to_channels(bot, session, data, call.from_user.id)
        return

    await call.message.answer("📤 Tarqatish boshlandi. Yakunida hisobot yuboraman.")
    await audit.log_action(
        session, call.from_user.id, "ad_sent",
        f"{len(data.get('user_ids', []))} ta foydalanuvchiga",
    )
    # Fon rejimida — admin panel qotib turmaydi.
    asyncio.create_task(_run(bot, data, call.from_user.id))


async def _ad_channels(session: AsyncSession, data: dict) -> list:
    """Reklama boradigan kanallar: hammasi yoki tanlanganlari."""
    items = await ch.all_channels(session, only_active=True)
    if data.get("mode") == "pickch":
        picked = set(data.get("picked", []))
        return [c for c in items if c.id in picked]
    return items


async def _send_to_channels(bot: Bot, session: AsyncSession, data: dict, report_to: int) -> None:
    targets = await _ad_channels(session, data)
    ok, errors = 0, []
    for channel in targets:
        try:
            await bot.copy_message(
                chat_id=channel.chat_id,
                from_chat_id=data["from_chat_id"],
                message_id=data["message_id"],
                reply_markup=_markup(data),
            )
            ok += 1
        except Exception as e:
            errors.append(f"{channel.title}: {e}"[:120])
        await asyncio.sleep(0.1)

    text = f"📢 <b>Kanallarga joylandi: {ok}/{len(targets)}</b>"
    if errors:
        text += "\n\n⚠️ Xatolar:\n" + "\n".join(errors)
    await bot.send_message(report_to, text[:3500])


async def _run(bot: Bot, data: dict, report_to: int) -> None:
    result = await broadcast.send_bulk_copy(
        bot,
        data["user_ids"],
        from_chat_id=data["from_chat_id"],
        message_id=data["message_id"],
        reply_markup=_markup(data),
    )

    if result.blocked:
        # Botni o'chirganlarni belgilaymiz — keyingi tarqatishlar tezroq.
        async with SessionMaker() as session:
            for uid in result.blocked:
                await svc.deactivate(session, uid)

    log.info(
        "Reklama tarqatildi: %s yuborildi, %s bloklagan, %s xato",
        result.sent, len(result.blocked), result.failed,
    )
    try:
        await bot.send_message(
            report_to,
            f"📣 <b>Reklama tarqatildi</b>\n\n"
            f"✅ Yetib bordi: <b>{result.sent}</b>\n"
            f"🚫 Botni o'chirgan: {len(result.blocked)}\n"
            f"⚠️ Xato: {result.failed}",
            reply_markup=admin_menu(),
        )
    except Exception:
        pass
