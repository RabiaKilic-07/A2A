"""Rezervasyon subagent'ı — KENDİ mesaj thread'i + KENDİ tool'ları.

automatic_function_calling kapalıdır; tool döngüsü manuel yönetilir (dispatch).
Çağrılan her tool, session.turn_tool_log'a yazılır (konsolda gösterim için).
"""

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text
from ..reservation_tools import RESERVATION_TOOL, dispatch
from ..session import Session

RESERVATION_SYSTEM = """Sen bir otelin rezervasyon asistanısın. Amacın müsaitlik sorgulayıp
rezervasyonu tamamlamak.

Şu 6 bilgiyi topla: giriş tarihi, çıkış tarihi, oda türü, manzara tipi, çocuk sayısı,
(çocuk varsa) çocuk yaşları.

Kurallar:
- Kullanıcının verdiği bilgilerle check_availability'yi çağır — hepsini bilmesen de çağırabilirsin.
- Araç 'incomplete' + missing_fields dönerse YALNIZCA eksik alanları nazikçe sor (bir-iki tanesini birlikte).
- Rezervasyonu ancak check_availability 'available' döndükten sonra complete_reservation ile kesinleştir.
- Kullanıcı önceki bir bilgiyi değiştirmek isterse güncelle ve yeniden check_availability çalıştır.
- NİHAİ HEDEF rezervasyonu tamamlatmaktır. Kullanıcı konuyu dağıtsa ya da başka şeyler sorsa
  bile, kısaca yardımcı olduktan sonra kaldığın yerden eksik bilgileri toplamaya devam et ve
  rezervasyonu bitirmeye yönlendir.
- Türkçe, kısa ve net konuş."""

RESERVATION_CONFIG = types.GenerateContentConfig(
    system_instruction=RESERVATION_SYSTEM,
    tools=[RESERVATION_TOOL],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # manuel kontrol
)


def run_reservation_subagent(session: Session, max_iters: int = 8) -> str:
    for _ in range(max_iters):
        response = client.models.generate_content(
            model=MODEL,
            contents=session.reservation_msgs,
            config=RESERVATION_CONFIG,
        )
        candidate = response.candidates[0]
        session.reservation_msgs.append(candidate.content)     # model turu

        fcs = response.function_calls or []
        if not fcs:
            return content_text(candidate.content) or "(boş yanıt)"

        response_parts = []
        for fc in fcs:
            args = dict(fc.args or {})
            out = dispatch(session.reservation_state, fc.name, args)
            session.turn_tool_log.append((fc.name, args, out))     # ← tool logu
            response_parts.append(types.Part.from_function_response(name=fc.name, response=out))
        session.reservation_msgs.append(types.Content(role="user", parts=response_parts))

    return "Üzgünüm, işlemi tamamlayamadım. Lütfen tekrar dener misiniz?"
