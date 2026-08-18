"""Bot ishga tushgandan keyin bilinadigan qiymatlar.

Hozircha faqat bot username — kanaldagi tugmaga
https://t.me/<username>?start=job_12 havolasini yasash uchun kerak.
Uni har safar Telegram'dan so'ramaslik uchun bir marta olib, shu yerda
saqlaymiz.
"""

bot_username: str = ""


# Botni dastur ichidan to'xtatish. Bazani tiklashdan keyin kerak: fayl
# almashtirildi, xotiradagi kesh va ochiq ulanishlar esa ESKI bazaga
# tegishli. Eng ishonchli yo'l — jarayonni qayta ko'tarish.
#
# Railway/systemd buni avtomat qiladi. Lokal ishga tushirilgan bo'lsa
# bot shunchaki to'xtaydi va uni qo'lda qayta ishga tushirasiz —
# foydalanuvchiga shu haqda aytiladi.
stop_bot = None  # __main__ da o'rnatiladi: () -> None
