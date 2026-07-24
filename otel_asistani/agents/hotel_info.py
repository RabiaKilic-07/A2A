"""hotel_info (RAG STUB, hafızalı) — gerçek retrieval ile değiştir.

Kendi mesaj thread'i (session.hotel_info_msgs) vardır → takip soruları çalışır.
"""

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text, user_content
from ..session import Session, reservation_nudge

HOTEL_KB = """
- Wifi: tüm otelde ücretsiz, şifre GUEST2026
- Kahvaltı: 07:00-10:30, açık büfe, konaklamaya dahil
- Check-in 14:00, check-out 12:00
- Spa & havuz: 09:00-21:00
- Otopark: ücretsiz
- Konum: sahile 200 metre
"""

HOTEL_INFO_SYSTEM = ("Otel bilgi asistanısın. SADECE aşağıdaki bilgilere dayanarak Türkçe yanıtla; "
                     "bilmiyorsan resepsiyona yönlendir.\n\nOTEL BİLGİLERİ:\n" + HOTEL_KB)


def run_rag(session: Session, user_text: str) -> str:
    session.hotel_info_msgs.append(user_content(user_text))
    response = client.models.generate_content(
        model=MODEL,
        contents=session.hotel_info_msgs,       # kendi thread'i → takip soruları çalışır
        config=types.GenerateContentConfig(
            system_instruction=HOTEL_INFO_SYSTEM + reservation_nudge(session),
        ),
    )
    content = response.candidates[0].content
    session.hotel_info_msgs.append(content)
    return content_text(content)
