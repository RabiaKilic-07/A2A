"""A/B DENEYİ — Rezervasyon akışında 'düşünce' (thinking) doğruluğa yardım ediyor mu?

Aynı sabit rezervasyon senaryosunu farklı düşünme düzeyleriyle çalıştırıp karşılaştırır:
  * HIGH                → OTEL_RES_THINKING_LEVEL=high  (Gemini 3 varsayılanı)
  * LOW                 → OTEL_RES_THINKING_LEVEL=low   (kodun YENİ varsayılanı)
  * MINIMAL             → OTEL_RES_THINKING_LEVEL=minimal

NOT: Gemini 3.x düşünmeyi thinking_LEVEL ile kontrol eder (thinking_budget=0 → 400 verir).

Ölçtükleri:
  * DOĞRULUK : rezervasyon tamamlandı mı (booking_id), araç sırası doğru mu, hata döndü mü
  * MALİYET  : toplam token, 'düşünce' tokenı, LLM çağrı sayısı

Model çıktısı deterministik değildir; her düzeyi N kez çalıştırıp ortalama alır (varsayılan 2).

Çalıştırma (senin terminalinde, GEMINI_API_KEY ayarlıyken):
    python deney_thinking.py            # her düzey 2 kez
    python deney_thinking.py 3          # her düzey 3 kez
"""

import os
import sys

# Ham döküm gürültüsünü kapat (özet sayaçları session'dan okuyoruz). raw_log import'tan ÖNCE ayarla.
os.environ["OTEL_RAW_LOG"] = "0"

# API anahtarı YOKSA erken çık: config.py, import anında Gemini istemcisini kurar ve anahtarsız patlar.
if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
    print("[DUR] GEMINI_API_KEY ayarlı değil — canlı deney yapılamaz.\n"
          "      PowerShell'de: $env:GEMINI_API_KEY=\"...\"  sonra: python deney_thinking.py")
    sys.exit(0)

from otel_asistani.orchestrator import handle_user_turn      # noqa: E402
from otel_asistani.session import Session                    # noqa: E402

# --- Sabit senaryo: 3 kişi, deluxe, deniz, 10-13 Ağustos 2026 → DLX-01 (max 3) birebir oturur ---
SENARYO = [
    "Üç yetişkin için on Ağustos giriş, on üç Ağustos çıkış tarihli, deluxe, deniz manzaralı bir oda ayırtmak istiyorum. Çocuk yok.",
    "Deniz manzaralı üç kişilik odayı istiyorum.",
    "Evet, onaylıyorum.",
]

# Beklenen sağlıklı araç sırası (doğruluk kontrolü için gevşek eşleşme).
BAD_STATUSES = {"no_match", "gecersiz_secim", "secenekler_gecersiz", "secim_yapilmadi",
                "asama1_eksik", "cocuk_bilgisi_eksik"}


def _tool_summary(out: dict) -> str:
    if out.get("is_error"):
        return f"HATA:{out.get('error')}"
    return out.get("status", "?")


def run_once(level):
    """Senaryoyu bir kez çalıştırır; düşünme düzeyini uygular ve metrikleri döndürür.
    level: None (varsayılan/high) | "low" | "minimal" | "medium" | "high"."""
    if level is None:
        os.environ.pop("OTEL_RES_THINKING_LEVEL", None)
    else:
        os.environ["OTEL_RES_THINKING_LEVEL"] = str(level)

    session = Session()
    tool_seq, errors, api_error = [], 0, None
    for i, user_text in enumerate(SENARYO, 1):
        try:
            reply = handle_user_turn(session, user_text)
        except Exception as e:
            api_error = f"{type(e).__name__}: {e}"
            print(f"    [tur {i}] İSTİSNA: {api_error}")
            break                               # bir tur patladıysa kalan turları boşa harcama
        for name, _args, out in session.turn_tool_log:
            st = _tool_summary(out)
            tool_seq.append(f"{name}:{st}")
            if out.get("is_error") or out.get("status") in BAD_STATUSES:
                errors += 1
        short = " ".join(reply.split())[:110]
        print(f"    [tur {i}] hedef={(session.last_target or '-'):11} "
              f"tok={session.turn_tokens:5} düşünce={session.turn_thinking:4} "
              f"çağrı={session.turn_llm_calls} | {short}")

    booked = session.reservation_state.booking_id is not None
    return {
        "booked": booked,
        "booking_id": session.reservation_state.booking_id,
        "tokens": session.total_tokens,
        "thinking": session.total_thinking,
        "llm_calls": session.total_llm_calls,
        "tool_calls": len(tool_seq),
        "errors": errors,
        "api_error": api_error,
        "tool_seq": tool_seq,
    }


