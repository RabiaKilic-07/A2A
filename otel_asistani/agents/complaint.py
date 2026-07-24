"""Şikayet subagent'ı (STUB) — kendi thread'i (session.complaint_msgs) var."""

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text
from ..prompt_rules import NUMBERS_AS_WORDS
from ..session import Session, reservation_nudge

COMPLAINT_SYSTEM = """Sen otelin şikayet ve talep asistanısın. Kullanıcının şikayet/talebini
anlayışla karşıla, gerekli detayları (oda no, tarih, sorun) nazikçe sor, sonra kaydedildiğini bildir.
Türkçe konuş.
""" + NUMBERS_AS_WORDS


def run_complaint_subagent(session: Session) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=session.complaint_msgs,
        config=types.GenerateContentConfig(
            system_instruction=COMPLAINT_SYSTEM + reservation_nudge(session),
        ),
    )
    content = response.candidates[0].content
    session.complaint_msgs.append(content)
    return content_text(content)
