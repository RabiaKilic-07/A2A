"""Gemini fonksiyon (tool) tanımları ve handler'ları.

Tool şemalarında 6 alan da OPTIONAL'dır — zorunluluk kodda (missing_fields) tutulur.
Kritik garantiler bu dosyada:
  * check_availability, eksik alanları KODLA tespit eder ('incomplete').
  * complete_reservation, müsaitliğin TAM O PARAMETRELER için doğrulandığını fingerprint ile kontrol eder.
Handler'lar SAĞLAYICIDAN BAĞIMSIZ'dır (yalnızca state + hotel_backend kullanır).
"""

from google.genai import types

from .hotel_backend import hotel_backend
from .reservation_state import ReservationState, fingerprint, missing_fields

# --- Alan şemaları: 6 alan da OPTIONAL (zorunluluk kodda) ---
_field_schemas = {
    "check_in":       types.Schema(type=types.Type.STRING,  description="Giriş tarihi (YYYY-MM-DD)"),
    "check_out":      types.Schema(type=types.Type.STRING,  description="Çıkış tarihi (YYYY-MM-DD)"),
    "room_type":      types.Schema(type=types.Type.STRING,  description="Oda türü: standart/deluxe/suit"),
    "view_type":      types.Schema(type=types.Type.STRING,  description="Manzara tipi: deniz/kara/bahçe"),
    "children_count": types.Schema(type=types.Type.INTEGER, description="Çocuk sayısı"),
    "children_ages":  types.Schema(type=types.Type.ARRAY,   items=types.Schema(type=types.Type.INTEGER),
                                   description="Her çocuğun yaşı (çocuk sayısı kadar)"),
}

check_availability_decl = types.FunctionDeclaration(
    name="check_availability",
    description=("Oda müsaitliğini sorgular. Elindeki alanları ver — hepsini bilmesen de çağırabilirsin. "
                 "Eksikse 'incomplete' + missing_fields döner; hepsi tamamsa 'available'/'unavailable' döner. "
                 "complete_reservation'dan ÖNCE mutlaka 'available' almalısın."),
    parameters=types.Schema(type=types.Type.OBJECT, properties=_field_schemas),
)

complete_reservation_decl = types.FunctionDeclaration(
    name="complete_reservation",
    description=("Rezervasyonu kesinleştirir. YALNIZCA check_availability 'available' döndükten sonra "
                 "aynı parametrelerle çağır. Parametreler değiştiyse önce yeniden check_availability yap."),
    parameters=types.Schema(type=types.Type.OBJECT, properties=_field_schemas),
)

RESERVATION_TOOL = types.Tool(function_declarations=[check_availability_decl, complete_reservation_decl])


def check_availability(state: ReservationState, **kwargs) -> dict:
    for k, v in kwargs.items():                    # v is not None → eskiyi EZME
        if hasattr(state, k) and v is not None:
            setattr(state, k, v)

    missing = missing_fields(state)
    if missing:
        state.availability_confirmed_for = None
        return {"status": "incomplete", "missing_fields": missing}

    if not hotel_backend.is_available(state):
        state.availability_confirmed_for = None
        return {"status": "unavailable"}

    state.availability_confirmed_for = fingerprint(state)   # onayı O parametrelere mühürle
    return {"status": "available", "price": hotel_backend.price(state)}


def complete_reservation(state: ReservationState, **kwargs) -> dict:
    for k, v in kwargs.items():
        if hasattr(state, k) and v is not None:
            setattr(state, k, v)

    missing = missing_fields(state)
    if missing:
        return {"is_error": True, "error": "eksik_bilgi", "missing_fields": missing}

    # ASIL GARANTİ: güncel parametreler, müsait bulunan parametrelerle birebir mi?
    if state.availability_confirmed_for != fingerprint(state):
        return {"is_error": True, "error": "musaitlik_dogrulanmadi",
                "message": "Önce güncel parametrelerle check_availability çalıştırılmalı."}

    booking = hotel_backend.book(state)
    state.booking_id = booking.id
    state.availability_confirmed_for = None
    return {"status": "confirmed", "booking_id": booking.id}


def dispatch(state: ReservationState, name: str, tool_input: dict) -> dict:
    if name == "check_availability":
        return check_availability(state, **tool_input)
    if name == "complete_reservation":
        return complete_reservation(state, **tool_input)
    return {"is_error": True, "error": f"bilinmeyen tool: {name}"}
