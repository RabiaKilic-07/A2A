"""Otel envanteri — mock veritabanı (data/rooms.json'dan okunur).

Gerçek envanter/DB ile değiştir. Her satır bir oda konfigürasyonudur:
oda türü, kapasite (min/max kişi), manzara tipi, yatak dizilişi, gecelik fiyat, dolu tarihler.

Planlama (birebir uyum / öneri / oda bölme) artık KODDA değil, Gemini'de yapılır. Backend yalnızca:
  * available_rooms : ENDPOINT — tarih + oda türüne göre gruplanmış müsaitliği (kaç adet oda) döner.
    Gemini bu veriye bakarak birebir varsa onu, yoksa alternatif önerir.
  * price_plan      : Gemini'nin seçtiği KARMA planı (oda listesi) DB'ye göre DOĞRULAR ve fiyatlar
    (booking güvencesi kodda kalır).
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

    def query_rooms(self, *, check_in, check_out, room_type=None) -> list:
        """DB SORGUSU: tarih uygun + (verilirse) oda türü eşleşen HAM oda kayıtlarını döndürür.
        (Gerçek DB'ye geçmek için burayı gerçek sorguyla değiştir.)"""
        return [
            r for r in self.rooms
            if _date_available(r, check_in, check_out)
            and (room_type is None or _norm(r["room_type"]) == _norm(room_type))
        ]

    def available_rooms(self, *, check_in, check_out, room_type=None) -> dict:
        """ENDPOINT: sorgu YALNIZCA oda türü + giriş/çıkış tarihine göredir (kişi sayısı KULLANILMAZ).
        Eşleşen odaları (oda türü + manzara + kapasite) kombinasyonuna göre GRUPLAR ve her grup için
        KAÇ ADET oda olduğunu (count) o grubun bilgileriyle birlikte döndürür.

        Ör. dönüş: {"room_type":"standart","total_rooms":5,
                    "groups":[{"room_type":"standart","view_type":"deniz","max_guests":2,
                               "price_per_night":4000,"count":1}, ...]}
        """
        rooms = self.query_rooms(check_in=check_in, check_out=check_out, room_type=room_type)
        groups = {}
        for r in rooms:
            key = (r["room_type"], r["view_type"], r["max_guests"])   # tür + manzara + kapasite
            group = groups.setdefault(key, {
                "room_type": r["room_type"],
                "view_type": r["view_type"],
                "max_guests": r["max_guests"],
                "price_per_night": r["price_per_night"],
                "count": 0,
            })
            group["count"] += 1
        return {
            "room_type": room_type,
            "total_rooms": len(rooms),
            "groups": sorted(groups.values(),
                             key=lambda g: (g["room_type"], g["view_type"], g["max_guests"])),
        }

    def price_plan(self, selections, *, check_in, check_out, room_type, total_guests):
        """Gemini'nin seçtiği KARMA planı DOĞRULAR ve fiyatlar.

        selections: [{"view_type","room_count"}, ...] — hepsi aynı oda türünden, farklı manzaralar
        BİRLİKTE olabilir (ör. 1 deniz + 1 bahçe). Her seçim için grubu bulur, o manzaradan yeterli
        oda olup olmadığını ve TOPLAM kapasitenin grubu aldığını kontrol eder, fiyatı toplar.
        Geçerliyse {"price_per_night","capacity","rooms":[...]} döner; değilse None.
        """
        groups = {
            _norm(g["view_type"]): g
            for g in self.available_rooms(check_in=check_in, check_out=check_out, room_type=room_type)["groups"]
        }
        used, capacity, price, detail = {}, 0, 0, []
        for sel in selections or []:
            view = _norm(sel.get("view_type"))
            count = sel.get("room_count") or 0
            group = groups.get(view)
            if group is None or count < 1:
                return None
            used[view] = used.get(view, 0) + count
            if used[view] > group["count"]:            # o manzaradan yeterli oda yok
                return None
            capacity += count * group["max_guests"]
            price += count * group["price_per_night"]
            detail.append({"view_type": group["view_type"], "room_count": count,
                           "max_guests": group["max_guests"], "price_per_night": group["price_per_night"]})
        if not detail or capacity < (total_guests or 0):   # boş seçim ya da kapasite yetmez
            return None
        return {"price_per_night": price, "capacity": capacity, "rooms": detail}

    def book(self):
        return SimpleNamespace(id="RSV-" + uuid.uuid4().hex[:8].upper())


hotel_backend = HotelBackend()
