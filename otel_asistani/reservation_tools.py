"""Gemini fonksiyon (tool) tanımları ve handler'ları — AŞAMALI rezervasyon (3 tool).

  1) check_availability : AŞAMA 1. Zorunlu 4 alanı (check_in, check_out, total_guests,
     room_type) toplar/doğrular. Eksikse 'incomplete'; 4'ü tamsa 'stage1_ok' → bed_options çağır.
  2) bed_options        : AŞAMA 2. 4 filtreyle DB'yi sorgular; (manzara + yatak dizilişi)
     seçeneklerini kullanıcıya sunmak için döndürür ve aşama-1 parmak izini mühürler.
  3) complete_reservation : AŞAMA 3. Seçilen (view_type, bed_layout)'ı çağrılınca state'e yazar;
     çocuk bilgileriyle birlikte ÖZETLE + ONAYLAT + bitirir.

Not: Kullanıcı seçim yapınca seçim, complete_reservation'a view_type/bed_layout verilerek kaydedilir
(handler'daki _apply state'e yazar) — seçim için ayrı bir tool yoktur; akış prompt ile yönetilir.

Kod garantileri:
  * check_availability, eksik aşama-1 alanlarını KODLA tespit eder (model değil).
  * complete_reservation, aşama-1 alanlarının bed_options'tan beri DEĞİŞMEDİĞİNİ (fingerprint) ve
    seçilen kombinasyonun DB'de gerçekten VAR olduğunu doğrular.
Handler'lar SAĞLAYICIDAN BAĞIMSIZ'dır (yalnızca state + hotel_backend kullanır).
"""

from datetime import date

from google.genai import types

from .hotel_backend import hotel_backend
from .reservation_state import (
    ReservationState,
    children_missing,
    full_fingerprint,
    selection_missing,
    stage1_fingerprint,
    stage1_missing,
)

# --- Alan şemaları: hepsi OPTIONAL (zorunluluk/sıra kodda tutulur) ---
_schemas = {
    "check_in":       types.Schema(type=types.Type.STRING,  description="Giriş tarihi (YYYY-MM-DD)"),
    "check_out":      types.Schema(type=types.Type.STRING,  description="Çıkış tarihi (YYYY-MM-DD)"),
    "total_guests":   types.Schema(type=types.Type.INTEGER, description="Toplam kişi sayısı (yetişkin + çocuk)"),
    "room_type":      types.Schema(type=types.Type.STRING,  description="Oda türü: standart/deluxe/suit"),
    "view_type":      types.Schema(type=types.Type.STRING,  description="Manzara tipi — bed_options'ın SUNDUĞU seçeneklerden biri"),
    "bed_layout":     types.Schema(type=types.Type.STRING,  description="Yatak dizilişi — bed_options'ın SUNDUĞU seçeneklerden biri"),
    "children_count": types.Schema(type=types.Type.INTEGER, description="Çocuk sayısı (yoksa 0)"),
    "children_ages":  types.Schema(type=types.Type.ARRAY,   items=types.Schema(type=types.Type.INTEGER),
                                   description="Her çocuğun yaşı (çocuk sayısı kadar)"),
    "confirmed":      types.Schema(type=types.Type.BOOLEAN,
                                   description="Kullanıcı özeti görüp AÇIKÇA onayladıysa true. Onay yoksa gönderme."),
}

_STAGE1 = ("check_in", "check_out", "total_guests", "room_type")
_DATA = ("check_in", "check_out", "total_guests", "room_type",
         "view_type", "bed_layout", "children_count", "children_ages")


def _params(*names) -> types.Schema:
    return types.Schema(type=types.Type.OBJECT, properties={n: _schemas[n] for n in names})


