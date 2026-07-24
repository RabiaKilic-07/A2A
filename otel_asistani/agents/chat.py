"""Genel sohbet akışı — kendi thread'i (session.chat_msgs).

Normal muhabbet + router'ın VARSAYILAN/YEDEK akışı.
"""

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text
from ..prompt_rules import NUMBERS_AS_WORDS
from ..session import Session, reservation_nudge

CHAT_SYSTEM = """Sen bir otelin samimi, yardımsever asistanısın. Kullanıcıyla normal, doğal
bir şekilde Türkçe sohbet et. Kullanıcı rezervasyon, otel bilgisi veya şikayet konusuna
girmek isterse bu konularda yardımcı olabileceğini kısaca hatırlat, ama zorlama.
""" + NUMBERS_AS_WORDS


def run_chat_agent(session: Session) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=session.chat_msgs,
        config=types.GenerateContentConfig(
            system_instruction=CHAT_SYSTEM + reservation_nudge(session),
        ),
    )
    content = response.candidates[0].content
    session.chat_msgs.append(content)
    return content_text(content)
