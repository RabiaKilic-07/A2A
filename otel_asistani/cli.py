"""Basit konsol döngüsü — kullanıcı girdisini alır, yanıtı ve tool/debug logunu basar."""

from .config import API_KEY, MODEL
from .orchestrator import handle_user_turn
from .reservation_state import missing_fields
from .session import Session


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
        _print_tool_log(session)
        print(f"[debug] active_flow={session.active_flow} "
              f"eksik={missing_fields(session.reservation_state)} "
              f"booking={session.reservation_state.booking_id}\n")
