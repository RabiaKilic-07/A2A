"""
Otel multi-agent demo — GOOGLE GEMINI sürümü, tek dosyalık uçtan uca iskelet.

Yapı:
  Orchestrator (router)  ──►  reservation subagent  (tools: check_availability, complete_reservation)
                         ──►  hotel_info (RAG stub, hafızalı)
                         ──►  complaint subagent
                         ──►  chat (genel sohbet / yedek akış)

Öne çıkan garantiler:
  * check_availability 6 alanı KADEMELİ toplar; eksikleri kod (_missing_fields) bilir, model değil.
  * complete_reservation, müsaitliğin TAM O PARAMETRELER için doğrulandığını fingerprint ile KODLA garanti eder.
  * Router "sticky": rezervasyon sürerken kısa cevaplar rezervasyona döner; kullanıcı konu değiştirirse hapsolmaz.

Kurulum:
  pip install google-genai pydantic
  PowerShell:  $env:GEMINI_API_KEY="..."
  python otel_asistani.py

Gemini anahtarını https://aistudio.google.com/app/apikey adresinden alabilirsin.
hotel_backend, run_rag ve run_complaint_subagent birer STUB'dır — gerçek envanter/RAG ile değiştir.
"""

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=API_KEY)

MODEL = "gemini-2.5-flash"   # istersen "gemini-2.5-pro" ya da "gemini-2.0-flash"


# ---------------------------------------------------------------------------
# 1) Rezervasyon durumu (state) + doğrulama yardımcıları  [SAĞLAYICIDAN BAĞIMSIZ]
# ---------------------------------------------------------------------------

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


def _missing_fields(s: ReservationState) -> list:
    missing = [f for f in REQUIRED if getattr(s, f) is None]
    if s.children_count and s.children_count > 0:      # çocuk yaşı KOŞULLU
        if not s.children_ages or len(s.children_ages) != s.children_count:
            missing.append("children_ages")
    return missing


def _fingerprint(s: ReservationState) -> str:
    payload = {f: getattr(s, f) for f in REQUIRED + ["children_ages"]}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# 2) Otel arka ucu (STUB) — gerçek envanter/DB ile değiştir
# ---------------------------------------------------------------------------

class HotelBackend:
    def is_available(self, s: ReservationState) -> bool:
        return True  # demo: her zaman müsait

    def price(self, s: ReservationState) -> str:
        return "5000 TL/gece"

    def book(self, s: ReservationState):
        return SimpleNamespace(id="RSV-" + uuid.uuid4().hex[:8].upper())


hotel_backend = HotelBackend()


# ---------------------------------------------------------------------------
# 3) Gemini fonksiyon (tool) tanımları — 6 alan da OPTIONAL (zorunluluk kodda)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 4) Tool handler'ları — kritik garantiler burada  [SAĞLAYICIDAN BAĞIMSIZ]
# ---------------------------------------------------------------------------

def check_availability(state: ReservationState, **kwargs) -> dict:
    for k, v in kwargs.items():                    # v is not None → eskiyi EZME
        if hasattr(state, k) and v is not None:
            setattr(state, k, v)

    missing = _missing_fields(state)
    if missing:
        state.availability_confirmed_for = None
        return {"status": "incomplete", "missing_fields": missing}

    if not hotel_backend.is_available(state):
        state.availability_confirmed_for = None
        return {"status": "unavailable"}

    state.availability_confirmed_for = _fingerprint(state)   # onayı O parametrelere mühürle
    return {"status": "available", "price": hotel_backend.price(state)}


def complete_reservation(state: ReservationState, **kwargs) -> dict:
    for k, v in kwargs.items():
        if hasattr(state, k) and v is not None:
            setattr(state, k, v)

    missing = _missing_fields(state)
    if missing:
        return {"is_error": True, "error": "eksik_bilgi", "missing_fields": missing}

    # ASIL GARANTİ: güncel parametreler, müsait bulunan parametrelerle birebir mi?
    if state.availability_confirmed_for != _fingerprint(state):
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


# ---------------------------------------------------------------------------
# 5) Gemini içerik/metin yardımcıları
# ---------------------------------------------------------------------------

