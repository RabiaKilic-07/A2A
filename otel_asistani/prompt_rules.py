"""Tüm asistan promptlarında ortak kullanılan kurallar."""

# Kullanıcıya yazılan metinde sayılar RAKAMLA değil YAZIYLA yazılır.
# Not: Bu yalnızca kullanıcıya gösterilen metin içindir; araçlara (tool) gönderilen
# tarih/sayı parametreleri her zaman normal rakamlarla ve gereken formatta verilir.
NUMBERS_AS_WORDS = (
    "SAYI YAZIMI: Kullanıcıya yazdığın metinde TÜM sayıları rakamla değil YAZIYLA yaz "
    "(ör. '2' yerine 'iki', '3 gece' yerine 'üç gece', 'saat 14:00' yerine 'saat on dört', "
    "'5000 TL' yerine 'beş bin TL'). Bu kural yalnızca kullanıcıya gösterilen metin içindir; "
    "araçlara (tool) gönderdiğin tarih/sayı parametrelerini her zaman rakamla ve gereken "
    "formatta (ör. YYYY-MM-DD) ver."
)

# Not: TTS bekleme (oyalama) cümleleri artık prompta gömülü değil; yalnızca iki noktada
# (hotel_info/RAG ve rezervasyonda bed_options öncesi) ayrıca üretilir. Bkz. wait_filler.py