check_availability_decl = types.FunctionDeclaration(
    name="check_availability",
    description=("AŞAMA 1. Rezervasyonun zorunlu 4 alanını toplar/doğrular: giriş tarihi, çıkış "
                "tarihi, toplam kişi sayısı, oda türü. Elindeki alanları ver — hepsini bilmesen de "
                "çağır. Eksik varsa 'incomplete' + missing_fields döner (yalnızca bu 4 alan). 4'ü de "
                "tamsa 'stage1_ok' döner; ARDINDAN bed_options'ı çağır. Kullanıcı fazladan bilgi "
                "(manzara, çocuk vb.) verirse yine de gönder; saklanır ama aşama-1 için zorunlu değildir."),
    parameters=_params(*_DATA),   # fazladan verilen bilgiler kaybolmasın diye tüm alanlar opsiyonel
)

bed_options_decl = types.FunctionDeclaration(
    name="bed_options",
    description=("AŞAMA 2. Aşama-1'in 4 filtresine göre veritabanını sorgular ve uygun odaların "
                "MANZARA TİPİ + YATAK DİZİLİŞİ seçeneklerini (fiyatlarıyla) döndürür. Bu seçenekleri "
                "kullanıcıya sun ve birini seçmesini iste. YALNIZCA check_availability 'stage1_ok' "
                "döndükten sonra çağır. Aşama-1 alanları eksikse 'incomplete' döner."),
    parameters=_params(*_STAGE1),
)

complete_reservation_decl = types.FunctionDeclaration(
    name="complete_reservation",
    description=("AŞAMA 3. Rezervasyonu KAYDET / ÖZETLE / ONAYLAT. Kullanıcı bir seçenek seçince, "
                "seçtiği view_type ve bed_layout'ı BU ARACA vererek seçimi kaydet — çocuk bilgisi "
                "henüz yoksa da çağır: araç 'cocuk_bilgisi_eksik' dönerse (seçim yine de kaydedilmiştir) "
                "çocuk sayısını sor. Tüm bilgiler tamsa confirmed OLMADAN çağır: 'needs_confirmation' + "
                "summary döner → özeti sun ve onay iste. Kullanıcı AÇIKÇA onaylayınca confirmed=true ile "
                "TEKRAR çağır → 'confirmed' + booking_id. Aşama-1 alanları bed_options'tan beri "
                "değiştiyse 'secenekler_gecersiz' döner."),
    parameters=_params(*_DATA, "confirmed"),
)

RESERVATION_TOOL = types.Tool(
    function_declarations=[check_availability_decl, bed_options_decl, complete_reservation_decl]
)


def _apply(state: ReservationState, kwargs: dict) -> None:
    for k, v in kwargs.items():                    # v is not None → eskiyi EZME
        if hasattr(state, k) and v is not None:
            setattr(state, k, v)


def check_availability(state: ReservationState, **kwargs) -> dict:
    _apply(state, kwargs)
    state.options_offered_for = None               # aşama-1 yeniden ele alınıyor → eski seçenekleri geçersiz kıl

    missing = stage1_missing(state)
    if missing:
        return {"status": "incomplete", "missing_fields": missing}

    if not hotel_backend.search_options(
        check_in=state.check_in, check_out=state.check_out,
        total_guests=state.total_guests, room_type=state.room_type,
    ):
        return {"status": "no_match",
                "message": "Bu tarih/kişi sayısı/oda türü için uygun oda yok. Bilgileri güncelleyin."}

    return {"status": "stage1_ok", "next": "bed_options"}


def bed_options(state: ReservationState, **kwargs) -> dict:
    _apply(state, kwargs)

    missing = stage1_missing(state)
    if missing:
        state.options_offered_for = None
        return {"status": "incomplete", "missing_fields": missing}

    options = hotel_backend.search_options(
        check_in=state.check_in, check_out=state.check_out,
        total_guests=state.total_guests, room_type=state.room_type,
    )
    if not options:
        state.options_offered_for = None
        return {"status": "no_match",
                "message": "Bu 4 filtre için uygun oda bulunamadı. Bilgileri güncelleyin."}

    state.options_offered_for = stage1_fingerprint(state)   # seçenekleri O filtrelere mühürle
    return {"status": "options", "options": options}


