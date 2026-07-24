"""Router (orchestrator) — sticky sınıflandırıcı, structured output.

Tek görevi kullanıcının son mesajını dört akıştan birine yönlendirmektir.
structured output (response_schema) ile 'target' garantili bir enum olur.
"""

from typing import Literal

from pydantic import BaseModel
from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import last_model_question
from ..session import Session


class RouteDecision(BaseModel):
    target: Literal["reservation", "hotel_info", "complaint", "chat"]
    reason: str


ROUTER_SYSTEM = """Sen bir otel asistanının yönlendiricisisin (router).
Tek görevin: kullanıcının SON mesajını DÖRT akıştan birine yönlendirmek.

- reservation : oda ayırtma, müsaitlik sorgulama, tarih/oda/kişi/manzara/çocuk bilgisi
                verme, VE daha önce verdiği rezervasyon bilgisini değiştirme.
- hotel_info  : otelin özellikleri hakkında bilgi sorusu (wifi, kahvaltı, spa, konum, saatler).
- complaint   : şikayet, talep, sorun bildirme.
- chat        : selamlaşma, teşekkür, muhabbet, yukarıdaki üçüne girmeyen genel/serbest mesajlar.
                Bu VARSAYILAN/YEDEK akıştır — emin değilsen chat seç.

YAPIŞKAN (sticky) KURAL:
Şu anki aktif akış: {active_flow}
Rezervasyon asistanının sorduğu son soru: {son_soru}

- Aktif akış "reservation" ise, kullanıcı AÇIKÇA konu değiştirmediği sürece "reservation"da KAL.
  "deniz manzarası", "2 çocuk", "20 Temmuz", "deluxe" gibi kısa/eksik cevaplar rezervasyonun
  devamıdır — bunları chat veya hotel_info sanma.
- Kullanıcı normal sohbet ederken bir rezervasyon bilgisi/isteği verirse (tarih, oda türü,
  "oda ayırtmak istiyorum") reservation seç — sohbet içinde gelmiş olması fark etmez.
- Otel özelliği sorarsa hotel_info, şikayet/talep varsa complaint, geri kalan her şey chat."""


def route(session: Session, user_text: str) -> str:
    system = ROUTER_SYSTEM.format(
        active_flow=session.active_flow or "yok",
        son_soru=last_model_question(session.reservation_msgs) or "yok",
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=RouteDecision,      # structured output → target garantili enum
        ),
    )
    decision = response.parsed
    if decision is None:
        return "chat"                           # ayrıştırılamazsa güvenli varsayılan
    return decision.target
