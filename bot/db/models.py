"""Ma'lumotlar modeli.

To'rtta jadval:
  settings — bot sozlamalari (kanal, karta, summa) — bot ichidan boshqariladi
  users    — ishchi / ish beruvchi / admin
  jobs     — ish e'loni (ochiq qismi + faqat to'laganlar ko'radigan sir qismi)
  bookings — kim qaysi ishga yozildi, to'lovi qaysi holatda, navbatdami
"""

from __future__ import annotations

import enum
from datetime import date, datetime, time, timezone

from bot.config import TZ

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Vaqtni doim UTC da saqlaydigan va UTC da qaytaradigan ustun turi.

    SQLite vaqt zonasini saqlamaydi: yozganda "zonali", o'qiganda "zonasiz"
    qaytadi va taqqoslash xato bilan yiqiladi. Shu turdan foydalanamiz.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- enumlar

class Role(str, enum.Enum):
    WORKER = "WORKER"        # ish qidiruvchi
    EMPLOYER = "EMPLOYER"    # ish beruvchi
    MODERATOR = "MODERATOR"  # chek tekshiradi, e'lon joylaydi
    ADMIN = "ADMIN"          # + sozlamalar, moliya, moderatorlarni boshqarish


# Xodimlar — chek tekshirish va e'lon joylash huquqiga egalar.
STAFF_ROLES = (Role.MODERATOR, Role.ADMIN)


class JobStatus(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"  # ish beruvchi yubordi, admin tekshiryapti
    OPEN = "OPEN"                      # yozilish ochiq
    FULL = "FULL"                      # joylar to'ldi
    CLOSED = "CLOSED"                  # yopilgan / sanasi o'tgan
    CANCELLED = "CANCELLED"            # bekor qilingan
    DECLINED = "DECLINED"              # admin e'lonni rad etdi


ACTIVE_JOB_STATUSES = (JobStatus.OPEN, JobStatus.FULL)


class BookingStatus(str, enum.Enum):
    WAITLIST = "WAITLIST"                # navbatda, hali to'lov talab qilinmagan
    PENDING_PAYMENT = "PENDING_PAYMENT"  # joy bron qilindi, chek kutilyapti
    RECEIPT_SENT = "RECEIPT_SENT"        # chek yuborildi, admin qarori kutilyapti
    CONFIRMED = "CONFIRMED"              # tasdiqlandi, sir ma'lumot berildi
    COMPLETED = "COMPLETED"              # ishga chiqdi (ish yakunlandi)
    REJECTED = "REJECTED"                # admin chekni rad etdi
    CANCELLED = "CANCELLED"              # ishchi o'zi (o'z vaqtida) bekor qildi
    LATE_CANCEL = "LATE_CANCEL"          # ish oldidan bekor qildi — joy bo'shadi,
                                         # lekin ishonchlilikka ta'sir qiladi
    EXPIRED = "EXPIRED"                  # vaqtida chek yubormadi
    NO_SHOW = "NO_SHOW"                  # yozilib, aytmasdan ishga chiqmadi


# Joyni "band" deb hisoblanadigan holatlar. Navbat (WAITLIST) joy egallamaydi.
OCCUPYING = (
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.RECEIPT_SENT,
    BookingStatus.CONFIRMED,
    BookingStatus.COMPLETED,
    BookingStatus.NO_SHOW,  # ishga chiqmagan bo'lsa ham joy o'shaniki edi
)

# Ish tafsilotlarini ko'ra oladigan holatlar.
UNLOCKED = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW)


