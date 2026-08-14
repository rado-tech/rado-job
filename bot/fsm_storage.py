"""aiogram FSM holatini SQLite'da saqlaydigan storage.

Nega MemoryStorage emas? Bot qayta ishga tushganda (Railway deploy, xato,
server restarti) xotiradagi holat yo'qoladi: e'lonni 8-qadamgacha yozgan
ish beruvchi hammasini boshidan boshlashga majbur bo'lardi. Endi holat
bazada — restart foydalanuvchiga umuman sezilmaydi.

Nega Redis emas? Bitta jarayon, bitta server: SQLite yetarli va yangi
xizmat talab qilmaydi. Har FSM amali bir necha ms — sekundiga o'nlab
so'rovda ham sezilmaydi.

Ma'lumot JSON bo'lib saqlanadi. Handler'lar faqat oddiy turlarni
(str/int/float/bool/None/ro'yxat) yozadi — smoke_test shuni tekshiradi.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import FsmState, utcnow

log = logging.getLogger(__name__)

# Shu muddatdan eski holatlar o'lik hisoblanadi va kuniga bir marta
# tozalanadi: 3 kun oldin boshlangan forma baribir davom ettirilmaydi.
STALE_HOURS = 72


class DbStorage(BaseStorage):
    def __init__(self, session_maker) -> None:  # noqa: ANN001
        self._maker = session_maker

    @staticmethod
    def _key(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.destiny}"

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with self._maker() as session:
            row = await session.get(FsmState, self._key(key))
            if value is None:
                # Holat tugadi. Ma'lumot ham bo'sh bo'lsa qatorni butunlay
                # o'chiramiz — jadval keraksiz o'sib bormasin.
                if row is not None:
                    if row.data in ("", "{}"):
                        await session.delete(row)
                    else:
                        row.state = None
                        row.updated_at = utcnow()
                    await session.commit()
                return
            if row is None:
                session.add(FsmState(key=self._key(key), state=value))
            else:
                row.state = value
                row.updated_at = utcnow()
            await session.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._maker() as session:
            row = await session.get(FsmState, self._key(key))
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        async with self._maker() as session:
            row = await session.get(FsmState, self._key(key))
            if not data:
                # Bo'sh ma'lumot: holat ham yo'q bo'lsa qator kerak emas.
                if row is not None:
                    if row.state is None:
                        await session.delete(row)
                    else:
                        row.data = "{}"
                        row.updated_at = utcnow()
                    await session.commit()
                return
            packed = json.dumps(data, ensure_ascii=False)
            if row is None:
                session.add(FsmState(key=self._key(key), data=packed))
            else:
                row.data = packed
                row.updated_at = utcnow()
            await session.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._maker() as session:
            row = await session.get(FsmState, self._key(key))
            if row is None or not row.data:
                return {}
            try:
                return json.loads(row.data)
            except ValueError:
                # Buzuq yozuv butun oqimni to'xtatmasin — bo'sh deb qaraymiz.
                log.warning("FSM ma'lumoti buzuq: %s", self._key(key))
                return {}

    async def close(self) -> None:
        # Sessiyalar har amalda ochilib-yopiladi, ushlab turadigan narsa yo'q.
        pass


async def cleanup(session: AsyncSession, *, stale_hours: int = STALE_HOURS) -> int:
    """Eski FSM qatorlarini o'chiradi. Qancha o'chirilganini qaytaradi."""
    cutoff = utcnow() - timedelta(hours=stale_hours)
    result = await session.execute(delete(FsmState).where(FsmState.updated_at < cutoff))
    await session.commit()
    return int(result.rowcount or 0)


async def count(session: AsyncSession) -> int:
    from sqlalchemy import func

    return int(
        (await session.scalar(select(func.count()).select_from(FsmState))) or 0
    )
