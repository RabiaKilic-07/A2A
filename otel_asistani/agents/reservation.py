"""Rezervasyon subagent'ı — KENDİ mesaj thread'i + KENDİ tool'ları.

automatic_function_calling kapalıdır; tool döngüsü manuel yönetilir (dispatch).
Çağrılan her tool, session.turn_tool_log'a yazılır (konsolda gösterim için).

Güvenlik ağı: Model bir bilgi değiştiğinde aracı çağırmak yerine "kontrol ediyorum" deyip
beklerse (stall), bir kez mode=ANY ile check_availability'yi çağırmaya ZORLARIZ — böylece
DB sorgusu beklemeden yapılır ve yeni filtreye göre seçenekler sunulur.
"""

import json
from datetime import date

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text, user_content
from ..hotel_backend import hotel_backend
from ..prompt_rules import NUMBERS_AS_WORDS
from ..reservation_state import ReservationState
from ..reservation_tools import RESERVATION_TOOL, dispatch
from ..session import Session, record_usage
from ..wait_filler import run_with_wait_filler

# Sistem promptunun başına eklenir; bugünün tam tarihi her istekte dinamik olarak verilir.
_DATE_NOTE = (
    "BUGÜNÜN TARİHİ: {today} (YYYY-MM-DD). Rezervasyon işlemlerini YALNIZCA bu tarih ve SONRASI "
    "için yap; geçmiş bir giriş/çıkış tarihi istenirse nazikçe reddet ve güncel ya da gelecek bir "
    "tarih iste. Kullanıcı yıl belirtmeden tarih verirse (ör. '28 Aralık'), onu bugünden itibaren "
    "GELECEKTEKİ en yakın tarih olacak şekilde yorumla (gerekirse bir sonraki yıla taşı). Çıkış "
    "tarihi girişten sonra olmalıdır. Rezervasyon yıl sınırını AŞABİLİR "
    "(ör. giriş 2026-12-28, çıkış 2027-01-03 geçerlidir).\n\n"
)

RESERVATION_SYSTEM = """Sen bir otelin rezervasyon asistanısın. Akış:

1) AŞAMA 1 (Bilgi Toplama):
- TEK mesajda birlikte iste: giriş/çıkış tarihi, oda türü, grup bilgisi (kişi sayısı, yaşlar, çocuk var mı). Manzara (view_type) opsiyoneldir.
- KİŞİ SAYIMI KURALINI AÇIKLA VE SEN HESAPLA: >12 yaş total_guests, <=12 yaş children_count (yaşları children_ages). Örnek: 2 yetişkin + 15 ve 8 yaş → total_guests=3, children_count=1, children_ages=[8].
- ASLA BİLGİ UYDURMA/VARSAYMA (özellikle oda türü). Sadece verilenleri araca gönder. Eksikse tahmini arama yapma; 'incomplete' dönünce eksiklerin HEPSİNİ birlikte sor.
- 'no_match' → uygun oda yok, güncellettir. 'stage1_ok' → HEMEN bed_options çağır.

2) AŞAMA 2 (Öneri ve Seçim):
- bed_options müsaitliği verir. ODA TÜRÜNÜ DEĞİŞTİRME. En fazla 5 seçenek sun, numaralandır, oda dağılımı + toplam gecelik fiyatla ver. Uydurma.
- Planlama Kuralları (Farklı manzaralar birleşip KARMA plan olabilir):
  1. Manzara Önceliği: İstenen manzarada tek odaya sığan grup varsa (max_guests >= total_guests) → YALNIZCA onu öner (BİREBİR). Sığmıyorsa önce o manzaradan count kadar al, kalanı başka manzaradan tamamla (KARMA). İstenen manzarada hiç yoksa/belirtilmediyse diğerlerinden öner.
  2. Dengeli Bölme: Kişileri odalara eşit dağıt (6 kişi → 3+3). İstenmedikçe "5+1" gibi dengesiz bölme.
- Kullanıcı seçince HEMEN complete_reservation(rooms=[{view_type, room_count}, ...]) çağır (metinle "harika" deyip geçme!). 'gecersiz_secim' → yeniden seçtir.

3) AŞAMA 3 (Özet ve Onay):
- Seçim yapılınca complete_reservation'ı confirmed OLMADAN çağır.
- 'needs_confirmation' + summary dönünce: Özetteki TÜM bilgileri (tarihler, kişiler, oda türü/dağılımı, çocuk, gecelik/toplam fiyat) göster, "Onaylıyor musunuz?" diye sor ve BEKLE. Özeti uydurma.
- Kullanıcı AÇIKÇA onaylarsa (evet/onaylıyorum) confirmed=true ile TEKRAR çağır → booking_id bildir. Onaysız ASLA confirmed=true gönderme.
- Değişiklik isterse ilgili aşamaya dön. 'secenekler_gecersiz' → AŞAMA 1'den başla.

BİLGİ DEĞİŞİRSE / STALL ENGELİ:
- Aşama-1 bilgisi değişirse AYNI TURDA check_availability'yi çağır, 'stage1_ok' gelince HEMEN bed_options'ı çağır.
- ASLA "kontrol ediyorum/bakıyorum" deyip aracı çağırmadan durma. Yapacağını söyleme, doğrudan aracı çağır. Metni sadece soru/sonuç için kullan.
- Sıra atlama, seçenek uydurma. NİHAİ HEDEF rezervasyonu tamamlatmaktır; konu dağılsa bile kaldığın yerden devam et. Türkçe, kısa ve net konuş."""

