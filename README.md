# Otel Multi-Agent Asistanı (Gemini)

Google Gemini ile çalışan çok ajanlı otel asistanı demosu. Bir router (orchestrator),
kullanıcının her mesajını dört akıştan birine yönlendirir:

```
Orchestrator (router) --> reservation  (tools: check_availability, bed_options, complete_reservation)
                      --> hotel_info    (mock DB'den anahtar kelimeyle sorgu, simüle gecikme)
                      --> complaint     (şikayet/talep)
                      --> chat          (genel sohbet / yedek akış)
```

## Rezervasyon akışı

1. **Aşama 1 — `check_availability`:** gerekli bilgileri **TEK seferde** toplar → giriş tarihi, çıkış
   tarihi, kişi sayısı, oda türü (+ opsiyonel manzara tercihi ve çocuk bilgisi). Eksikse `incomplete`;
   tamsa `stage1_ok`. **Kişi sayımı kuralı:** 12 yaşından **büyük** herkes `total_guests`, 12 yaş ve
   **altı** ise `children_count` sayılır (asistan bunu kullanıcıya açıklar).
2. **Aşama 2 — `bed_options`:** yatak dizilişi değil, **yerleşim planları** sunar — grubu odalara nasıl
   yerleştirebileceğimizin seçenekleri: tek oda (gerekirse oda türü **yükseltilerek**) ya da grup
   **bölünerek** birden çok oda (ör. iki adet iki kişilik oda). Sorgu manzarayı **filtre almaz**;
   tercih edilen manzara **üstte**, diğerleri **altta** sıralanır.
3. **Aşama 3 — `complete_reservation`:** kullanıcı bir planı seçince, model planın `plan_id`'sini
   `arrangement` olarak verir. Çocuk bilgisi aşama-1'de alındığı için tüm bilgiler **özetlenip onay
   istenir** (`needs_confirmation`); kullanıcı açıkça onaylayınca (`confirmed=true`) rezervasyon kesinleşir.

## Öne çıkan kod garantileri
- **Aşama-1 zorunluluğu:** eksik 4 alanı model değil, kod (`stage1_missing`) bilir.
- **Değişiklikte geri dönüş:** aşama-1 alanlarından biri değişirse sunulan planlar
  `stage1_fingerprint` ile geçersizleşir → `bed_options` yeniden çalıştırılmalı (`secenekler_gecersiz`).
- **Uydurma seçim engeli:** seçilen plan (`arrangement`) güncel girdiler için üretilen planlar
  arasında yoksa rezervasyon reddedilir (`gecersiz_secim`) — plan, doğrulama sırasında yeniden üretilir.
- **Onay kapısı:** rezervasyon, önce özet gösterilip kullanıcı açıkça onaylamadan yapılmaz.
  `full_fingerprint` sayesinde model özeti atlayıp kendi kendine onaylayamaz; özet sonrası bir bilgi
  değişirse onay eskir ve özet yenilenir.

## Kurulum ve çalıştırma
```powershell
pip install -r requirements.txt
$env:GEMINI_API_KEY="..."   # https://aistudio.google.com/app/apikey
python main.py
```

## Dosya yapısı
```
main.py                       # Çalıştırma girişi
otel_asistani/
├── __init__.py               # Genel bakış / mimari notları
├── config.py                 # Gemini istemcisi + model ayarı
├── reservation_state.py      # ReservationState + AŞAMALI doğrulama (sağlayıcıdan bağımsız)
├── hotel_backend.py          # Mock envanter — data/rooms.json'u okur, yerleşim planları üretir
├── hotel_info_db.py          # Mock otel bilgi tabanı — data/hotel_info.json'u anahtar kelimeyle sorgular
├── data/
│   ├── rooms.json            # Mock veritabanı (oda konfigürasyonları)
│   └── hotel_info.json       # Mock otel bilgi tabanı (wifi, kahvaltı, saatler, ...)
├── reservation_tools.py      # 3 tool tanımı + handler'lar (kritik garantiler)
├── gemini_utils.py           # Gemini içerik/metin yardımcıları
├── prompt_rules.py           # Ortak prompt kuralları (ör. sayıları yazıyla yaz)
├── wait_filler.py            # TTS bekleme cümlesi üretimi (rezervasyonda bed_options öncesi)
├── session.py                # Session state + "yarım rezervasyon" nudge'ları
├── orchestrator.py           # Tur yönetimi (router kararına göre yönlendirme)
├── cli.py                    # Basit konsol döngüsü
└── agents/
    ├── router.py             # Sticky sınıflandırıcı (structured output)
    ├── reservation.py        # Rezervasyon subagent'ı (3 aşamalı, manuel tool döngüsü)
    ├── hotel_info.py         # Mock DB sorgusu + simüle DB gecikmesi (RAG yok)
    ├── complaint.py          # Şikayet subagent'ı
    └── chat.py               # Genel sohbet / yedek akış
```

## Mock veritabanı (`data/rooms.json`)
Her satır bir oda konfigürasyonudur: `room_type`, kapasite (`min_guests`/`max_guests`),
`view_type`, `price_per_night` ve `unavailable_dates` (dolu günler).
`bed_options`, tarih uygunluğu olan odalardan **yerleşim planları** üretir: her oda için grubu
almak üzere kaç oda gerektiğini (`ceil(total_guests / max_guests)`) hesaplar → tek oda veya çok
oda planı. Manzara/oda türü yalnızca sıralama tercihidir. Gerçek envanter/DB ile değiştirin.
```
