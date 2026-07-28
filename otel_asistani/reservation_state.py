"""Rezervasyon durumu (state) ve AŞAMALI doğrulama — SAĞLAYICIDAN BAĞIMSIZ.

Akış:
  1) Aşama-1 (zorunlu 4 alan): check_in, check_out, total_guests, room_type. Tümü TEK seferde alınır.
     (view_type = tercih edilen manzara, opsiyoneldir; children_* de bu aşamada birlikte toplanır.)
     → bed_options, DB endpoint'inden gruplanmış müsaitliği Gemini'ye verir.
  2) Seçim: Gemini müsaitliğe göre önerir; kullanıcı seçince karma plan (selected_rooms) kaydedilir.
  3) Çocuk bilgisi zaten aşama-1'de alınır; complete_reservation özetler + onaylatır.

Not: total_guests = 12 yaş ÜSTÜ kişi sayısı; children_count = 12 yaş ve ALTI.
Aşama-1 alanlarından biri değişirse sunulan planlar geçersizleşir (stage1 fingerprint).
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

STAGE1_FIELDS = ["check_in", "check_out", "total_guests", "room_type"]   # DB sorgu girdileri


def _hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass
class ReservationState:
    # Aşama 1 — sorgu girdileri (zorunlu 4 alan)
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    total_guests: Optional[int] = None          # 12 yaş ÜSTÜ kişi sayısı
    room_type: Optional[str] = None             # tercih edilen oda türü (yükseltme olabilir)
    view_type: Optional[str] = None             # tercih edilen manzara (opsiyonel; önceliklendirme için)
    # Seçim — Gemini'nin (müsaitlik verisine göre) belirlediği KARMA plan:
    # [{"view_type","room_count"}, ...] — farklı manzaralar birlikte olabilir (ör. 1 deniz + 1 bahçe)
    selected_rooms: Optional[list] = None
    # Çocuklar (12 yaş ve altı)
    children_count: Optional[int] = None
    children_ages: Optional[list] = None
    # Kod garantileri
    options_offered_for: Optional[str] = None      # bed_options'ın çalıştığı aşama-1 parmak izi
    confirmation_pending_for: Optional[str] = None  # özeti gösterilip onayı beklenen TAM rezervasyonun parmak izi
    booking_id: Optional[str] = None               # dolunca active_flow serbest kalır


def stage1_missing(state: ReservationState) -> list:
    return [f for f in STAGE1_FIELDS if getattr(state, f) is None]


def selection_missing(state: ReservationState) -> list:
    return [] if state.selected_rooms else ["selected_rooms"]


def children_missing(state: ReservationState) -> list:
    if state.children_count is None:
        return ["children_count"]
    if state.children_count > 0:                 # çocuk yaşı KOŞULLU
        if not state.children_ages or len(state.children_ages) != state.children_count:
            return ["children_ages"]
    return []


def total_people(state: ReservationState) -> int:
    """Toplam kişi = yetişkin (>12 yaş, total_guests) + çocuk (<=12 yaş, children_count).
    Yatak/kapasite ihtiyacı DAİMA bu sayı üzerinden hesaplanır (yetişkin + çocuk = yatak)."""
    return (state.total_guests or 0) + (state.children_count or 0)


def missing_fields(state: ReservationState) -> list:
    """Aşama sırasına göre kalan tüm eksikler (debug/nudge için)."""
    return stage1_missing(state) + selection_missing(state) + children_missing(state)


def stage1_fingerprint(state: ReservationState) -> str:
    """Aşama-1 (4 alan) parmak izi — sunulan planların hangi girdiye ait olduğunu mühürler."""
    return _hash({f: getattr(state, f) for f in STAGE1_FIELDS})


def full_fingerprint(state: ReservationState) -> str:
    """Tüm rezervasyonun (4 alan + seçilen karma plan + çocuk) parmak izi — onayın hangi bilgilere
    ait olduğunu mühürler. Özet gösterildikten sonra bir alan değişirse onay geçersizleşir."""
    fields = STAGE1_FIELDS + ["selected_rooms", "children_count", "children_ages"]
    return _hash({f: getattr(state, f) for f in fields})
