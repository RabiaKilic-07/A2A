"""Rezervasyon durumu (state) ve doğrulama yardımcıları — SAĞLAYICIDAN BAĞIMSIZ."""

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

REQUIRED = ["check_in", "check_out", "room_type", "view_type", "children_count"]


@dataclass
class ReservationState:
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    room_type: Optional[str] = None
    view_type: Optional[str] = None
    children_count: Optional[int] = None
    children_ages: Optional[list] = None
    availability_confirmed_for: Optional[str] = None   # KAPI: müsait bulunan parametrelerin parmak izi
    booking_id: Optional[str] = None                   # dolunca active_flow serbest kalır


def missing_fields(state: ReservationState) -> list:
    missing = [f for f in REQUIRED if getattr(state, f) is None]
    if state.children_count and state.children_count > 0:      # çocuk yaşı KOŞULLU
        if not state.children_ages or len(state.children_ages) != state.children_count:
            missing.append("children_ages")
    return missing


def fingerprint(state: ReservationState) -> str:
    payload = {f: getattr(state, f) for f in REQUIRED + ["children_ages"]}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