def _user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def _content_text(content) -> str:
    parts = getattr(content, "parts", None) or []
    out = [p.text for p in parts if getattr(p, "text", None)]
    return " ".join(out).strip()


def _last_model_question(session: "Session") -> Optional[str]:
    for c in reversed(session.reservation_msgs):
        if getattr(c, "role", None) == "model":
            t = _content_text(c)
            if t:
                return t
    return None


# ---------------------------------------------------------------------------
# 6) Router (orchestrator) — sticky sınıflandırıcı, structured output
# ---------------------------------------------------------------------------

class RouteDecision(BaseModel):
    target: Literal["reservation", "hotel_info", "complaint", "chat"]
    reason: str


ROUTER_SYSTEM = """Sen bir otel asistanının yönlendiricisisin (router).
Tek görevin: kullanıcının SON mesajını DÖRT akıştan birine yönlendirmek.

- reservation : oda ayırtma, müsaitlik sorgulama, tarih/oda/kişi/manzara/çocuk bilgisi
                verme, VE daha önce verdiği rezervasyon bilgisini değiştirme.
- hotel_info  : otelin özellikleri hakkında bilgi sorusu (wifi, kahvaltı, spa, konum, saatler).
- complaint   : şikayet, talep, sorun bildirme.
- chat        : selamlaşma, teşekkür, muhabbet, yukarıdaki üçüne girmeyen genel/serbest mesajlar.
                Bu VARSAYILAN/YEDEK akıştır — emin değilsen chat seç.

YAPIŞKAN (sticky) KURAL:
Şu anki aktif akış: {active_flow}
Rezervasyon asistanının sorduğu son soru: {son_soru}

- Aktif akış "reservation" ise, kullanıcı AÇIKÇA konu değiştirmediği sürece "reservation"da KAL.
  "deniz manzarası", "2 çocuk", "20 Temmuz", "deluxe" gibi kısa/eksik cevaplar rezervasyonun
  devamıdır — bunları chat veya hotel_info sanma.
- Kullanıcı normal sohbet ederken bir rezervasyon bilgisi/isteği verirse (tarih, oda türü,
  "oda ayırtmak istiyorum") reservation seç — sohbet içinde gelmiş olması fark etmez.
- Otel özelliği sorarsa hotel_info, şikayet/talep varsa complaint, geri kalan her şey chat."""


def route(session: "Session", user_text: str) -> str:
    system = ROUTER_SYSTEM.format(
        active_flow=session.active_flow or "yok",
        son_soru=_last_model_question(session) or "yok",
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=RouteDecision,      # structured output → target garantili enum
        ),
    )
    decision = response.parsed
    if decision is None:
        return "chat"                           # ayrıştırılamazsa güvenli varsayılan
    return decision.target


# ---------------------------------------------------------------------------
# 7) Rezervasyon subagent'ı — KENDİ mesaj thread'i + KENDİ tool'ları
# ---------------------------------------------------------------------------

RESERVATION_SYSTEM = """Sen bir otelin rezervasyon asistanısın. Amacın müsaitlik sorgulayıp
rezervasyonu tamamlamak.

Şu 6 bilgiyi topla: giriş tarihi, çıkış tarihi, oda türü, manzara tipi, çocuk sayısı,
(çocuk varsa) çocuk yaşları.

Kurallar:
- Kullanıcının verdiği bilgilerle check_availability'yi çağır — hepsini bilmesen de çağırabilirsin.
- Araç 'incomplete' + missing_fields dönerse YALNIZCA eksik alanları nazikçe sor (bir-iki tanesini birlikte).
- Rezervasyonu ancak check_availability 'available' döndükten sonra complete_reservation ile kesinleştir.
- Kullanıcı önceki bir bilgiyi değiştirmek isterse güncelle ve yeniden check_availability çalıştır.
- NİHAİ HEDEF rezervasyonu tamamlatmaktır. Kullanıcı konuyu dağıtsa ya da başka şeyler sorsa
  bile, kısaca yardımcı olduktan sonra kaldığın yerden eksik bilgileri toplamaya devam et ve
  rezervasyonu bitirmeye yönlendir.
- Türkçe, kısa ve net konuş."""

