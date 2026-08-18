r"""Oqim testi: tugma bosilganda ZANJIR oxirigacha ishlaydimi?

Ishga tushirish:
    .venv\Scripts\python.exe flow_test.py

smoke_test — biznes qoidalari, wiring_test — yig'ilish. Bu esa uchinchi
qatlam: HANDLER'larni haqiqatan chaqiradi.

Telegramga chiqmaymiz — Bot obyektining so'rov yuboruvchisi almashtiriladi
va nima yuborilgani yozib boriladi. Shu bilan "tugma bosildi -> nima
bo'ldi" zanjiri to'liq tekshiriladi.
"""

import asyncio
import os
import pathlib
import sys

DB = pathlib.Path("_flow.db")
os.environ["BOT_TOKEN"] = "111:AAAA"
os.environ["ADMIN_IDS"] = "5"
os.environ["DB_URL"] = "sqlite+aiosqlite:///./" + DB.name

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime, timedelta  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery,
    Chat,
    Contact,
    Document,
    Message,
    Update,
    User as TgUser,
)

from bot import runtime  # noqa: E402
from bot.db.base import SessionMaker, engine, init_db  # noqa: E402
from bot.db.models import Channel, Job, JobStatus, Role, User  # noqa: E402
from bot.fsm_storage import DbStorage  # noqa: E402
from bot.handlers import build_router  # noqa: E402
from bot.middlewares import (  # noqa: E402
    DbSessionMiddleware,
    PrivateOnlyMiddleware,
    ThrottleMiddleware,
    UserMiddleware,
)
from bot.services import settings_store as store  # noqa: E402
from bot.utils import local_today  # noqa: E402

SENT = []
failures = 0


def check(label, cond, detail=""):  # noqa: ANN001
    global failures
    print(("  OK  " if cond else "  XATO") + " " + label + ((" -- " + detail) if detail else ""))
    if not cond:
        failures += 1


class FakeSession:
    """Telegram o'rniga: nima yuborilganini ro'yxatga yozadi."""

    async def __call__(self, bot, method, timeout=None):  # noqa: ANN001
        name = type(method).__name__
        SENT.append((name, method))
        d = method.model_dump()
        if name == "SendMessage":
            return Message(
                message_id=len(SENT) + 100,
                date=datetime.now(),
                chat=Chat(id=d.get("chat_id", 1), type="private"),
                text=d.get("text", ""),
            )
        if name in ("EditMessageText", "EditMessageReplyMarkup", "EditMessageCaption"):
            return Message(
                message_id=1, date=datetime.now(),
                chat=Chat(id=1, type="private"), text="edited",
            )
        if name == "GetMe":
            return TgUser(id=111, is_bot=True, first_name="Bot", username="radojob_bot")
        return True

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


bot = Bot(
    token="111:AAAA",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=FakeSession(),
)
runtime.bot_username = "radojob_bot"

dp = Dispatcher(storage=DbStorage(SessionMaker))
for obs in (dp.message, dp.callback_query):
    obs.outer_middleware(ThrottleMiddleware(interval=0.0))
    obs.outer_middleware(DbSessionMiddleware())
    obs.outer_middleware(UserMiddleware())
    obs.outer_middleware(PrivateOnlyMiddleware())
dp.include_router(build_router())

UID = 0


def press(data, uid, chat_id=None):  # noqa: ANN001
    global UID
    UID += 1
    chat = Chat(id=chat_id or uid, type="private")
    msg = Message(
        message_id=50, date=datetime.now(), chat=chat, text="oldingi xabar",
        from_user=TgUser(id=111, is_bot=True, first_name="Bot"),
    )
    return Update(
        update_id=UID,
        callback_query=CallbackQuery(
            id=str(UID), from_user=TgUser(id=uid, is_bot=False, first_name="U"),
            chat_instance="ci", data=data, message=msg,
        ),
    )


