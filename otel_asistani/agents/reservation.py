"""Rezervasyon subagent'ı — KENDİ mesaj thread'i + KENDİ tool'ları.

automatic_function_calling kapalıdır; tool döngüsü manuel yönetilir (dispatch).
Çağrılan her tool, session.turn_tool_log'a yazılır (konsolda gösterim için).

Güvenlik ağı: Model bir bilgi değiştiğinde aracı çağırmak yerine "kontrol ediyorum" deyip
beklerse (stall), bir kez mode=ANY ile check_availability'yi çağırmaya ZORLARIZ — böylece
DB sorgusu beklemeden yapılır ve yeni filtreye göre seçenekler sunulur.
"""

from datetime import date

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text, user_content
from ..prompt_rules import NUMBERS_AS_WORDS
from ..reservation_state import ReservationState
from ..reservation_tools import RESERVATION_TOOL, dispatch
from ..session import Session
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

RESERVATION_SYSTEM = """Sen bir otelin rezervasyon asistanısın. Rezervasyonu 3 AŞAMADA, adım adım tamamlarsın.

AŞAMA 1 — Zorunlu 4 bilgi (önce bunları topla):
  giriş tarihi, çıkış tarihi, toplam kişi sayısı, oda türü.
  Elindeki alanlarla check_availability'yi çağır (hepsini bilmesen de çağırabilirsin).
  - 'incomplete' + missing_fields dönerse YALNIZCA eksik alanları nazikçe sor.
  - 'no_match' dönerse bu bilgiler için uygun oda olmadığını söyle ve güncellemesini iste.
  - 'stage1_ok' dönerse HEMEN bed_options'ı çağır.
  Not: Kullanıcı bu aşamada fazladan bilgi (ör. çocuk sayısı) verirse yine de aktar; saklanır.

AŞAMA 2 — Seçenekleri sun ve seçimi KAYDET:
  bed_options, veritabanından gelen manzara tipi + yatak dizilişi seçeneklerini döndürür.
  Bu seçenekleri fiyatlarıyla birlikte, NUMARALANDIRARAK kullanıcıya listele ve birini seçmesini iste.
  Kullanıcı bir seçeneği seçince (numarayla ör. "2 numara" ya da tarif ederek) HEMEN complete_reservation'ı
  o seçeneğin view_type ve bed_layout'ı ile çağır — seçim böylece state'e KAYDEDİLİR (araya başka konu
  girse bile kaybolmaz). Sadece "harika seçim" deyip GEÇME; önce bu aracı çağır. Çocuk bilgisi henüz
  yoksa araç 'cocuk_bilgisi_eksik' döner (seçim yine de kaydedilmiştir) → AŞAMA 3'e geçip çocuk sayısını sor.

  KULLANICININ ÖN TERCİHİNE GÖRE SÜZ (senin uygulaman gereken seçim standardı, DB filtresi DEĞİL):
  Kullanıcı aşama-1'de İSTENMEDEN bir tercih belirttiyse (örn. "deniz manzarası", ya da belirli
  bir yatak dizilişi), bed_options TÜM uygun odaları döndürse bile kullanıcıya YALNIZCA bu tercihe
  uyan seçenekleri sun; uymayanları listeleme.
  Örnek: kullanıcı baştan "deniz" dediyse, gelen listeden yalnızca view_type = "deniz" olanları göster.
  - Tercihe uyan hiç seçenek yoksa bunu kullanıcıya söyle; tercihini değiştirmesini/gevşetmesini öner
    ve istersen mevcut diğer seçenekleri de sun.
  - Kullanıcı sonradan tercihini değiştirir/kaldırırsa süzgeci ona göre güncelle.
  - Bu süzme yalnızca SUNUMDA olur; bed_options'ı yine 4 filtreyle (tercih olmadan) çağır.

AŞAMA 3 — Özet, onay ve bitir:
  Seçim kaydedildikten sonra çocuk sayısını, çocuk varsa yaşlarını sor.
  Sonra complete_reservation'ı (seçim + çocuk bilgileriyle) confirmed OLMADAN çağır.
  - Araç 'needs_confirmation' + summary dönerse: özetteki TÜM bilgileri (giriş/çıkış tarihi,
    kişi sayısı, oda türü, manzara, yatak dizilişi, çocuk sayısı/yaşları, gecelik ve toplam
    fiyat) kullanıcıya net biçimde göster ve "Onaylıyor musunuz?" diye sor. SONRA BEKLE.
    Özeti uydurma; yalnızca summary'deki değerleri kullan.
  - Kullanıcı AÇIKÇA onaylarsa (evet / onaylıyorum) complete_reservation'ı confirmed=true ile
    TEKRAR çağır → 'confirmed' + booking_id döner, rezervasyon numarasını bildir.
  - Kullanıcı bir bilgiyi değiştirmek isterse ilgili aşamaya dön (gerekirse AŞAMA 1'e).
  - Kullanıcı onaylamadan ASLA confirmed=true gönderme.
  'secenekler_gecersiz' hatası alırsan aşama-1 bilgisi değişmiştir → AŞAMA 1'den yeniden başla.

BİLGİ DEĞİŞİRSE (çok önemli):
  Kullanıcı aşama-1 bilgilerinden birini (tarih / kişi sayısı / oda türü) değiştirirse:
  AYNI TURDA check_availability'yi YENİ bilgiyle ÇAĞIR (aracı gerçekten çalıştır),
  'stage1_ok' gelince HEMEN bed_options'ı çağır ve yeni seçenekleri sun.
  ASLA "kontrol ediyorum / müsaitliğe bakıyorum / sorguluyorum" deyip aracı çağırmadan durma.
  Bir işlemi yapacağını SÖYLEME — doğrudan ilgili aracı çağır. Metin cevabı YALNIZCA
  kullanıcıya soru sorman veya sonucu bildirmen gerektiğinde kullan.

Kurallar:
- Sırayı atlama: bed_options'tan ÖNCE 'stage1_ok' alınmış olmalı; seçim yapılmadan onay/özet isteme.
- Kullanıcıya var olmayan seçenek uydurma; yalnızca bed_options'ın döndürdüğü seçenekleri sun.
- NİHAİ HEDEF rezervasyonu tamamlatmaktır. Kullanıcı konuyu dağıtsa bile kısaca yardımcı olup
  kaldığın aşamadan devam et.
- Türkçe, kısa ve net konuş."""

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
            return client.models.generate_content(
                model=MODEL, contents=session.reservation_msgs, config=cfg,
            )

        # bed_options gibi bekleme yaratan bir üretim varsa: üretimi HEMEN başlat, bekleme
        # cümlesini onunla EŞ ZAMANLI üret (sorgu, filler'ı beklemez).
        response = run_with_wait_filler(_generate, filler_ctx) if filler_ctx else _generate()
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
