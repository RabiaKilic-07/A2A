"""Otel envanteri — mock veritabanı (data/rooms.json'dan okunur).

Gerçek envanter/DB ile değiştir. Her satır, belirli bir oda konfigürasyonudur:
oda türü, kapasite (min/max kişi), manzara tipi, yatak dizilişi, gecelik fiyat, dolu tarihler.
"""

import json
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

_DB_PATH = Path(__file__).with_name("data") / "rooms.json"


def _load_rooms() -> list:
    with open(_DB_PATH, encoding="utf-8") as f:
        return json.load(f)["rooms"]


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _date_available(room: dict, check_in, check_out) -> bool:
    """Oda, [check_in, check_out) aralığında dolu bir güne denk gelmiyorsa müsait."""
    blocked = room.get("unavailable_dates") or []
    if not blocked:
        return True
    try:
        start, end = date.fromisoformat(check_in), date.fromisoformat(check_out)
    except (TypeError, ValueError):
        return True                     # tarih ayrıştırılamıyorsa mock: engel yok
    for d in blocked:
        try:
            if start <= date.fromisoformat(d) < end:
                return False
        except ValueError:
            continue
    return True


class HotelBackend:
    def __init__(self):
        self.rooms = _load_rooms()

    def _matches(self, room, *, check_in, check_out, total_guests, room_type) -> bool:
        if _norm(room["room_type"]) != _norm(room_type):
            return False
        if total_guests is not None and not (room["min_guests"] <= total_guests <= room["max_guests"]):
            return False
        return _date_available(room, check_in, check_out)

    def search_options(self, *, check_in, check_out, total_guests, room_type) -> list:
        """4 filtreye uyan odaların (manzara, yatak dizilişi, fiyat) seçeneklerini döndürür."""
        return [
            {
                "view_type": room["view_type"],
                "bed_layout": room["bed_layout"],
                "price_per_night": room["price_per_night"],
            }
            for room in self.rooms
            if self._matches(room, check_in=check_in, check_out=check_out,
                             total_guests=total_guests, room_type=room_type)
        ]

    def find_room(self, *, check_in, check_out, total_guests, room_type, view_type, bed_layout):
        """Seçilen (manzara + yatak dizilişi) kombinasyonuna uyan odayı döndürür; yoksa None."""
        for room in self.rooms:
            if (self._matches(room, check_in=check_in, check_out=check_out,
                              total_guests=total_guests, room_type=room_type)
                    and _norm(room["view_type"]) == _norm(view_type)
                    and _norm(room["bed_layout"]) == _norm(bed_layout)):
                return room
        return None

    def book(self, room: dict):
        return SimpleNamespace(id="RSV-" + uuid.uuid4().hex[:8].upper(), room_id=room["id"])


hotel_backend = HotelBackend()