RESERVATION_CONFIG = types.GenerateContentConfig(
    system_instruction=RESERVATION_SYSTEM,
    tools=[RESERVATION_TOOL],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # manuel kontrol
)


def run_reservation_subagent(session: "Session", max_iters: int = 8) -> str:
    for _ in range(max_iters):
        response = client.models.generate_content(
            model=MODEL,
            contents=session.reservation_msgs,
            config=RESERVATION_CONFIG,
        )
        candidate = response.candidates[0]
        session.reservation_msgs.append(candidate.content)     # model turu

        fcs = response.function_calls or []
        if not fcs:
            return _content_text(candidate.content) or "(boş yanıt)"

        response_parts = []
        for fc in fcs:
            args = dict(fc.args or {})
            out = dispatch(session.reservation_state, fc.name, args)
            session.turn_tool_log.append((fc.name, args, out))     # ← tool logu
            response_parts.append(types.Part.from_function_response(name=fc.name, response=out))
        session.reservation_msgs.append(types.Content(role="user", parts=response_parts))

    return "Üzgünüm, işlemi tamamlayamadım. Lütfen tekrar dener misiniz?"


# ---------------------------------------------------------------------------
# 8) hotel_info (RAG STUB, hafızalı) — gerçek retrieval ile değiştir
# ---------------------------------------------------------------------------

HOTEL_KB = """
- Wifi: tüm otelde ücretsiz, şifre GUEST2026
- Kahvaltı: 07:00-10:30, açık büfe, konaklamaya dahil
- Check-in 14:00, check-out 12:00
- Spa & havuz: 09:00-21:00
- Otopark: ücretsiz
- Konum: sahile 200 metre
"""

HOTEL_INFO_SYSTEM = ("Otel bilgi asistanısın. SADECE aşağıdaki bilgilere dayanarak Türkçe yanıtla; "
                     "bilmiyorsan resepsiyona yönlendir.\n\nOTEL BİLGİLERİ:\n" + HOTEL_KB)


def _reservation_in_progress(session: "Session") -> bool:
    """Başlamış ama tamamlanmamış bir rezervasyon var mı? (active_flow'dan bağımsız)"""
    s = session.reservation_state
    started = bool(session.reservation_msgs) or any(getattr(s, f) is not None for f in REQUIRED)
    return started and s.booking_id is None


def _reservation_nudge(session: "Session") -> str:
    """Yarım rezervasyon varsa, sapma akışlarına 'sonunda rezervasyona geri getir' talimatı ekler."""
    if not _reservation_in_progress(session):
        return ""
    eksik = _missing_fields(session.reservation_state)
    durum = f"eksik bilgiler: {eksik}" if eksik else "tüm bilgiler tam, onay bekleniyor"
    return ("\n\nÖNEMLİ BAĞLAM: Kullanıcının YARIM kalmış bir rezervasyonu var "
            f"({durum}). Önce mevcut sorusuna kısaca yardımcı ol, ardından kullanıcıyı nazikçe "
            "rezervasyonu tamamlamaya geri davet et. Nihai hedef rezervasyonun tamamlanmasıdır.")


def run_rag(session: "Session", user_text: str) -> str:
    session.hotel_info_msgs.append(_user_content(user_text))
    response = client.models.generate_content(
        model=MODEL,
        contents=session.hotel_info_msgs,       # kendi thread'i → takip soruları çalışır
        config=types.GenerateContentConfig(
            system_instruction=HOTEL_INFO_SYSTEM + _reservation_nudge(session),
        ),
    )
    content = response.candidates[0].content
    session.hotel_info_msgs.append(content)
    return _content_text(content)


# ---------------------------------------------------------------------------
# 9) Şikayet subagent'ı (STUB) — kendi thread'i var
# ---------------------------------------------------------------------------

COMPLAINT_SYSTEM = """Sen otelin şikayet ve talep asistanısın. Kullanıcının şikayet/talebini
anlayışla karşıla, gerekli detayları (oda no, tarih, sorun) nazikçe sor, sonra kaydedildiğini bildir.
Türkçe konuş."""


