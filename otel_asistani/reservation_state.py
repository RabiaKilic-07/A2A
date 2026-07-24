"""Rezervasyon durumu (state) ve AŞAMALI doğrulama — SAĞLAYICIDAN BAĞIMSIZ.

Rezervasyon 3 aşamada toplanır:
  1) Aşama-1 (zorunlu 4 alan): check_in, check_out, total_guests, room_type
     → bed_options tool'u veritabanını bu 4 filtreye göre sorgular.
  2) Seçim: kullanıcı sunulan (view_type, bed_layout) seçeneklerinden birini seçer.
  3) Aşama-3: children_count (+ çocuk varsa children_ages).

Aşama-1 alanlarından biri değişirse sunulan seçenekler geçersizleşir (stage1 fingerprint) →
bed_options yeniden çalıştırılmalı.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

STAGE1_FIELDS = ["check_in", "check_out", "total_guests", "room_type"]   # DB filtreleri
SELECTION_FIELDS = ["view_type", "bed_layout"]                           # bed_options'tan seçilir


def _hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass
class ReservationState:
    # Aşama 1 — veritabanı filtreleri (zorunlu 4 alan)
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    total_guests: Optional[int] = None
    room_type: Optional[str] = None
    # Aşama 2 — bed_options'ın sunduğu seçeneklerden seçilen
    view_type: Optional[str] = None
    bed_layout: Optional[str] = None
    # Aşama 3
    children_count: Optional[int] = None
    children_ages: Optional[list] = None
    # Kod garantileri
    options_offered_for: Optional[str] = None      # bed_options'ın çalıştığı aşama-1 parmak izi
    confirmation_pending_for: Optional[str] = None  # özeti gösterilip onayı beklenen TAM rezervasyonun parmak izi
    booking_id: Optional[str] = None               # dolunca active_flow serbest kalır


def stage1_missing(state: ReservationState) -> list:
    return [f for f in STAGE1_FIELDS if getattr(state, f) is None]


def selection_missing(state: ReservationState) -> list:
    return [f for f in SELECTION_FIELDS if getattr(state, f) is None]


def children_missing(state: ReservationState) -> list:
    if state.children_count is None:
        return ["children_count"]
    if state.children_count > 0:                 # çocuk yaşı KOŞULLU
        if not state.children_ages or len(state.children_ages) != state.children_count:
            return ["children_ages"]
    return []


def missing_fields(state: ReservationState) -> list:
    """Aşama sırasına göre kalan tüm eksikler (debug/nudge için)."""
    return stage1_missing(state) + selection_missing(state) + children_missing(state)


def stage1_fingerprint(state: ReservationState) -> str:
    """Aşama-1 (4 filtre) parmak izi — sunulan seçeneklerin hangi girdiye ait olduğunu mühürler."""
    return _hash({f: getattr(state, f) for f in STAGE1_FIELDS})


def full_fingerprint(state: ReservationState) -> str:
    """Tüm rezervasyonun (4 filtre + seçim + çocuk) parmak izi — onayın hangi bilgilere ait
    olduğunu mühürler. Özet gösterildikten sonra bir alan değişirse onay geçersizleşir."""
    fields = STAGE1_FIELDS + SELECTION_FIELDS + ["children_count", "children_ages"]
    return _hash({f: getattr(state, f) for f in fields})
