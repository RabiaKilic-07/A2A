"""Tur yönetimi — router kararına göre ilgili akışa yönlendirir.

active_flow yönetimi:
  * reservation : akışı "reservation"a kilitler; booking tamamlanınca serbest bırakır.
  * complaint   : akışı "complaint"a alır.
  * hotel_info / chat : SAPMA/YEDEK akışlardır; active_flow'a dokunmaz (sticky router korunur).
"""

from .agents.chat import run_chat_agent
from .agents.complaint import run_complaint_subagent
from .agents.hotel_info import run_hotel_info
from .agents.reservation import run_reservation_subagent
from .agents.router import route
from .gemini_utils import user_content
from .session import Session


def handle_user_turn(session: Session, user_text: str) -> str:
    session.turn_tool_log = []                              # her tur logu sıfırla
    session.turn_tokens = 0                                 # her tur token sayaç sıfırla
    target = route(session, user_text)
    session.last_target = target

    if target == "reservation":
        session.active_flow = "reservation"
        session.reservation_msgs.append(user_content(user_text))
        reply = run_reservation_subagent(session)
        if session.reservation_state.booking_id is not None:
            session.active_flow = None          # rezervasyon bitti, akışı serbest bırak
        return reply

    if target == "hotel_info":
        return run_hotel_info(session, user_text)   # SAPMA: active_flow'a dokunma

    if target == "complaint":
        session.active_flow = "complaint"
        session.complaint_msgs.append(user_content(user_text))
        return run_complaint_subagent(session)

    if target == "chat":
        session.chat_msgs.append(user_content(user_text))   # YEDEK: active_flow'a dokunma
        return run_chat_agent(session)

    return "Anlayamadım, tekrar eder misiniz?"