def run_complaint_subagent(session: "Session") -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=session.complaint_msgs,
        config=types.GenerateContentConfig(
            system_instruction=COMPLAINT_SYSTEM + _reservation_nudge(session),
        ),
    )
    content = response.candidates[0].content
    session.complaint_msgs.append(content)
    return _content_text(content)


# ---------------------------------------------------------------------------
# 9b) Genel sohbet akışı — kendi thread'i (normal muhabbet + yedek akış)
# ---------------------------------------------------------------------------

CHAT_SYSTEM = """Sen bir otelin samimi, yardımsever asistanısın. Kullanıcıyla normal, doğal
bir şekilde Türkçe sohbet et. Kullanıcı rezervasyon, otel bilgisi veya şikayet konusuna
girmek isterse bu konularda yardımcı olabileceğini kısaca hatırlat, ama zorlama."""


def run_chat_agent(session: "Session") -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=session.chat_msgs,
        config=types.GenerateContentConfig(
            system_instruction=CHAT_SYSTEM + _reservation_nudge(session),
        ),
    )
    content = response.candidates[0].content
    session.chat_msgs.append(content)
    return _content_text(content)


# ---------------------------------------------------------------------------
# 10) Session + tur yönetimi
# ---------------------------------------------------------------------------

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


def handle_user_turn(session: Session, user_text: str) -> str:
    session.turn_tool_log = []                              # her tur logu sıfırla
    target = route(session, user_text)
    session.last_target = target

    if target == "reservation":
        session.active_flow = "reservation"
        session.reservation_msgs.append(_user_content(user_text))
        reply = run_reservation_subagent(session)
        if session.reservation_state.booking_id is not None:
            session.active_flow = None          # rezervasyon bitti, akışı serbest bırak
        return reply

    if target == "hotel_info":
        return run_rag(session, user_text)      # SAPMA: active_flow'a dokunma

    if target == "complaint":
        session.active_flow = "complaint"
        session.complaint_msgs.append(_user_content(user_text))
        return run_complaint_subagent(session)

    if target == "chat":
        session.chat_msgs.append(_user_content(user_text))   # YEDEK: active_flow'a dokunma
        return run_chat_agent(session)

    return "Anlayamadım, tekrar eder misiniz?"


# ---------------------------------------------------------------------------
# 11) Basit konsol döngüsü
# ---------------------------------------------------------------------------

def _summarize_result(out: dict) -> str:
    if out.get("is_error"):
        extra = f" {out.get('missing_fields')}" if out.get("missing_fields") else ""
        return f"HATA:{out.get('error')}{extra}"
    status = out.get("status", "?")
    if status == "incomplete":
        return f"incomplete eksik={out.get('missing_fields')}"
    if status == "available":
        return f"available fiyat={out.get('price')}"
    if status == "confirmed":
        return f"confirmed booking={out.get('booking_id')}"
    return status


def _print_tool_log(session: "Session") -> None:
    if not session.turn_tool_log:
        print(f"[araç] çağrılan tool yok (akış: {session.last_target})")
        return
    print("[araçlar]")
    for name, args, out in session.turn_tool_log:
        arg_str = ", ".join(f"{k}={v}" for k, v in args.items())
        print(f"   • {name}({arg_str}) -> {_summarize_result(out)}")


def main():
    if not API_KEY:
        print("[UYARI] GEMINI_API_KEY ayarlı değil. PowerShell: $env:GEMINI_API_KEY=\"...\"\n")
    session = Session()
    print("Otel asistanı hazır (Gemini). Çıkmak için 'q'.\n")
    while True:
        try:
            user_text = input("Siz: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_text:
            continue
        if user_text.lower() in {"q", "quit", "exit", "cikis", "çıkış"}:
            break
        try:
            reply = handle_user_turn(session, user_text)
        except Exception as e:
            print(f"\n[HATA] {type(e).__name__}: {e}\n"
                  f"       (API anahtarını/modeli kontrol et: GEMINI_API_KEY, MODEL={MODEL})\n")
            continue
        print(f"\nAsistan: {reply}")
        _print_tool_log(session)
        print(f"[debug] active_flow={session.active_flow} "
              f"eksik={_missing_fields(session.reservation_state)} "
              f"booking={session.reservation_state.booking_id}\n")


if __name__ == "__main__":
    main()
