"""Ortak Gemini istemcisi ve model ayarları."""

import os

from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=API_KEY)

# gemini-2.5-flash: implicit context caching indirimi (cache'lenen girdi token'ında ~%90) bu
# modelde geçerli ve VARSAYILAN AÇIK — tekrar eden system+tool prefix'i otomatik ucuzlar.
# NOT: 2.5 düşünmeyi thinking_BUDGET (token) ile kontrol eder; 3.x'in thinking_LEVEL'i değil.
MODEL = "gemini-2.5-flash"   # istersen "gemini-3.6-flash", "gemini-2.5-pro", "gemini-2.0-flash"
