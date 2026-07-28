"""Rezervasyon subagent'ı — KENDİ mesaj thread'i + KENDİ tool'ları.

automatic_function_calling kapalıdır; tool döngüsü manuel yönetilir (dispatch).
Çağrılan her tool, session.turn_tool_log'a yazılır (konsolda gösterim için).

Güvenlik ağı: Model bir bilgi değiştiğinde aracı çağırmak yerine "kontrol ediyorum" deyip
beklerse (stall), bir kez mode=ANY ile check_availability'yi çağırmaya ZORLARIZ — böylece
DB sorgusu beklemeden yapılır ve yeni filtreye göre seçenekler sunulur.
"""

import os
from datetime import date

from google.genai import types

from ..config import MODEL, client
from ..gemini_utils import content_text, user_content
from ..prompt_rules import NUMBERS_AS_WORDS
from ..raw_log import log_llm_call
from ..reservation_state import ReservationState, stage1_missing, total_people
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
- TEK mesajda birlikte iste: giriş/çıkış tarihi, oda türü, grup bilgisi (YETİŞKİN sayısı, çocuk var mı, çocukların yaşları). Manzara (view_type) opsiyoneldir. Kullanıcıya "kaç kişi" değil "kaç YETİŞKİN" diye sor.
- SAYIM KURALINI AÇIKLA VE SEN HESAPLA: >12 yaş YETİŞKİN'dir → total_guests; <=12 yaş ÇOCUK'tur → children_count (yaşları children_ages). Örnek: 2 yetişkin + 15 ve 8 yaş → total_guests=3 (yetişkin), children_count=1, children_ages=[8].
- YATAK/KAPASİTE: gereken yatak sayısı = YETİŞKİN + ÇOCUK (toplam kişi). DB kapasite kontrolü ve oda planlaması DAİMA bu toplam üzerinden yapılır (çocuk da yatak ister).
- ASLA BİLGİ UYDURMA/VARSAYMA (özellikle oda türü). Sadece verilenleri araca gönder. Eksikse tahmini arama yapma; 'incomplete' dönünce eksiklerin HEPSİNİ birlikte sor.
- 'no_match' → uygun oda yok, güncellettir. 'stage1_ok' → HEMEN bed_options çağır.

2) AŞAMA 2 (Öneri ve Seçim):
- bed_options müsaitliği + total_people (toplam kişi = yetişkin+çocuk) döner. ODA TÜRÜNÜ DEĞİŞTİRME. En fazla 5 seçenek sun. Fiyatı DB'den GELDİĞİ GİBİ (price_per_night) DOĞRUDAN ver; gece sayısıyla ÇARPMA, toplam HESAPLAMA yapma. Uydurma.
- SEÇENEK SUNUMU (ÇOK ÖNEMLİ): Seçenekleri ASLA etiketleme/numaralandırma — "1/2/3", "Birinci/İkinci/Üçüncü seçenek", "seçenek bir/iki", numaralı ya da madde madde liste KULLANMA. Seçenekleri AKICI, doğal cümlelerle, birbirinden İÇERİKLERİYLE (manzara + oda dağılımı + fiyat) ayırt edilecek şekilde anlat. Seçimi de numarayla DEĞİL, içerikle iste.
  YANLIŞ: "Birinci seçenek: bir deniz bir kara oda... İkinci seçenek: iki bahçe oda... Hangi seçeneği tercih edersiniz?"
  DOĞRU: "Deniz manzaralı bir oda ile kara manzaralı bir odayı birlikte alabilirsiniz; fiyatları dört bin ve üç bin sekiz yüz TL. Dilerseniz iki bahçe manzaralı oda da mümkün; her biri üç bin beş yüz TL. Hangisi size daha uygun olur?"
