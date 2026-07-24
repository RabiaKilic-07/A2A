"""Otel arka ucu (STUB) — gerçek envanter/DB ile değiştir."""

import uuid
from types import SimpleNamespace

from .reservation_state import ReservationState


class HotelBackend:
    def is_available(self, state: ReservationState) -> bool:
        return True  # demo: her zaman müsait

    def price(self, state: ReservationState) -> str:
        return "5000 TL/gece"

    def book(self, state: ReservationState):
        return SimpleNamespace(id="RSV-" + uuid.uuid4().hex[:8].upper())


hotel_backend = HotelBackend()