def _nights(check_in, check_out):
    try:
        return (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    except (TypeError, ValueError):
        return None


def _build_summary(state: ReservationState, room: dict) -> dict:
    """Kullanıcıya sunulacak rezervasyon özeti (kod tarafında derlenir, uydurulmaz)."""
    price = room["price_per_night"]
    summary = {
        "check_in": state.check_in,
        "check_out": state.check_out,
        "total_guests": state.total_guests,
        "room_type": state.room_type,
        "view_type": state.view_type,
        "bed_layout": state.bed_layout,
        "children_count": state.children_count,
        "children_ages": state.children_ages or [],
        "price_per_night": price,
    }
    nights = _nights(state.check_in, state.check_out)
    if nights and nights > 0:
        summary["nights"] = nights
        summary["total_price"] = price * nights
    return summary


def complete_reservation(state: ReservationState, **kwargs) -> dict:
    confirmed = bool(kwargs.pop("confirmed", False))   # confirmed state alanı değil → ayrı ele al
    _apply(state, kwargs)

    if stage1_missing(state):
        return {"is_error": True, "error": "asama1_eksik", "missing_fields": stage1_missing(state)}

    # GARANTİ 1: aşama-1 alanları bed_options'tan beri değişmedi mi?
    if state.options_offered_for is None or state.options_offered_for != stage1_fingerprint(state):
        state.options_offered_for = None
        state.confirmation_pending_for = None
        return {"is_error": True, "error": "secenekler_gecersiz",
                "message": "Aşama-1 bilgileri değişti. Önce check_availability + bed_options yeniden çalıştırılmalı."}

    if selection_missing(state):
        return {"is_error": True, "error": "secim_yapilmadi", "missing_fields": selection_missing(state),
                "message": "Kullanıcı sunulan manzara + yatak dizilişi seçeneklerinden birini seçmeli."}

    if children_missing(state):
        return {"is_error": True, "error": "cocuk_bilgisi_eksik", "missing_fields": children_missing(state)}

    # GARANTİ 2: seçilen (manzara + yatak dizilişi) bu filtreler için DB'de gerçekten var mı?
    room = hotel_backend.find_room(
        check_in=state.check_in, check_out=state.check_out,
        total_guests=state.total_guests, room_type=state.room_type,
        view_type=state.view_type, bed_layout=state.bed_layout,
    )
    if room is None:
        state.confirmation_pending_for = None
        return {"is_error": True, "error": "gecersiz_secim",
                "message": "Seçilen manzara/yatak dizilişi bu filtreler için mevcut değil. bed_options'ı tekrar çalıştırın."}

    summary = _build_summary(state, room)

    # GARANTİ 3 (ONAY KAPISI): önce özet gösterilip kullanıcı AÇIKÇA onaylamadan rezervasyon YAPILMAZ.
    # confirmed=true olsa bile, özetin gösterildiği TAM bilgilere ait bir onay damgası şart —
    # böylece model özeti sunmadan kendi kendine onaylayıp geçemez, bilgi değişince onay eskir.
    if not confirmed or state.confirmation_pending_for != full_fingerprint(state):
        state.confirmation_pending_for = full_fingerprint(state)
        return {"status": "needs_confirmation", "summary": summary,
                "message": ("Bu özeti kullanıcıya aynen sun ve 'Onaylıyor musunuz?' diye sor. "
                            "Kullanıcı açıkça onaylarsa complete_reservation'ı confirmed=true ile TEKRAR çağır. "
                            "Bir bilgiyi değiştirmek isterse ilgili aşamaya dön.")}

    booking = hotel_backend.book(room)
    state.booking_id = booking.id
    state.options_offered_for = None
    state.confirmation_pending_for = None
    return {"status": "confirmed", "booking_id": booking.id, "room_id": booking.room_id, "summary": summary}


def dispatch(state: ReservationState, name: str, tool_input: dict) -> dict:
    if name == "check_availability":
        return check_availability(state, **tool_input)
    if name == "bed_options":
        return bed_options(state, **tool_input)
    if name == "complete_reservation":
        return complete_reservation(state, **tool_input)
    return {"is_error": True, "error": f"bilinmeyen tool: {name}"}