- Planlama Kuralları (Farklı manzaralar birleşip KARMA plan olabilir; her zaman TOPLAM kişi = yetişkin+çocuk üzerinden):
  1. Manzara Önceliği: İstenen manzarada tek odaya TÜM grup (toplam kişi) sığıyorsa (max_guests >= toplam kişi) → YALNIZCA onu öner (BİREBİR). Sığmıyorsa önce o manzaradan count kadar al, kalanı başka manzaradan tamamla (KARMA). İstenen manzarada hiç yoksa/belirtilmediyse diğerlerinden öner.
  2. Dengeli Bölme: TOPLAM kişiyi (yetişkin+çocuk) odalara eşit dağıt (6 kişi → 3+3). Seçilen odaların toplam kapasitesi toplam kişiden AZ olamaz. İstenmedikçe "5+1" gibi dengesiz bölme.
- Kullanıcı seçimini SERBEST/konuşma diliyle yapabilir (ör. "deniz manzaralı olan", "kara odaları", "ilkini", "ikincisini", "bahçeli olsun"). Ne kastettiğini ANLA ve doğru odaları HEMEN complete_reservation(rooms=[{view_type, room_count}, ...]) ile çağır (metinle "harika" deyip geçme!). Belirsizse kısaca netleştir. 'gecersiz_secim' → yeniden seçtir.

3) AŞAMA 3 (Özet ve Onay):
- Seçim yapılınca complete_reservation'ı confirmed OLMADAN çağır.
- 'needs_confirmation' + summary dönünce: Özetteki TÜM bilgileri (tarihler, kişiler, oda türü/dağılımı, çocuk, fiyat) göster; fiyatı summary'deki DB değeriyle (price) DOĞRUDAN yaz, gece sayısıyla çarpıp toplam HESAPLAMA. "Onaylıyor musunuz?" diye sor ve BEKLE. Özeti uydurma.
- Kullanıcı AÇIKÇA onaylarsa (evet/onaylıyorum) confirmed=true ile TEKRAR çağır → booking_id bildir. Onaysız ASLA confirmed=true gönderme.
- Değişiklik isterse ilgili aşamaya dön. 'secenekler_gecersiz' → AŞAMA 1'den başla.

