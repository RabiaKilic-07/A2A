"""Ortak Gemini istemcisi ve model ayarları."""

import os

from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=API_KEY)

MODEL = "gemini-3.6-flash"   # istersen "gemini-2.5-pro" ya da "gemini-2.0-flash"