def say(text, uid, chat_id=None):  # noqa: ANN001
    global UID
    UID += 1
    return Update(
        update_id=UID,
        message=Message(
            message_id=UID, date=datetime.now(),
            chat=Chat(id=chat_id or uid, type="private"), text=text,
            from_user=TgUser(id=uid, is_bot=False, first_name="U"),
        ),
    )


def send_file(name, uid, size=2048):  # noqa: ANN001
    global UID
    UID += 1
    return Update(update_id=UID, message=Message(
        message_id=UID, date=datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=TgUser(id=uid, is_bot=False, first_name="U"),
        document=Document(file_id="F" + str(UID), file_unique_id="U" + str(UID),
                          file_name=name, file_size=size),
    ))


async def feed(update):  # noqa: ANN001
    SENT.clear()
    await dp.feed_update(bot, update)
    out = []
    for _name, m in SENT:
        d = m.model_dump()
        out.append(str(d.get("text") or d.get("caption") or ""))
    return out


def no_error(out):  # noqa: ANN001
    return not any("Xatolik" in t for t in out)


async def main():  # noqa: C901
    DB.unlink(missing_ok=True)
    await init_db()

    async with SessionMaker() as s:
        await store.load(s)
        await store.set_value(s, "card_number", "8600 1111 2222 3333")
        await store.set_value(s, "card_holder", "Test")
        await store.set_value(s, "free_mode", "0")
        s.add_all([
            User(id=5, full_name="Admin", role=Role.ADMIN, phone="+998", region="Chilonzor"),
            User(id=2, full_name="Ishchi", role=Role.WORKER, phone="+998900000001",
                 region="Chilonzor", categories="|yuk|", notify=True, lang="uz"),
            User(id=7, full_name="Rabotnik", role=Role.WORKER, phone="+998900000007",
                 region="Chilonzor", categories="|yuk|", notify=True, lang="ru"),
            User(id=3, full_name="Ish beruvchi", role=Role.EMPLOYER,
                 phone="+998900000002", region="Chilonzor", lang="ru"),
        ])
        await s.commit()
        s.add_all([
            Channel(id=1, chat_id=-1001, title="Chilonzor", kind="channel",
                    regions="|Chilonzor|"),
            Channel(id=2, chat_id=-1002, title="Umumiy", kind="channel"),
            Channel(id=3, chat_id=-1003, title="Sergeli", kind="channel",
                    regions="|Sergeli|"),
        ])
        for i in range(12):
            s.add(Job(
                category="yuk", title="Ish " + str(i), description="tavsif",
                secret_details="MAXFIY manzil", region="Chilonzor",
                work_date=local_today() + timedelta(days=2), start_time="08:00",
                salary=200_000, fee=10_000, slots_total=3,
                status=JobStatus.OPEN, created_by=5,
            ))
        await s.commit()

    print("")
    print("== 1. Foydalanuvchi topgan xato: Barchasi (filtrsiz)")
    await feed(press("s:channels", 5))
    out = await feed(press("ch:regions:1", 5))
    check("hudud filtri oynasi ochildi", any("hudud" in t.lower() for t in out), str(out)[:70])
    out = await feed(press("p:chreg:__all__", 5))
    check("Barchasi bosildi, xato yo'q", no_error(out), str(out)[:110])
    out = await feed(press("p:chreg:__all__", 5))
    check("ikkinchi marta ham xato yo'q", no_error(out), str(out)[:110])
    await feed(press("ch:cats:1", 5))
    out = await feed(press("p:chcat:__all__", 5))
    check("kasb filtrida ham ishlaydi", no_error(out), str(out)[:110])
    out = await feed(press("p:chcat:yuk", 5))
    check("bitta kasb tanlash ishlaydi", no_error(out))
    out = await feed(press("p:chcat:__done__", 5))
    check("Tayyor kanal kartochkasini ko'rsatdi", no_error(out) and bool(out), str(out)[:110])

    print("")
    print("== 2. Lenta: sahifalash va filtrni tozalash")
    out = await feed(say("/ishlar", 2))
    check("lenta ochildi", bool(out) and no_error(out), str(out)[:70])
    out = await feed(press("f:page::1", 2))
    check("sahifa 2 ga o'tdi", no_error(out), str(out)[:110])
    out = await feed(press("f:reset::0", 2))
    check("Filtrni tozalash ishlaydi", no_error(out), str(out)[:110])
    out = await feed(press("f:filter:region:0", 2))
    check("hudud filtri tugmasi ishlaydi", no_error(out), str(out)[:110])

    print("")
    print("== 3. Profil tugmalari (yangi)")
    out = await feed(say("Profil", 2))
    out = await feed(say("\U0001F464 Profil", 2))
    check("profil ochildi", any("Profil" in t for t in out), str(out)[:70])
    for action in ("lang", "region", "cats", "invite", "help"):
        out = await feed(press("pr:" + action, 2))
        check("tugma " + action + " javob berdi", bool(out) and no_error(out), str(out)[:60])
    out = await feed(press("pr:notify", 2))
    check("xabarnoma almashdi", any("xabar" in t.lower() for t in out), str(out)[:70])
    out = await feed(press("pr:complain", 2))
    check("shikoyat so'raldi", bool(out) and no_error(out), str(out)[:70])
    out = await feed(say("Ish beruvchi kelmadi va pul to'lamadi", 2))
    check("shikoyat qabul qilindi", bool(out) and no_error(out), str(out)[:70])

    print("")
    print("== 4. Profildan hudud o'zgartirish matni to'g'rimi")
    await feed(press("pr:region", 2))
    out = await feed(press("p:rregion:Sergeli", 2))
    check("Saqlandi deydi, ro'yxatdan o'tdingiz DEMAYDI",
          any("Saqland" in t for t in out) and not any("Tayyor!" in t for t in out),
          str(out)[:90])

    print("")
    print("== 5. Kanal tanlash oqimi (yangi)")
    out = await feed(press("aj:repost:1", 5))
    check("kanal tanlovi chiqdi", any("qayerga joylansin" in t for t in out), str(out)[:90])
    out = await feed(press("pb:auto:1:0", 5))
    check("Mos kanallarga ishladi", any("kanalga joylandi" in t for t in out), str(out)[:90])
    await feed(press("aj:repost:1", 5))
    out = await feed(press("pb:all:1:0", 5))
    check("Barchaga ishladi", any("kanalga joylandi" in t for t in out), str(out)[:90])
    await feed(press("aj:repost:1", 5))
    out = await feed(press("pb:pick:1:0", 5))
    check("qo'lda tanlash ochildi", no_error(out))
    out = await feed(press("pb:t:1:2", 5))
    check("kanal belgilandi", no_error(out))
    out = await feed(press("pb:done:1:0", 5))
    check("tanlanganlarga joylandi", any("kanalga joylandi" in t for t in out), str(out)[:90])
    await feed(press("aj:repost:1", 5))
    out = await feed(press("pb:skip:1:0", 5))
    check("Joylamaslik ishladi", any("joylanmadi" in t for t in out), str(out)[:90])

    print("")
    print("== 6. To'lov ko'rsatmasi qabul qiluvchining tilida")
    out = await feed(press("j:apply:2", 7))
    check("ruscha ishchiga ruscha", any(("Карта" in t) or ("сум" in t) for t in out), str(out)[:90])
    out = await feed(press("j:apply:3", 2))
    check("o'zbek ishchiga o'zbekcha", any(("Karta" in t) or ("so'm" in t) for t in out), str(out)[:90])

    print("")
    print("== 7. Jurnal, holat, hisobot tugmalari")
    out = await feed(press("s:journal", 5))
    check("jurnal ochildi", bool(out) and no_error(out), str(out)[:90])
    out = await feed(press("s:health", 5))
    check("bot holati ochildi", any("holati" in t for t in out), str(out)[:90])
    out = await feed(press("s:report", 5))
    check("kunlik hisobot ochildi", any("hisobot" in t.lower() for t in out), str(out)[:90])

    print("")
    print("== 8. Begona odam moderator tugmasini bosolmaydi")
    out = await feed(press("s:journal", 2))
    check("oddiy ishchi jurnal ocholmadi", not any("Jurnal" in t for t in out), str(out)[:70])
    out = await feed(press("pb:all:1:0", 2))
    check("oddiy ishchi kanalga joylay olmadi",
          not any("joylandi" in t for t in out), str(out)[:70])


    print("")
    print("== 9. YANGI odam ro'yxatdan o'tishi buzilmadimi")
    out = await feed(say("/start", 90))
    check("til so'raldi", any("Til" in t or "язык" in t for t in out), str(out)[:70])
    out = await feed(press("p:lang:uz", 90))
    check("rol so'raldi", any("Kim sifatida" in t for t in out), str(out)[:70])
    out = await feed(press("p:role:worker", 90))
    check("telefon so'raldi", any("raqam" in t.lower() for t in out), str(out)[:70])
    # Telefonni HAQIQIY kontakt sifatida yuboramiz — holat shunda o'tadi.
    global UID
    UID += 1
    contact_update = Update(update_id=UID, message=Message(
        message_id=UID, date=datetime.now(),
        chat=Chat(id=90, type="private"),
        from_user=TgUser(id=90, is_bot=False, first_name="Yangi"),
        contact=Contact(phone_number="+998901112233", first_name="Yangi", user_id=90),
    ))
    out = await feed(contact_update)
    check("kontaktdan keyin hudud so'raldi",
          any("hudud" in t.lower() for t in out), str(out)[:70])
    out = await feed(press("p:rregion:Chilonzor", 90))
    check("ro'yxatda: hududdan keyin QIZIQISHLAR so'raladi",
          any("qiziq" in t.lower() for t in out), str(out)[:70])
    out = await feed(press("p:cat:__done__", 90))
    check("ro'yxat yakunida TABRIK chiqadi",
          any("Tayyor" in t for t in out), str(out)[:80])


    print("")
    print("== 10. Bazani tiklash (yangi)")
    out = await feed(press("s:restore", 5))
    check("tiklash so'ralди", any("tiklash" in t.lower() for t in out), str(out)[:70])
    out = await feed(send_file("hujjat.pdf", 5))
    check("noto'g'ri fayl rad etildi",
          any("o‘xshamaydi" in t or "xshamaydi" in t for t in out), str(out)[:70])
    out = await feed(send_file("katta.db.gz", 5, size=30 * 1024 * 1024))
    check("20 MB dan katta fayl rad etildi",
          any("20 MB" in t for t in out), str(out)[:70])
    out = await feed(say("matn yubordim", 5))
    check("matn emas, fayl so'raldi", any("faylni" in t.lower() for t in out), str(out)[:70])
    out = await feed(say("/cancel", 5))
    check("bekor qilindi", bool(out) and no_error(out), str(out)[:70])

    print("")
    print("== 11. Tiklash faqat EGASIGA")
    out = await feed(press("s:restore", 2))
    check("oddiy ishchi tiklay olmaydi",
          not any("tiklash" in t.lower() for t in out), str(out)[:70])
    out = await feed(press("rs:yes", 2))
    check("tasdiq tugmasi ham ishlamaydi",
          not any("tiklandi" in t.lower() for t in out), str(out)[:70])

    await engine.dispose()
    DB.unlink(missing_ok=True)
    for suf in ("-wal", "-shm"):
        pathlib.Path(DB.name + suf).unlink(missing_ok=True)

    print("")
    if failures:
        print("NATIJA: " + str(failures) + " ta muammo")
        sys.exit(1)
    print("NATIJA: oqim testlari o'tdi")


asyncio.run(main())
