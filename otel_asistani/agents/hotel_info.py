"""hotel_info — otel sorularını mock veritabanından (data/hotel_info.json) yanıtlar.

Gerçek RAG/LLM YAPILMAZ: bilgi doğrudan mock DB'den anahtar kelimeyle çekilir; DB gecikmesi
time.sleep ile TAKLİT edilir (set timeout benzeri). Bu akışta bekleme (oyalama) cümlesi ÜRETİLMEZ.
"""

import time

from ..gemini_utils import user_content
from ..hotel_info_db import lookup
from ..session import Session, missing_fields, reservation_in_progress

HOTEL_DB_DELAY = 3.0   # saniye — DB'den veri geliyormuş gibi bekletme (set timeout benzeri)


def run_hotel_info(session: Session, user_text: str) -> str:
    session.hotel_info_msgs.append(user_content(user_text))
    time.sleep(HOTEL_DB_DELAY)       # DB'den veri geliyormuş gibi beklet
    reply = lookup(user_text)        # mock DB'den veriyi çek (RAG yok)
    if reservation_in_progress(session):
        if not missing_fields(session.reservation_state):
            reply += "\n\nBu arada, onayınızı bekleyen bir rezervasyon işleminiz bulunuyor. Rezervasyon özetinizi onaylayarak tamamlamak ister misiniz?"
        else:
            reply += "\n\nBu arada, devam etmekte olan bir rezervasyon işleminiz bulunuyor. Kaldığımız yerden devam etmek ister misiniz?"
    return reply