BİLGİ DEĞİŞİRSE / STALL ENGELİ:
- Aşama-1 bilgisi değişirse AYNI TURDA check_availability'yi çağır, 'stage1_ok' gelince HEMEN bed_options'ı çağır.
- ASLA "kontrol ediyorum/bakıyorum" deyip aracı çağırmadan durma. Yapacağını söyleme, doğrudan aracı çağır. Metni sadece soru/sonuç için kullan.
- Sıra atlama, seçenek uydurma. NİHAİ HEDEF rezervasyonu tamamlatmaktır; konu dağılsa bile kaldığın yerden devam et. Türkçe, kısa ve net konuş."""

# Model, aracı çağırmadan "kontrol ediyorum" tarzı beklemeye geçtiğinde yakalamak için ipuçları.
_STALL_HINTS = ("kontrol ed", "sorgul", "müsaitli", "musaitli", "bakıyorum", "bakayım", "tekrar bak")


def _system_text() -> str:
    """Rezervasyon system promptu (tarih notu + akış kuralları + sayı yazımı)."""
    return (_DATE_NOTE.format(today=date.today().isoformat())
            + RESERVATION_SYSTEM + "\n\n" + NUMBERS_AS_WORDS)


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
    # Rezervasyon çağrılarında düşünme düzeyi. gemini-3.6-flash düşünmeyi thinking_LEVEL ile kontrol
    # eder (thinking_budget DEĞİL — o 400 verebilir). Deney sonucu: düşük düşünme aynı isabetle çok
    # daha ucuz. VARSAYILAN "low". Geçerli: minimal | low | medium | high. OTEL_RES_THINKING_LEVEL
    # ile override edilir.
    level = os.environ.get("OTEL_RES_THINKING_LEVEL") or "low"
    thinking_config = types.ThinkingConfig(thinking_level=level)

    return types.GenerateContentConfig(
        system_instruction=_system_text(),
        tools=[RESERVATION_TOOL],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # manuel kontrol
        tool_config=tool_config,
        thinking_config=thinking_config,
    )


def _looks_like_stall(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in _STALL_HINTS)


def _bed_options_wait_context(state: ReservationState) -> str:
    """bed_options DB sorgusu öncesi bekleme cümlesi için bağlam (kullanıcının aşama-1 girdileri)."""
    return (f"Kullanıcı şu rezervasyon için uygun oda ve yatak seçeneklerini bekliyor: "
            f"giriş {state.check_in}, çıkış {state.check_out}, {total_people(state)} kişi, "
            f"{state.room_type} oda. Şimdi uygun odalar veritabanından sorgulanacak.")


def run_reservation_subagent(session: Session, max_iters: int = 8) -> str:
    force_tool = None       # sonraki turda ZORLANACAK araç (mode=ANY)
    text_only = False       # sonraki turda araç YASAK (mode=NONE) → özeti sun/soru sor
    filler_ctx = None       # sonraki üretim, EŞ ZAMANLI bir bekleme cümlesiyle yapılacaksa bağlam
    forced_once = False     # metin-stall zorlamasını tek sefere sınırla
    for loop_i in range(max_iters):
        expect_text = text_only                                 # bu tur kasıtlı metin turu mu?
        cfg = _config(force_tool, text_only)

        # Bu turun modu (loglamada mode=ANY zorlama / mode=NONE metin turu görünür olsun).
        note = f"iter {loop_i + 1}"
        if force_tool:
            note += f" | force_tool={force_tool} (mode=ANY)"
        if text_only:
            note += " | text_only (mode=NONE)"

        def _generate(cfg=cfg):
            # Savunma: geçmişte None varsa (eski/kirli oturum) süz → pydantic ValidationError'ı önle.
            res = client.models.generate_content(
                model=MODEL,
                contents=[m for m in session.reservation_msgs if m is not None],
                config=cfg,
            )
            record_usage(session, res)
            return res

        # bed_options gibi bekleme yaratan bir üretim varsa: üretimi HEMEN başlat, bekleme
        # cümlesini onunla EŞ ZAMANLI üret (sorgu, filler'ı beklemez).
        response = run_with_wait_filler(_generate, filler_ctx, session) if filler_ctx else _generate()
        # Ham döküm: contents HENÜZ model yanıtı eklenmeden loglanır → tam olarak modele GİDEN girdi.
        log_llm_call(session, "RESERVATION", system=_system_text(),
                     contents=session.reservation_msgs, tools=[RESERVATION_TOOL],
                     response=response, model=MODEL, note=note)
        force_tool, text_only, filler_ctx = None, False, None   # zorlama/kısıt tek turluktur
        candidate = response.candidates[0] if response.candidates else None
        # Model bazen content=None döndürebilir (ör. finish_reason=MAX_TOKENS: bütçe tümüyle
        # düşünmeye gitti, görünür çıktı yok). Geçmişi None ile KİRLETME → yoksa sonraki
        # çağrıda contents içinde None gider ve pydantic ValidationError verir. Nazikçe çık.
        if candidate is None or candidate.content is None:
            fr = getattr(candidate, "finish_reason", None)
            return f"Üzgünüm, yanıtı oluşturamadım (sebep: {fr}). Lütfen tekrar dener misiniz?"
        session.reservation_msgs.append(candidate.content)      # model turu

        fcs = response.function_calls or []
        if not fcs:
            text = content_text(candidate.content) or "(boş yanıt)"
            # Kasıtlı metin turu (özet/onay sorusu) → olduğu gibi kullanıcıya dön.
            if expect_text:
                return text
            # Model aracı çağırmadan "kontrol ediyorum" deyip beklerse → bir kez zorla çağırt.
            # Ama YALNIZCA aşama-1 tamsa: elde veri yokken zorlamak boş bir çağrı yakıp
            # 'incomplete' döndürür (model zaten bilgi istiyordur). Sadece "bilgi DEĞİŞTİ ama
            # aracı çağırmadı" durumunda (state dolu) zorlamak anlamlıdır.
            if not forced_once and _looks_like_stall(text) and not stage1_missing(session.reservation_state):
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
