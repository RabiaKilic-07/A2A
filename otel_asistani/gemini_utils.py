"""Gemini içerik/metin yardımcıları."""

from typing import Optional

from google.genai import types


def user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def content_text(content) -> str:
    # "thought" (düşünme/muhakeme) parçalarını ATLA — bunlar kullanıcıya gösterilmemeli.
    parts = getattr(content, "parts", None) or []
    out = [p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)]
    return " ".join(out).strip()


def last_model_question(messages: list) -> Optional[str]:
    """Verilen mesaj thread'indeki son model (asistan) metnini döndürür."""
    for c in reversed(messages):
        if getattr(c, "role", None) == "model":
            t = content_text(c)
            if t:
                return t
    return None
