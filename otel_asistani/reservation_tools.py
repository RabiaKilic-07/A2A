"""Gemini fonksiyon (tool) tanımları ve handler'ları — rezervasyon (3 tool).

  1) check_availability : Aşama-1 girdilerini (check_in, check_out, total_guests, room_type) TEK
     seferde toplar/doğrular. Eksikse 'incomplete'; tamsa 'stage1_ok' → bed_options çağır.
  2) bed_options        : DB endpoint'inden (available_rooms) gruplanmış müsaitliği Gemini'ye verir.
     Planlamayı (birebir uyum / öneri / oda bölme) GEMINI yapar; kod plan üretmez.
  3) complete_reservation : Gemini'nin seçtiği KARMA planı (rooms listesi) DB'ye göre DOĞRULAR,
     fiyatlar, ÖZETLER + ONAYLAR + bitirir.

Kod garantileri:
  * check_availability, eksik aşama-1 alanlarını KODLA tespit eder (model değil).
  * complete_reservation, aşama-1 alanlarının bed_options'tan beri DEĞİŞMEDİĞİNİ (fingerprint) VE
    seçilen (manzara + oda sayısı) planın DB'de MÜSAİT ve kapasitesinin YETERLİ olduğunu doğrular; onay kapısı.
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
    "total_guests":   types.Schema(type=types.Type.INTEGER, description="12 yaşından BÜYÜK kişi sayısı (12 yaş ve altı buraya DAHİL DEĞİL, çocuk sayılır)"),
    "room_type":      types.Schema(type=types.Type.STRING,  description="İstenen oda türü: standart/deluxe/suit (DEĞİŞMEZ; farklı tür önerilmez)"),
    "view_type":      types.Schema(type=types.Type.STRING,  description="Tercih edilen manzara (opsiyonel): deniz/kara/bahçe. Önceliklendirme için."),
    "rooms":          types.Schema(type=types.Type.ARRAY,
                                   description=("Seçilen KARMA plan: oda listesi. Her eleman {view_type, room_count}. "
                                                "Farklı manzaralar BİRLİKTE olabilir (ör. 1 deniz + 1 bahçe)."),
                                   items=types.Schema(type=types.Type.OBJECT, properties={
                                       "view_type": types.Schema(type=types.Type.STRING, description="Bu odaların manzarası"),
                                       "room_count": types.Schema(type=types.Type.INTEGER, description="Bu manzaradan kaç oda"),
                                   })),
    "children_count": types.Schema(type=types.Type.INTEGER, description="12 yaş ve ALTI çocuk sayısı (yoksa 0)"),
    "children_ages":  types.Schema(type=types.Type.ARRAY,   items=types.Schema(type=types.Type.INTEGER),
                                   description="12 yaş ve altı her çocuğun yaşı (children_count kadar)"),
    "confirmed":      types.Schema(type=types.Type.BOOLEAN,
                                   description="Kullanıcı özeti görüp AÇIKÇA onayladıysa true. Onay yoksa gönderme."),
}

_STAGE1 = ("check_in", "check_out", "total_guests", "room_type")   # stage1_ok için zorunlu
_INPUT = ("check_in", "check_out", "total_guests", "room_type",    # tüm ön bilgiler (tek seferde)
          "view_type", "children_count", "children_ages")


def _params(*names) -> types.Schema:
    return types.Schema(type=types.Type.OBJECT, properties={n: _schemas[n] for n in names})


check_availability_decl = types.FunctionDeclaration(
    name="check_availability",
    description=("AŞAMA 1. Gerekli bilgileri TEK seferde toplar/doğrular: giriş tarihi, çıkış tarihi, "
                "kişi sayısı (total_guests = 12 yaş ÜSTÜ), oda türü. Varsa manzara tercihini (view_type) "
                "ve çocuk bilgisini (children_count/children_ages, 12 yaş ve altı) de aynı çağrıda gönder. "
                "Eksik varsa 'incomplete' + missing_fields döner (4 zorunlu alan). Tamsa 'stage1_ok' → "
                "ARDINDAN bed_options'ı çağır."),
    parameters=_params(*_INPUT),
)

bed_options_decl = types.FunctionDeclaration(
    name="bed_options",
    description=("AŞAMA 2. İstenen oda türü + tarih için MÜSAİTLİK verisini döndürür: her (manzara, "
                "kapasite) grubu için kaç adet oda olduğu ve gecelik fiyat. Planlamayı SEN yaparsın: "
                "kullanıcının istediği manzarada, tek odaya sığan bir grup varsa (max_guests >= kişi "
                "sayısı) BİREBİR odur → yalnızca onu öner. Yoksa bu veriye göre öneride bulun: aynı türde "
                "farklı manzara ya da odayı BÖLME (yeterli sayıda oda varsa). YALNIZCA check_availability "
                "'stage1_ok' döndükten sonra çağır."),
    parameters=_params("check_in", "check_out", "total_guests", "room_type", "view_type"),
)

complete_reservation_decl = types.FunctionDeclaration(
    name="complete_reservation",
    description=("AŞAMA 3. Kullanıcı bir öneri seçince, seçilen odaları 'rooms' listesiyle ver "
                "([{view_type, room_count}, ...]; farklı manzaralar birlikte olabilir) ve confirmed "
                "OLMADAN çağır: araç seçimi DB'ye göre doğrular, fiyatlar ve 'needs_confirmation' + summary "
                "döner → özeti sun ve onay iste. Kullanıcı AÇIKÇA onaylayınca confirmed=true ile TEKRAR çağır "
                "→ 'confirmed' + booking_id. Aşama-1 değiştiyse 'secenekler_gecersiz'; seçim müsait/kapasite "
                "yetersizse 'gecersiz_secim'."),
    parameters=_params(*_INPUT, "rooms", "confirmed"),
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
    state.options_offered_for = None               # aşama-1 yeniden ele alınıyor → eski planları geçersiz kıl

    missing = stage1_missing(state)
    if missing:
        return {"status": "incomplete", "missing_fields": missing}

    # İstenen ODA TÜRÜNDEN, bu tarih için müsait oda var mı?
    if not hotel_backend.available_rooms(
        check_in=state.check_in, check_out=state.check_out, room_type=state.room_type,
    )["groups"]:
        return {"status": "no_match",
                "message": "Bu tarih için istenen oda türünden müsait oda yok. Bilgileri güncelleyin."}

    return {"status": "stage1_ok", "next": "bed_options"}


def bed_options(state: ReservationState, **kwargs) -> dict:
    _apply(state, kwargs)

    missing = stage1_missing(state)
    if missing:
        state.options_offered_for = None
        return {"status": "incomplete", "missing_fields": missing}

    # DB endpoint'inden gruplanmış müsaitlik (kişi sayısı KULLANILMAZ) → planlamayı Gemini yapar.
    availability = hotel_backend.available_rooms(
        check_in=state.check_in, check_out=state.check_out, room_type=state.room_type,
    )
    if not availability["groups"]:
        state.options_offered_for = None
        return {"status": "no_match",
                "message": "Bu tarih için istenen oda türünden müsait oda yok. Bilgileri güncelleyin."}

    state.options_offered_for = stage1_fingerprint(state)   # müsaitliği O aşama-1 girdisine mühürle
    return {
        "status": "options",
        "total_guests": state.total_guests,
        "availability": availability,
        "message": ("Bu MÜSAİTLİK verisine göre planla. İstenen manzarada tek odaya sığan bir grup varsa "
                    "(max_guests >= kişi sayısı, count >= 1) BİREBİR odur → yalnızca onu öner. Yoksa: aynı "
                    "türde farklı manzara ya da odayı BÖL (bir grubu birden çok oda seçerek; oda sayısı o "
                    "grubun count'unu aşamaz). İstenen manzarada yeterli oda yoksa o manzaradan alıp KALANI "
                    "başka manzaradan tamamla (karma). Kullanıcı seçince complete_reservation'ı rooms listesiyle çağır."),
    }


def _nights(check_in, check_out):
    try:
        return (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    except (TypeError, ValueError):
        return None


def _build_summary(state: ReservationState, plan: dict) -> dict:
    """Kullanıcıya sunulacak rezervasyon özeti (kod tarafında, doğrulanan KARMA plandan derlenir)."""
    price = plan["price_per_night"]                        # tüm odalar için gecelik toplam
    summary = {
        "check_in": state.check_in,
        "check_out": state.check_out,
        "total_guests": state.total_guests,
        "children_count": state.children_count,
        "children_ages": state.children_ages or [],
        "room_type": state.room_type,
        "rooms": [{"view_type": r["view_type"], "room_count": r["room_count"],
                   "per_room_capacity": r["max_guests"]} for r in plan["rooms"]],
        "total_capacity": plan["capacity"],
        "price_per_night": price,
    }
    nights = _nights(state.check_in, state.check_out)
    if nights and nights > 0:
        summary["nights"] = nights
        summary["total_price"] = price * nights
    return summary


def complete_reservation(state: ReservationState, **kwargs) -> dict:
    confirmed = bool(kwargs.pop("confirmed", False))       # confirmed state alanı değil → ayrı ele al
    rooms = kwargs.pop("rooms", None)                      # seçim = karma oda listesi
    _apply(state, kwargs)
    if rooms is not None:                                  # seçimi kaydet (araya konu girse kaybolmasın)
        state.selected_rooms = sorted(
            [{"view_type": r.get("view_type"), "room_count": r.get("room_count")} for r in rooms],
            key=lambda r: str(r.get("view_type") or "").lower(),
        )

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
                "message": "Kullanıcı bir öneri seçmeli: rooms = [{view_type, room_count}, ...]."}

    if children_missing(state):
        return {"is_error": True, "error": "cocuk_bilgisi_eksik", "missing_fields": children_missing(state)}

    # GARANTİ 2: seçilen KARMA plan DB'de müsait ve toplam kapasitesi yeterli mi?
    plan = hotel_backend.price_plan(
        state.selected_rooms,
        check_in=state.check_in, check_out=state.check_out,
        room_type=state.room_type, total_guests=state.total_guests,
    )
    if plan is None:
        state.confirmation_pending_for = None
        return {"is_error": True, "error": "gecersiz_secim",
                "message": ("Seçilen oda(lar) için yeterli müsait oda yok ya da toplam kapasite yetmiyor. "
                            "bed_options müsaitliğine göre yeniden öner/seç.")}

    summary = _build_summary(state, plan)

    # GARANTİ 3 (ONAY KAPISI): önce özet gösterilip kullanıcı AÇIKÇA onaylamadan rezervasyon YAPILMAZ.
    if not confirmed or state.confirmation_pending_for != full_fingerprint(state):
        state.confirmation_pending_for = full_fingerprint(state)
        return {"status": "needs_confirmation", "summary": summary,
                "message": ("Bu özeti kullanıcıya aynen sun ve 'Onaylıyor musunuz?' diye sor. "
                            "Kullanıcı açıkça onaylarsa complete_reservation'ı confirmed=true ile TEKRAR çağır. "
                            "Bir bilgiyi değiştirmek isterse ilgili aşamaya dön.")}

    booking = hotel_backend.book()
    state.booking_id = booking.id
    state.options_offered_for = None
    state.confirmation_pending_for = None
    return {"status": "confirmed", "booking_id": booking.id, "summary": summary}


def dispatch(state: ReservationState, name: str, tool_input: dict) -> dict:
    if name == "check_availability":
        return check_availability(state, **tool_input)
    if name == "bed_options":
        return bed_options(state, **tool_input)
    if name == "complete_reservation":
        return complete_reservation(state, **tool_input)
    return {"is_error": True, "error": f"bilinmeyen tool: {name}"}
