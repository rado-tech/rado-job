"""Loyiha sozlamalari.

MUHIM o'zgarish: .env da endi faqat O'ZGARMAYDIGAN narsalar qoldi —
token, adminlar ro'yxati va baza manzili. Kanal, karta raqami, to'lov
summasi kabi narsalar BAZADA saqlanadi va bot ichidan o'zgartiriladi
(bot/services/settings.py).

Sabab: kanal ID sini qo'lda topib, faylga yozib, botni qayta ishga
tushirish — xato chiqadigan joy. Telegram guruhni supergruppaga
aylantirganda ID o'zgaradi va hammasi buziladi. Bot ID ni o'zi topib,
o'zi saqlagani ancha ishonchli.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# O'zbekiston vaqti = UTC+5, yozgi/qishki o'zgarish yo'q.
TZ = timezone(timedelta(hours=5), "Asia/Tashkent")
UTC = timezone.utc


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str
    admin_ids: str = ""
    log_level: str = "INFO"

    # HAMMA saqlanadigan narsa shu papkaga tushadi: baza, zaxira nusxalar,
    # jurnal. Bitta joyda bo'lgani uchun uni Railway/Docker'da bitta Volume
    # sifatida ulash kifoya — boshqa hech narsani o'zgartirish shart emas.
    #
    # Mahalliy kompyuterda: "." (loyiha papkasi, hozirgidek)
    # Railway'da:           "/data" (ulangan Volume)
    data_dir: str = "."

    # Bo'sh qoldirilsa — data_dir ichidagi SQLite fayli.
    # PostgreSQL: postgresql+asyncpg://user:parol@host/baza
    db_url: str = ""

    # Quyidagilar faqat BIRINCHI ishga tushishda bazaga ko'chiriladi.
    # Keyin bot ichidagi «⚙️ Sozlamalar» dan boshqariladi.
    card_number: str = ""
    card_holder: str = ""
    default_fee: int = 10_000
    hold_minutes: int = 15
    channel_id: str = ""
    moderation_chat_id: str = ""

    @property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x.strip("-").isdigit()}

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        # Absolyut yo'l — bot qaysi papkadan ishga tushirilishidan qat'i nazar
        # baza doim bitta joyda bo'ladi.
        return f"sqlite+aiosqlite:///{(self.data_path / 'rado_job.db').as_posix()}"

    @property
    def backups_path(self) -> Path:
        path = self.data_path / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs_path(self) -> Path:
        path = self.data_path / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()  # type: ignore[call-arg]


# ---------------------------------------------------------------- hududlar

REGIONS: list[str] = [
    "Bektemir",
    "Chilonzor",
    "Mirobod",
    "Mirzo Ulug'bek",
    "Olmazor",
    "Sergeli",
    "Shayxontohur",
    "Uchtepa",
    "Yakkasaroy",
    "Yashnobod",
    "Yangihayot",
    "Yunusobod",
    "Toshkent viloyati",
    "Boshqa hudud",
]


# ---------------------------------------------------------------- kasblar

# Kalit bazada saqlanadi (qisqa, o'zgarmaydi), nom foydalanuvchiga ko'rinadi.
# Nomni istalgan payt o'zgartirsangiz eski e'lonlar buzilmaydi.
CATEGORIES: list[tuple[str, str]] = [
    ("yuk", "📦 Yuk tashish"),
    ("qurilish", "🧱 Qurilish / ta'mir"),
    ("tozalash", "🧹 Tozalash"),
    ("ombor", "🏭 Ombor / zavod"),
    ("oshxona", "🍽 Oshxona / ofitsiant"),
    ("savdo", "🛒 Sotuvchi / promouter"),
    ("dala", "🌾 Dala / bog'"),
    ("kochirish", "🚚 Ko'chirish"),
    ("boshqa", "🔧 Boshqa"),
]

CATEGORY_NAMES: dict[str, str] = dict(CATEGORIES)


def category_name(key: str | None) -> str:
    return CATEGORY_NAMES.get(key or "", "🔧 Boshqa")


# Tez tanlash uchun tayyor qiymatlar — admin raqam terib o'tirmaydi.
QUICK_TIMES = ["06:00", "07:00", "08:00", "09:00", "10:00", "14:00"]
QUICK_SALARIES = [100_000, 150_000, 200_000, 250_000, 300_000, 400_000]
QUICK_SLOTS = [1, 2, 3, 5, 10, 20]