def average(runs, key):
    return sum(r[key] for r in runs) / len(runs) if runs else 0


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2
    # Not: kod varsayılanı artık "low"; baseline'ın gerçekten HIGH olması için düzeyi AÇIKÇA veriyoruz.
    conditions = [
        ("DÜŞÜNCE HIGH", "high"),
        ("DÜŞÜNCE LOW (yeni varsayılan)", "low"),
        ("DÜŞÜNCE MINIMAL", "minimal"),
    ]

    results = {}
    for label, level in conditions:
        print(f"\n{'=' * 78}\n### AYAR: {label}  —  {n} çalıştırma\n{'=' * 78}")
        runs = []
        for k in range(1, n + 1):
            print(f"  -- çalıştırma {k}/{n} --")
            runs.append(run_once(level))
        results[label] = runs

    # --- Karşılaştırma tablosu ---
    print(f"\n{'=' * 78}\n### SONUÇ KARŞILAŞTIRMASI\n{'=' * 78}")
    print(f"{'AYAR':28} {'başarı':>8} {'ort.token':>10} {'ort.düşünce':>12} "
          f"{'ort.çağrı':>10} {'ort.hata':>9} {'api-hata':>9}")
    for label, _ in conditions:
        runs = results[label]
        basari = sum(r["booked"] for r in runs)
        api_hata = sum(1 for r in runs if r["api_error"])
        print(f"{label:28} {basari}/{len(runs):<6} {average(runs,'tokens'):10.0f} "
              f"{average(runs,'thinking'):12.0f} {average(runs,'llm_calls'):10.1f} "
              f"{average(runs,'errors'):9.1f} {api_hata:>9}")

    # --- Araç sırası dökümü (doğruluğu göz ile kontrol için) ---
    print(f"\n{'-' * 78}\nAraç sıraları (her çalıştırma):")
    for label, _ in conditions:
        print(f"\n  {label}:")
        for i, r in enumerate(results[label], 1):
            ok = "✓ REZERVE" if r["booked"] else "✗ tamamlanmadı"
            print(f"    {i}. {ok} ({r['booking_id']})  hata={r['errors']}")
            print(f"       {' → '.join(r['tool_seq']) or '(araç çağrısı yok)'}")
            if r["api_error"]:
                print(f"       API HATASI: {r['api_error']}")

    # --- Kaba yorum: HIGH (varsayılan) temel alınır, azaltılmış düzeyler onunla kıyaslanır ---
    base_label = conditions[0][0]
    base = results[base_label]
    b_base, t_base = sum(r["booked"] for r in base), average(base, "tokens")
    print(f"\n{'-' * 78}\nKABA YORUM (temel = {base_label}):")
    print(f"  • Temel başarı: {b_base}/{len(base)}, ort. {t_base:.0f} token, "
          f"ort. {average(base,'thinking'):.0f} düşünce.")
    for label, _ in conditions[1:]:
        runs = results[label]
        if all(r["api_error"] for r in runs):
            print(f"  • {label}: TÜM çalıştırmalar API hatası verdi → bu model bu düzeyi kabul "
                  f"etmiyor olabilir (örn. thinking_level birleşimi). Detay yukarıda.")
            continue
        b, t = sum(r["booked"] for r in runs), average(runs, "tokens")
        fark = f"~%{100*(t_base-t)/t_base:.0f} {'az' if t < t_base else 'çok'}" if t_base else "?"
        print(f"  • {label}: başarı {b}/{len(runs)}, {t:.0f} token ({fark}), "
              f"düşünce {average(runs,'thinking'):.0f}.")
    print("  → KARAR: bir düzeyde başarı temeldekiyle EŞİT/DAHA İYİ kalıp token/düşünce düşüyorsa, "
          "o düzey tercih edilebilir. Başarı düşüyorsa (hata artıyor/rezervasyon tamamlanmıyor) "
          "düşünme doğruluğa yardım ediyordur, HIGH kalsın.")


if __name__ == "__main__":
    main()
