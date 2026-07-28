"""Şikayet subagent'ı (STUB) — kendi thread'i (session.complaint_msgs) var."""

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text
from ..prompt_rules import NUMBERS_AS_WORDS
from ..raw_log import log_llm_call
from ..session import Session, record_usage, reservation_nudge

COMPLAINT_SYSTEM = """Sen otelin şikayet ve talep asistanısın. Kullanıcının şikayet/talebini
anlayışla karşıla, gerekli detayları (oda no, tarih, sorun) nazikçe sor, sonra kaydedildiğini bildir.
Türkçe konuş.
""" + NUMBERS_AS_WORDS


def run_complaint_subagent(session: Session) -> str:
    system = COMPLAINT_SYSTEM + reservation_nudge(session)
    response = client.models.generate_content(
        model=MODEL,
        contents=[m for m in session.complaint_msgs if m is not None],   # None'ları süz (kirli geçmiş koruması)
        config=types.GenerateContentConfig(system_instruction=system),
    )
    record_usage(session, response)
    log_llm_call(session, "COMPLAINT", system=system, contents=session.complaint_msgs,
                 response=response, model=MODEL)
    content = response.candidates[0].content if response.candidates else None
    if content is None:                                # boş content'i geçmişe ekleme (None kirliliği)
        return "Üzgünüm, şu an yanıt oluşturamadım. Tekrar dener misiniz?"
    session.complaint_msgs.append(content)
    return content_text(content)
