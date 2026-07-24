"""Otel bilgi tabanı — mock veritabanı (data/hotel_info.json'dan okunur).

hotel_info akışı otel sorularını buradan ANAHTAR KELİMEYLE sorgular (gerçek RAG/LLM YOK).
Eşleşme bulunamazsa 'Bilmiyorum.' döner. Gerçek bir veritabanı/servis ile değiştirilebilir.
"""

import json
from pathlib import Path

_DB_PATH = Path(__file__).with_name("data") / "hotel_info.json"


def _load() -> dict:
    with open(_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def lookup(question: str) -> str:
    """Soruyu anahtar kelimeyle mock DB'de arar.

    Sorunun içinde bir kaydın konu kelimelerinden biri geçiyorsa o kaydın 'Konu: bilgi'sini,
    hiçbir eşleşme yoksa 'Bilmiyorum.' döndürür.
    """
    q = question.casefold()
    for entry in _load().get("bilgiler", []):
        konu_words = [w for w in entry["konu"].casefold().split() if len(w) > 2]
        if any(word in q for word in konu_words):
            return f"{entry['konu']}: {entry['bilgi']}"
    return "Bilmiyorum."
