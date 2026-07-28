"""Basit konsol döngüsü — kullanıcı girdisini alır, yanıtı ve tool/debug logunu basar."""

import sys

from .config import API_KEY, MODEL
from .orchestrator import handle_user_turn
from .reservation_state import missing_fields
from .session import Session


def _safe_print(text: str) -> None:
    """Konsol kodlaması (ör. cp1254) ham dökümdeki bir karakteri basamazsa turu çökertme."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc))


def _summarize_result(out: dict) -> str:
    if out.get("is_error"):
        extra = f" {out.get('missing_fields')}" if out.get("missing_fields") else ""
        return f"HATA:{out.get('error')}{extra}"
    status = out.get("status", "?")
    if status == "incomplete":
        return f"incomplete eksik={out.get('missing_fields')}"
    if status == "stage1_ok":
        return "stage1_ok → bed_options"
    if status == "no_match":
        return "no_match (uygun oda yok)"
    if status == "options":
        groups = out.get("availability", {}).get("groups", [])
        return f"options ({len(groups)} grup müsaitlik)"
    if status == "needs_confirmation":
        return "needs_confirmation (özet sunuldu, onay bekleniyor)"
    if status == "confirmed":
        return f"confirmed booking={out.get('booking_id')}"
    return status


def _print_raw_log(session: Session) -> None:
    """Bu turdaki her LLM çağrısının modele giren/çıkan ham verisini basar."""
    if not session.raw_log:
        return
    _safe_print("\n" + "-" * 20 + " RAW (bu turda modele GİREN/ÇIKAN ham veri) " + "-" * 20)
    for block in session.raw_log:
        _safe_print(block)
        _safe_print("-" * 84)


def _print_tool_log(session: Session) -> None:
    if not session.turn_tool_log:
        print(f"[araç] çağrılan tool yok (akış: {session.last_target})")
        return
    print("[araçlar]")
    for name, args, out in session.turn_tool_log:
        arg_str = ", ".join(f"{k}={v}" for k, v in args.items())
        print(f"   • {name}({arg_str}) -> {_summarize_result(out)}")


def main() -> None:
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
        _print_raw_log(session)                # ← normal mesajın hemen altına ham giriş/çıkış dökümü
        _print_tool_log(session)
        print(f"[debug] active_flow={session.active_flow} "
              f"eksik={missing_fields(session.reservation_state)} "
              f"booking={session.reservation_state.booking_id}")
        print(f"[token] Bu mesaj için: {session.turn_tokens} token "
              f"(düşünce {session.turn_thinking}, {session.turn_llm_calls} LLM çağrısı) "
              f"| Toplam: {session.total_tokens} token\n")
