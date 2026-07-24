"""Bekleme (oyalama) cümlesi üretimi — TTS'te sessizliği önlemek için.

YALNIZCA bekleme yaratan iki işlemden ÖNCE çağrılır:
  * hotel_info (RAG) çalışmadan önce
  * rezervasyonda bed_options (DB sorgusu) çalışmadan önce

Üretilen cümle SABİT bir kalıp değildir; her seferinde kullanıcının o anki isteğine/bağlamına
göre değişir. (bed_options 'mode=ANY' ile zorlandığından model o turda metin üretemez; bu yüzden
filler ayrı, kısa bir üretimle önceden oluşturulur.)
"""

import concurrent.futures

from google.genai import types

from .config import MODEL, client
from .gemini_utils import content_text
from .prompt_rules import NUMBERS_AS_WORDS

_FILLER_SYSTEM = (
    "Görevin: kısa bir sorgulama/bilgi getirme işlemi yapılırken kullanıcının beklemesini "
    "sağlayacak TEK bir kısa, doğal, samimi Türkçe cümle üretmek. Cümle, verilen bağlama "
    "(kullanıcının isteğine/konusuna) atıfta bulunsun ve ne yapıldığını ima etsin. SABİT bir "
    "kalıp kullanma; bağlama göre değiştir. SADECE bu tek cümleyi yaz, başka hiçbir şey ekleme.\n"
    + NUMBERS_AS_WORDS
)


def make_wait_filler(context: str) -> str:
    """Verilen bağlama göre kısa bir bekleme cümlesi üretir (üretilemezse boş döner).

    Düşünme (thinking) KAPALI (thinking_budget=0): model, muhakemesini çıktıya dökmeden
    doğrudan tek cümleyi ÇOK HIZLI üretsin (bekleme cümlesi anında iletilmeli).
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=context,
            config=types.GenerateContentConfig(
                system_instruction=_FILLER_SYSTEM,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return content_text(response.candidates[0].content)
    except Exception:
        return ""   # filler kritik değil; başarısız olursa akışı durdurma


def run_with_wait_filler(work, context: str):
    """`work`'ü (argümansız çağrılabilir ağır işlem: sorgu/üretim) HEMEN arka planda başlatır;
    bu SIRADA bağlama göre bir bekleme cümlesi üretip kullanıcıya iletir; sonra work sonucunu
    döndürür. Böylece sorgu, filler üretimini BEKLEMEDEN — onunla eş zamanlı — başlamış olur.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work)          # ağır işlem HEMEN başlar (filler'ı beklemez)
        filler = make_wait_filler(context)  # sorgu sürerken eş zamanlı üretilir
        if filler:
            print(f"\nAsistan: {filler}")
        return future.result()              # işlem sonucunu döndür (hata olursa yayılır)
