"""Session state + 'yarım rezervasyon' nudge yardımcıları.

nudge, sapma akışlarına (hotel_info / complaint / chat) "önce yardım et, sonra
rezervasyona geri getir" talimatı ekleyerek nihai hedefi korur.
"""

from dataclasses import dataclass, field
from typing import Optional

from .reservation_state import STAGE1_FIELDS, ReservationState, missing_fields


@dataclass
class Session:
    active_flow: Optional[str] = None          # None | "reservation" | "complaint"
    reservation_msgs: list = field(default_factory=list)
    complaint_msgs: list = field(default_factory=list)
    hotel_info_msgs: list = field(default_factory=list)
    chat_msgs: list = field(default_factory=list)
    reservation_state: ReservationState = field(default_factory=ReservationState)
    last_target: Optional[str] = None                       # bu turda seçilen akış
    turn_tool_log: list = field(default_factory=list)       # bu turda çağrılan tool'lar


def reservation_in_progress(session: Session) -> bool:
    """Başlamış ama tamamlanmamış bir rezervasyon var mı? (active_flow'dan bağımsız)"""
    s = session.reservation_state
    started = bool(session.reservation_msgs) or any(getattr(s, f) is not None for f in STAGE1_FIELDS)
    return started and s.booking_id is None


def reservation_nudge(session: Session) -> str:
    """Yarım rezervasyon varsa, sapma akışlarına 'sonunda rezervasyona geri getir' talimatı ekler."""
    if not reservation_in_progress(session):
        return ""
    eksik = missing_fields(session.reservation_state)
    durum = f"eksik bilgiler: {eksik}" if eksik else "tüm bilgiler tam, onay bekleniyor"
    return ("\n\nÖNEMLİ BAĞLAM: Kullanıcının YARIM kalmış bir rezervasyonu var "
            f"({durum}). Önce mevcut sorusuna kısaca yardımcı ol, ardından kullanıcıyı nazikçe "
            "rezervasyonu tamamlamaya geri davet et. Nihai hedef rezervasyonun tamamlanmasıdır.")