# Model, aracı çağırmadan "kontrol ediyorum" tarzı beklemeye geçtiğinde yakalamak için ipuçları.
_STALL_HINTS = ("kontrol ed", "sorgul", "müsaitli", "musaitli", "bakıyorum", "bakayım", "tekrar bak")


def _config(force_tool: str = None, text_only: bool = False) -> types.GenerateContentConfig:
    tool_config = None
    if text_only:                                   # araç çağırmayı YASAKLA (mode=NONE) → sadece metin
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="NONE")
        )
    elif force_tool:                                # aracı çağırmaya ZORLA (mode=ANY)
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=[force_tool],
            )
        )
    return types.GenerateContentConfig(
        system_instruction=(_DATE_NOTE.format(today=date.today().isoformat())
                             + RESERVATION_SYSTEM + "\n\n" + NUMBERS_AS_WORDS),
        tools=[RESERVATION_TOOL],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # manuel kontrol
        tool_config=tool_config,
    )


def _looks_like_stall(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in _STALL_HINTS)


def _bed_options_wait_context(state: ReservationState) -> str:
    """bed_options DB sorgusu öncesi bekleme cümlesi için bağlam (kullanıcının aşama-1 girdileri)."""
    return (f"Kullanıcı şu rezervasyon için uygun oda ve yatak seçeneklerini bekliyor: "
            f"giriş {state.check_in}, çıkış {state.check_out}, {state.total_guests} kişi, "
            f"{state.room_type} oda. Şimdi uygun odalar veritabanından sorgulanacak.")


def run_reservation_subagent(session: Session, max_iters: int = 8) -> str:
    force_tool = None       # sonraki turda ZORLANACAK araç (mode=ANY)
    text_only = False       # sonraki turda araç YASAK (mode=NONE) → özeti sun/soru sor
    filler_ctx = None       # sonraki üretim, EŞ ZAMANLI bir bekleme cümlesiyle yapılacaksa bağlam
    forced_once = False     # metin-stall zorlamasını tek sefere sınırla
    for _ in range(max_iters):
        expect_text = text_only                                 # bu tur kasıtlı metin turu mu?
        cfg = _config(force_tool, text_only)

        def _generate(cfg=cfg):
            res = client.models.generate_content(
                model=MODEL, contents=session.reservation_msgs, config=cfg,
            )
            record_usage(session, res)
            return res

        # bed_options gibi bekleme yaratan bir üretim varsa: üretimi HEMEN başlat, bekleme
        # cümlesini onunla EŞ ZAMANLI üret (sorgu, filler'ı beklemez).
        response = run_with_wait_filler(_generate, filler_ctx, session) if filler_ctx else _generate()
        force_tool, text_only, filler_ctx = None, False, None   # zorlama/kısıt tek turluktur
        candidate = response.candidates[0]
        session.reservation_msgs.append(candidate.content)      # model turu

        fcs = response.function_calls or []
        if not fcs:
            text = content_text(candidate.content) or "(boş yanıt)"
            # Kasıtlı metin turu (özet/onay sorusu) → olduğu gibi kullanıcıya dön.
            if expect_text:
                return text
            # Model aracı çağırmadan "kontrol ediyorum" deyip beklerse → bir kez zorla çağırt.
            if not forced_once and _looks_like_stall(text):
                forced_once = True
                force_tool = "check_availability"
                session.reservation_msgs.append(
                    user_content("Sadece açıklama yapma; güncel bilgilerle ilgili aracı ŞİMDİ çağır.")
                )
                continue
            return text

        response_parts = []
        for fc in fcs:
            args = dict(fc.args or {})
            out = dispatch(session.reservation_state, fc.name, args)
            session.turn_tool_log.append((fc.name, args, out))     # ← tool logu
            if fc.name == "bed_options":                           # DB endpoint'inden dönen oda bilgilerini logla
                st = session.reservation_state
                db = hotel_backend.available_rooms(
                    check_in=st.check_in, check_out=st.check_out, room_type=st.room_type,
                )
                print("\nbed options - DB (oda grupları/sayıları):",
                      json.dumps(db, ensure_ascii=False, indent=2))
            status = out.get("status")
            # Aşama-1 tamamsa (bilgi değişse bile) DB sorgusunu BEKLETMEDEN yaptır: stage1_ok
            # gelir gelmez bed_options'ı zorla. bed_options üretimi, sonraki turda bir bekleme
            # cümlesiyle EŞ ZAMANLI yapılsın diye bağlamı hazırla (filler sorguyu bekletmez).
            if status == "stage1_ok":
                force_tool = "bed_options"
                filler_ctx = _bed_options_wait_context(session.reservation_state)
            # Onay gerekiyorsa: bu tur araç ÇAĞIRMA — özeti sun, "Onaylıyor musunuz?" diye sor,
            # sonra kullanıcıyı bekle. Model kendi kendine confirmed=true ile devam edemesin.
            elif status == "needs_confirmation":
                text_only = True
            # Rezervasyon onaylandı: sonucu (booking_id) bildir; tekrar araç çağırma.
            elif status == "confirmed":
                text_only = True
            response_parts.append(types.Part.from_function_response(name=fc.name, response=out))
        session.reservation_msgs.append(types.Content(role="user", parts=response_parts))

    return "Üzgünüm, işlemi tamamlayamadım. Lütfen tekrar dener misiniz?"
