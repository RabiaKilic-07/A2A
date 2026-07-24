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
hotel_backend, run_rag ve run_complaint_subagent birer STUB'dır — gerçek envanter/RAG ile değiştir.

Modüller:
  config             Gemini istemcisi + model ayarı
  reservation_state  ReservationState + doğrulama (sağlayıcıdan bağımsız)
  hotel_backend      Envanter/DB STUB'ı
  reservation_tools  Tool tanımları + handler'lar (kritik garantiler)
  gemini_utils       Gemini içerik/metin yardımcıları
  session            Session state + "yarım rezervasyon" nudge'ları
  agents/            router, reservation, hotel_info, complaint, chat
  orchestrator       Tur yönetimi (router kararına göre yönlendirme)
  cli                Basit konsol döngüsü
"""