class ReportStatus(str, enum.Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------- jadvallar

class Setting(Base):
    """Oddiy kalit-qiymat jadvali.

    Nega alohida jadval, .env emas? Chunki kanal ID, karta raqami, to'lov
    summasi — ishlash davomida o'zgaradigan narsalar. Ularni bot ichidan
    o'zgartirib, botni qayta ishga tushirmaslik kerak.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str | None] = mapped_column(String(32))
    region: Mapped[str | None] = mapped_column(String(64), index=True)
    role: Mapped[Role] = mapped_column(SAEnum(Role), default=Role.WORKER, index=True)
    # Interfeys tili: "uz" yoki "ru".
    lang: Mapped[str] = mapped_column(String(2), default="uz")

    # Obuna qilingan kasblar. "|yuk|qurilish|" ko'rinishida saqlanadi —
    # chekkalardagi ajratgichlar tufayli LIKE '%|yuk|%' aniq ishlaydi va
    # "yuk" so'zi "yuklash" ichida qolib ketmaydi.
    categories: Mapped[str] = mapped_column(Text, default="")

    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    # Foydalanuvchi botni bloklab qo'ysa False bo'ladi — keyingi tarqatishlarda
    # unga urinmaymiz. Minglab foydalanuvchida bu tezlikni sezilarli oshiradi.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    no_show_count: Mapped[int] = mapped_column(Integer, default=0)

    # Referal. invited_by — kim chaqirgan; referral_rewarded — chaqiruvchiga
    # mukofot berilgan-berilmagani (bir odam uchun bir marta).
    invited_by: Mapped[int | None] = mapped_column(BigInteger, index=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    invited_count: Mapped[int] = mapped_column(Integer, default=0)

    # Bepul yozilish bonuslari. Pulli e'longa to'lovsiz yozilish uchun.
    free_credits: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    @property
    def is_registered(self) -> bool:
        return bool(self.phone and self.region)

    @property
    def category_keys(self) -> list[str]:
        return [c for c in (self.categories or "").split("|") if c]

    @property
    def mention(self) -> str:
        tag = f"@{self.username}" if self.username else f"id{self.id}"
        return f"{self.full_name} ({tag})"

    @property
    def reliability(self) -> str:
        total = self.completed_count + self.no_show_count
        if total == 0:
            return "yangi"
        return f"{self.completed_count}/{total} ishga chiqqan"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Ishchi ro'yxatidagi asosiy so'rov: ochiq + kelajakdagi sanalar.
        Index("ix_job_feed", "status", "work_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), default="boshqa", index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)

    # Manzil, mas'ul odam, telefon — FAQAT to'lovi tasdiqlangan ishchiga.
    secret_details: Mapped[str] = mapped_column(Text)

    region: Mapped[str] = mapped_column(String(64), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String(16))

    salary: Mapped[int] = mapped_column(Integer)
    fee: Mapped[int] = mapped_column(Integer)
    slots_total: Mapped[int] = mapped_column(Integer)

    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus), default=JobStatus.OPEN, index=True
    )
    decline_reason: Mapped[str | None] = mapped_column(String(256))

    # Xarita nuqtasi. Manzil matni secret_details ichida bo'ladi; bu esa
    # bosib borsa bo'ladigan lokatsiya — to'lov tasdiqlangach yuboriladi.
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)

    # ESKI maydon. Endi postlar job_posts jadvalida (bir e'lon — ko'p kanal).
    # Eski ma'lumot buzilmasligi uchun qoldirildi.
    channel_message_id: Mapped[int | None] = mapped_column(Integer)

    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    # Ish tugagach yozilganlarni belgilash so'rovi yuborilganmi.
    attendance_asked: Mapped[bool] = mapped_column(Boolean, default=False)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="job")
    posts: Mapped[list["JobPost"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    @property
    def starts_at(self) -> datetime:
        """Ish boshlanish vaqti — UTC da.

        Bazada sana va vaqt alohida (matn) saqlanadi, chunki admin ularni
        alohida kiritadi. Eslatma yuborish uchun esa aniq moment kerak.
        """
        try:
            hh, mm = (self.start_time or "08:00").split(":")
            local_time = time(int(hh), int(mm))
        except (ValueError, AttributeError):
            local_time = time(8, 0)
        return datetime.combine(self.work_date, local_time, tzinfo=TZ).astimezone(timezone.utc)
    # Bu bog'lanish mantiq uchun emas, YOZISH TARTIBI uchun kerak: SQLAlchemy
    # faqat relationship orqali "avval user, keyin job" ekanini tushunadi.
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("job_id", "user_id", name="uq_booking_job_user"),
        Index("ix_booking_status", "status"),
        Index("ix_booking_expiry", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)

    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus), default=BookingStatus.PENDING_PAYMENT
    )

    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    # Eslatmalar bir marta yuborilishi uchun belgilar.
    reminded_evening: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_soon: Mapped[bool] = mapped_column(Boolean, default=False)
    attendance_asked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bonus hisobiga (to'lovsiz) yozilganmi — statistikada ajratish uchun.
    used_credit: Mapped[bool] = mapped_column(Boolean, default=False)

    # Navbatga qachon yozilgani — kim oldin turgani shu bo'yicha aniqlanadi.
    queued_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    reject_reason: Mapped[str | None] = mapped_column(String(256))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    job: Mapped[Job] = relationship(back_populates="bookings")
    user: Mapped[User] = relationship()


class Report(Base):
    """Foydalanuvchi shikoyati / murojaati.

    Real pul aylanganda bu majburiy: «ish e'londagidek emas edi»,
    «pul to'lanmadi», «manzil noto'g'ri». Busiz odam shikoyatini
    ochiq kanalga yozadi va obro'ingizga zarar yetadi.
    """

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    text: Mapped[str] = mapped_column(Text)

    status: Mapped[ReportStatus] = mapped_column(
        SAEnum(ReportStatus), default=ReportStatus.OPEN, index=True
    )
    answer: Mapped[str | None] = mapped_column(Text)
    handled_by: Mapped[int | None] = mapped_column(BigInteger)
    handled_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    user: Mapped[User] = relationship()
    job: Mapped[Job | None] = relationship()


class Channel(Base):
    """E'lon joylanadigan kanal yoki guruh.

    Bir nechta bo'lishi mumkin va har biriga FILTR biriktiriladi: masalan
    «Chilonzor ishlari» kanaliga faqat Chilonzor e'lonlari boradi. Bu
    ko'p kanalning asosiy kamchiligini — bir odam bir e'lonni bir necha
    marta ko'rishini — sezilarli kamaytiradi.
    """

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(16), default="channel")  # channel | group

    # "|Chilonzor|Sergeli|" ko'rinishida. Bo'sh bo'lsa — barcha hududlar.
    regions: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[str] = mapped_column(Text, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    @property
    def region_list(self) -> list[str]:
        return [x for x in (self.regions or "").split("|") if x]

    @property
    def category_list(self) -> list[str]:
        return [x for x in (self.categories or "").split("|") if x]

    def accepts(self, region: str, category: str) -> bool:
        if self.regions and f"|{region}|" not in self.regions:
            return False
        if self.categories and f"|{category}|" not in self.categories:
            return False
        return True


class JobPost(Base):
    """Bitta e'lonning bitta kanaldagi posti.

    last_hash — oxirgi joylangan matnning barmoq izi. Tahrirlashdan oldin
    solishtiramiz: matn o'zgarmagan bo'lsa Telegramga umuman murojaat
    qilmaymiz. 10 kanal x 50 e'lon x kuniga 10 o'zgarish = 5000 so'rov
    bo'lardi; bu tekshiruv uni bir necha barobar kamaytiradi.
    """

    __tablename__ = "job_posts"
    __table_args__ = (UniqueConstraint("job_id", "chat_id", name="uq_post_job_chat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    last_hash: Mapped[str] = mapped_column(String(32), default="")

    job: Mapped[Job] = relationship(back_populates="posts")
