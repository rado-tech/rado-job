from aiogram import Router

from bot.handlers import ads, admin, base, common, jobpost, moderation, settings, worker


def build_router() -> Router:
    """Barcha handler'larni bitta routerga yig'adi.

    TARTIB MUHIM. aiogram xabarni routerlar bo'ylab yuqoridan pastga
    yuritadi va BIRINCHI mos kelgan handler'da to'xtaydi:

      base       — /cancel. Har qanday holatdan chiqish uchun eng birinchi.
      moderation — admin: chek/e'lon tasdiqlash (tor holat filtrlari)
      settings   — admin: sozlamalar
      ads        — admin: reklama tarqatish (Ad holatlari tor)
      admin      — admin: panel, statistika, foydalanuvchilar
      jobpost    — e'lon yaratish (admin ham, ish beruvchi ham)
      common     — /start, ro'yxatdan o'tish, profil, navigatsiya
      worker     — ishchi: qidiruv, yozilish, chek (eng keng filtrlar)

    Admin routerlari birinchi turadi, chunki ularning filtrlari torroq
    (faqat ADMIN_IDS). Admin bo'lmagan foydalanuvchining xabari ularga
    umuman tegmasdan keyingi routerga o'tadi.
    """
    router = Router(name="root")
    router.include_router(base.router)
    router.include_router(moderation.router)
    router.include_router(settings.router)
    router.include_router(ads.router)
    router.include_router(admin.router)
    router.include_router(jobpost.router)
    router.include_router(common.router)
    router.include_router(worker.router)
    return router
