"""Genel sohbet akışı — kendi thread'i (session.chat_msgs).

Normal muhabbet + router'ın VARSAYILAN/YEDEK akışı.
"""

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text
from ..prompt_rules import NUMBERS_AS_WORDS
from ..raw_log import log_llm_call
from ..session import Session, record_usage, reservation_nudge

CHAT_SYSTEM = """Sen bir otelin samimi, yardımsever asistanısın. Kullanıcıyla normal, doğal
bir şekilde Türkçe sohbet et. Kullanıcı rezervasyon, otel bilgisi veya şikayet konusuna
girmek isterse bu konularda yardımcı olabileceğini kısaca hatırlat, ama zorlama.
""" + NUMBERS_AS_WORDS


def run_chat_agent(session: Session) -> str:
    system = CHAT_SYSTEM + reservation_nudge(session)
    response = client.models.generate_content(
        model=MODEL,
        contents=[m for m in session.chat_msgs if m is not None],   # None'ları süz (kirli geçmiş koruması)
        config=types.GenerateContentConfig(system_instruction=system),
    )
    record_usage(session, response)
    log_llm_call(session, "CHAT", system=system, contents=session.chat_msgs,
                 response=response, model=MODEL)
    content = response.candidates[0].content if response.candidates else None
    if content is None:                                # boş content'i geçmişe ekleme (None kirliliği)
        return "Üzgünüm, şu an yanıt oluşturamadım. Tekrar dener misiniz?"
    session.chat_msgs.append(content)
    return content_text(content)
