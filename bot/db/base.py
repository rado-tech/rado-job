"""Baza ulanishi va sxemani yangilash.

SQLite bilan boshlaymiz — server o'rnatish kerak emas. PostgreSQL'ga o'tish
uchun .env dagi DB_URL ni almashtirish kifoya:
    DB_URL=postgresql+asyncpg://user:pass@localhost/rado_job
"""

from __future__ import annotations

import logging

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateIndex

from bot.config import settings
from bot.db.models import Base

log = logging.getLogger(__name__)

IS_SQLITE = settings.database_url.startswith("sqlite")

engine = create_async_engine(
    settings.database_url,
    echo=False,
    # SQLite'da ulanishlar soni cheklangan; boshqa bazalarda bu parametr
    # avtomat e'tiborsiz qoladi.
    pool_pre_ping=True,
)

# expire_on_commit=False — commit'dan keyin obyekt maydonlari o'qishga tayyor
# turaveradi. Async muhitda bu majburiy: aks holda oddiy `user.region`
# murojaati kutilmagan so'rovga aylanadi va MissingGreenlet xatosi chiqadi.
SessionMaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if IS_SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        """SQLite'ni ko'p foydalanuvchiga tayyorlaymiz.

        WAL: o'qish va yozish bir-birini bloklamaydi. Busiz e'lon chiqqan
        zahoti 50 kishi bosganda «database is locked» xatolari yog'iladi.
        busy_timeout: baza band bo'lsa darrov xato bermay, 5 soniya kutadi.
        """
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        # synchronous=FULL — har tranzaksiya diskka kafolatli yoziladi.
        # NORMAL tezroq, lekin TOK O'CHSA oxirgi bir necha yozuv yo'qolishi
        # mumkin. Bizda yozuv kam (kuniga bir necha ming), lekin har biri
        # odamning puli — tezlikni emas, ishonchlilikni tanlaymiz.
        cur.execute("PRAGMA synchronous=FULL")
        cur.close()


def _upgrade_schema(conn) -> None:  # noqa: ANN001
    """Yetishmayotgan ustun va indekslarni qo'shadi.

    Nega kerak? `create_all` faqat YO'Q jadvalni yaratadi; mavjud jadvalga
    yangi ustun qo'shmaydi. Yangi funksiya qo'shganimizda (masalan kasb turi)
    bazani o'chirib tashlash — real foydalanuvchilar ma'lumotini yo'qotish
    demak. Shuning uchun har ishga tushishda sxemani solishtirib, farqini
    ALTER TABLE bilan qo'shib qo'yamiz.

    Bu Alembic emas: ustun o'chirish yoki turini o'zgartirishni bilmaydi.
    Loyiha kattarganda Alembic'ga o'tamiz. Hozirgi bosqichda shu yetarli.
    """
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(conn.dialect)}'
            default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
            if default is not None:
                literal = f"'{default}'" if isinstance(default, str) else str(int(default))
                ddl += f" DEFAULT {literal}"
            conn.execute(text(ddl))
            log.warning("Sxema yangilandi: %s.%s ustuni qo'shildi", table.name, column.name)

        have_idx = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have_idx:
                conn.execute(CreateIndex(index, if_not_exists=True))
                log.warning("Sxema yangilandi: %s indeksi qo'shildi", index.name)


def _collect_pending(conn) -> list[str]:  # noqa: ANN001
    """Sxemada nima o'zgarishi kerakligini SANAYDI, lekin o'zgartirmaydi.

    Buni alohida ajratdik: o'zgarish bo'ladigan bo'lsa, ALTER TABLE dan
    OLDIN zaxira nusxa olamiz. Migratsiya xato ketsa qaytadigan joy bo'lsin.
    """
    inspector = inspect(conn)
    existing = set(inspector.get_table_names())
    pending: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            pending.append(f"yangi jadval: {table.name}")
            continue
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in have:
                pending.append(f"{table.name}.{column.name}")
    return pending


async def pending_schema_changes() -> list[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(_collect_pending)


async def integrity_check() -> str:
    """Baza buzilmaganini tekshiradi.

    SQLite buzilishi kam uchraydi, lekin uchraganda jimgina uchraydi —
    xato faqat o'sha buzuq sahifaga tegilganda chiqadi, ya'ni oylar keyin.
    Har ishga tushishda tekshirib, muammoni ERTA bilib olamiz.
    """
    if not IS_SQLITE:
        return "ok"
    async with engine.connect() as conn:
        row = (await conn.exec_driver_sql("PRAGMA quick_check")).scalar()
    return str(row or "ok")


async def checkpoint() -> None:
    """WAL faylini asosiy bazaga ko'chiradi.

    To'xtatishdan oldin chaqiriladi: shundan keyin baza fayli o'zi
    yetarli bo'ladi va uni bemalol ko'chirish mumkin.
    """
    if not IS_SQLITE:
        return
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        log.warning("WAL checkpoint bajarilmadi: %s", e)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_schema)
