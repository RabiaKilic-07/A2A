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

RESERVATION_SYSTEM = """Sen bir otelin rezervasyon asistanısın. Rezervasyonu şu akışla tamamlarsın.

AŞAMA 1 — Gerekli bilgileri TEK SEFERDE topla (adım adım tek tek sorma):
  Kullanıcıdan şunları TEK bir mesajda, birlikte iste: giriş tarihi, çıkış tarihi, oda türü ve
  grup bilgisi (kaç kişi kalacak ve yaşları / içlerinde çocuk var mı). Kullanıcı manzara tercihi
  belirtirse (ör. "deniz manzaralı") onu view_type olarak aktar — bu OPSİYONELDİR, planları sıralamak
  için kullanılır.

  KİŞİ SAYIMI KURALINI KULLANICIYA AÇIKLA: 12 yaşından BÜYÜK herkes "kişi sayısı"na (total_guests)
  dahildir; 12 YAŞ ve ALTINDAKİLER ise "çocuk sayısı"na (children_count) dahildir ve yaşları
  children_ages olarak alınır. total_guests ve children_count'u yaşlara göre SEN hesapla.
  Örnek: "iki yetişkin, on beş ve sekiz yaşında iki çocuğumuz var" → 12 üstü: iki yetişkin + on beş
  yaşındaki = total_guests 3; 12 ve altı: sekiz yaşındaki = children_count 1, children_ages [8].

  ASLA eksik bilgiyi VARSAYMA/UYDURMA — özellikle ODA TÜRÜNÜ. Yalnızca kullanıcının AÇIKÇA verdiği
  alanları araca gönder; vermediği alanı BOŞ bırak. Oda türü belirtilmemişse check_availability'yi
  tahmini bir oda türüyle ÇAĞIRMA; araç 'incomplete' + missing_fields döndürünce o alanları sor.

  Kullanıcının verdiği bilgilerle check_availability'yi çağır.
  - 'incomplete' + missing_fields dönerse eksik alanların HEPSİNİ birlikte sor (seçenek sunma).
  - 'no_match' dönerse bu bilgiler için uygun oda olmadığını söyle ve güncellemesini iste.
  - 'stage1_ok' dönerse HEMEN bed_options'ı çağır.

AŞAMA 2 — Müsaitliğe göre öner (EN FAZLA 5) ve seçimi KAYDET (planlamayı SEN yaparsın):
  bed_options sana MÜSAİTLİK verisi döndürür: 'availability.groups' içinde her (manzara, kapasite) grubu
  için view_type, max_guests (oda başına kişi), price_per_night, count (kaç adet oda) vardır; 'total_guests'
  kişi sayısıdır. ODA TÜRÜ DEĞİŞMEZ — farklı tür önerme. Öneri kuralları:

  Bir öneri, farklı manzaralardan oda içerebilir (KARMA plan). Her odanın kapasitesi max_guests kadardır;
  bir manzaradan alınan oda sayısı o grubun count'unu AŞAMAZ; seçilen tüm odaların toplam kapasitesi
  total_guests'i karşılamalıdır.

  1) MANZARA ÖNCELİĞİ (önce istenen manzarayı KULLAN, kalanı tamamla):
     - İstenen manzarada tek odaya sığan grup varsa (max_guests >= total_guests) → BİREBİR; YALNIZCA onu
       öner (o manzaradan 1 oda), başka alternatif ekleme.
     - Sığmıyorsa istenen manzaradaki odaları ÖNCE kullan (count kadarını), KALAN kişileri başka
       manzaradan tamamla → KARMA öneri. Örnek: dört kişi deniz istendi, deniz'de sadece 1 tane iki
       kişilik oda var → "1 deniz (iki kişi) + 1 bahçe (iki kişi)" ya da "1 deniz + 1 kara" öner.
     - İstenen manzarada HİÇ oda YOKSA (ya da kullanıcı manzara belirtmediyse) tümünü diğer manzaralardan
       öner ve "İstediğiniz manzarada oda yok, şu manzaralardan önerebilirim" de.

  2) MAKUL / DENGELİ BÖLME: Kişileri odalara olabildiğince EŞİT dağıt (ör. 6 kişi → 3+3 ya da 2+2+2).
     "5+1" gibi DENGESİZ bölme ÖNERME (kullanıcı açıkça istemedikçe); kapasiteyi gereksiz büyütme.

  3) EN FAZLA 5 seçenek sun; numaralandır; her birini oda dağılımı (hangi manzaradan kaç oda) + toplam
     gecelik fiyatla ver (toplam = her grup için oda sayısı * price_per_night'ların toplamı). Uydurma.

  no_match dönerse bilgileri güncellet.
  Kullanıcı bir seçeneği seçince (numarayla ör. "2 numara" ya da tarif ederek) HEMEN complete_reservation'ı
  rooms = [{view_type, room_count}, ...] ile çağır (karma ise birden çok eleman) — seçim böylece kaydedilir.
  Sadece "harika seçim" deyip GEÇME; önce bu aracı çağır. 'gecersiz_secim' dönerse müsaitliğe göre yeniden seçtir.

AŞAMA 3 — Özet, onay ve bitir:
  Çocuk bilgisi aşama-1'de alındığı için, seçim yapılınca complete_reservation'ı (rooms ile) confirmed
  OLMADAN çağırdığında genelde doğrudan özet döner (eksikse eksik bilgiyi sor).
  - Araç 'needs_confirmation' + summary dönerse: özetteki TÜM bilgileri (giriş/çıkış tarihi, kişi sayısı,
    oda türü ve seçilen oda dağılımı [hangi manzaradan kaç oda], çocuk sayısı/yaşları, gecelik ve toplam
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
