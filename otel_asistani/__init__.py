"""
Otel multi-agent demo — Google Gemini sürümü.

Yapı:
  Orchestrator (router)  ──►  reservation subagent  (tools: check_availability, complete_reservation)
                         ──►  hotel_info (RAG stub, hafızalı)
                         ──►  complaint subagent
                         ──►  chat (genel sohbet / yedek akış)

Öne çıkan garantiler:
  * check_availability 6 alanı KADEMELİ toplar; eksikleri kod (missing_fields) bilir, model değil.
  * complete_reservation, müsaitliğin TAM O PARAMETRELER için doğrulandığını fingerprint ile KODLA garanti eder.
  * Router "sticky": rezervasyon sürerken kısa cevaplar rezervasyona döner; kullanıcı konu değiştirirse hapsolmaz.

Kurulum:
  pip install google-genai pydantic
  PowerShell:  $env:GEMINI_API_KEY="..."
  python main.py

Gemini anahtarını https://aistudio.google.com/app/apikey adresinden alabilirsin.
hotel_backend (envanter), hotel_info_db (bilgi) ve run_complaint_subagent birer MOCK/STUB'dır —
gerçek veritabanı/servis ile değiştir.

Modüller:
  config             Gemini istemcisi + model ayarı
  reservation_state  ReservationState + doğrulama (sağlayıcıdan bağımsız)
  hotel_backend      Oda envanteri MOCK'u (data/rooms.json)
  hotel_info_db      Otel bilgi tabanı MOCK'u (data/hotel_info.json)
  reservation_tools  Tool tanımları + handler'lar (kritik garantiler)
  gemini_utils       Gemini içerik/metin yardımcıları
  prompt_rules       Ortak prompt kuralları
  wait_filler        TTS bekleme cümlesi üretimi (eş zamanlı)
  session            Session state + "yarım rezervasyon" nudge'ları
  agents/            router, reservation, hotel_info, complaint, chat
  orchestrator       Tur yönetimi (router kararına göre yönlendirme)
  cli                Basit konsol döngüsü
"""
