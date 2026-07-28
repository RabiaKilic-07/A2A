"""Ham (raw) token loglama — token maliyeti teşhisi için.

VARSAYILAN: her LLM çağrısı için yalnızca hangi ajan olduğunu (başlık) ve
usage_metadata'dan GERÇEK token kırılımını (GİRDİ/ÇIKTI/düşünce/cache/TOPLAM) basar.
System prompt ve mesaj içerikleri BASILMAZ.

Full dökümü (system + tüm geçmiş/contents + tool şemaları + çıktı metni) görmek için:
    OTEL_RAW_LOG_PROMPTS=1
Tüm loglamayı kapatmak için: OTEL_RAW_LOG=0

Loglar session.raw_log tamponuna yazılır; cli.py her turun SONUNDA, normal konuşma
mesajının hemen altına '----' ayıracıyla basar.

Karakter tabanlı (~tok) değerler (full dökümde) KABA tahmindir; GERÇEK sayılar
'TOKEN' satırındaki usage_metadata değerleridir.
"""

import json
import os

_ENABLED = os.environ.get("OTEL_RAW_LOG", "1").lower() not in {"0", "false", "no", "off"}
_MAXLEN = int(os.environ.get("OTEL_RAW_LOG_MAXLEN", "4000"))   # tek parçada gösterilecek azami krk
# Varsayılan: SADECE token bilgisi (system prompt + içerik dökümü BASILMAZ).
# Full dökümü (system + contents + tools + çıktı metni) görmek için: OTEL_RAW_LOG_PROMPTS=1
_SHOW_PROMPTS = os.environ.get("OTEL_RAW_LOG_PROMPTS", "0").lower() in {"1", "true", "yes", "on"}

_TAGS = {
    "function_response": "TOOL-SONUCU",
    "function_call":     "TOOL-ÇAĞRISI",
    "thought":           "düşünce",
    "text":              "metin",
}


def _approx_tok(n_chars: int) -> int:
    return max(1, round(n_chars / 4))


def _json(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def _indent(text: str, n: int = 6) -> str:
    prefix = " " * n
    if len(text) > _MAXLEN:
        text = text[:_MAXLEN] + f"\n... [+{len(text) - _MAXLEN} krk kesildi -- tümü için OTEL_RAW_LOG_MAXLEN artır]"
    return "\n".join(prefix + ln for ln in text.split("\n"))


def _fmt_parts(content):
    """Bir Content'in (veya düz string'in) parçalarını [(tür, metin), ...] listesine çevirir."""
    parts = getattr(content, "parts", None)
    if parts is None:                                   # düz string (ör. router user_text)
        return [("text", str(content))]
    out = []
    for p in parts:
        fc = getattr(p, "function_call", None)
        fr = getattr(p, "function_response", None)
        if fc:
            out.append(("function_call", f"{fc.name}({_json(dict(fc.args or {}))})"))
        elif fr:
            out.append(("function_response", f"{fr.name} -> {_json(dict(fr.response or {}))}"))
        elif getattr(p, "text", None) is not None:
            kind = "thought" if getattr(p, "thought", False) else "text"
            out.append((kind, p.text))
    return out


def _iter_contents(contents):
    """contents (str | list[Content]) → [(role, [(tür, metin), ...]), ...]"""
    if contents is None:
        return []
    if isinstance(contents, str):
        return [("user", [("text", contents)])]
    return [(getattr(c, "role", "?"), _fmt_parts(c)) for c in contents]


def _render_input(system, contents, tools, sys_seen):
    lines = ["---- GİRDİ (modele giden) ----"]

    # 1) SYSTEM PROMPT — her çağrıda TEKRAR gönderilir (sabit maliyet). Aynıysa tekrar basmayız.
    if system is not None:
        sc = len(system)
        if system in sys_seen:
            lines.append(f"system    : {sc} krk (~{_approx_tok(sc)} tok) — [bu turdaki önceki çağrıyla AYNI, tekrar gitti]")
        else:
            sys_seen.add(system)
            lines.append(f"system    : {sc} krk (~{_approx_tok(sc)} tok)")
            lines.append(_indent(system))

    # 2) CONTENTS / GEÇMİŞ — asıl şişme burada olur (özellikle TOOL-SONUCU JSON'ları).
    msgs = _iter_contents(contents)
    total = 0
    lines.append(f"contents  : {len(msgs)} mesaj (aşağıda parça parça)")
    for i, (role, parts) in enumerate(msgs):
        for kind, text in parts:
            c = len(text)
            total += c
            tag = _TAGS.get(kind, kind)
            lines.append(f"  [{i}] role={role:5} {tag:12} {c} krk (~{_approx_tok(c)} tok)")
            lines.append(_indent(text))
    lines.append(f"  -> GEÇMİŞ TOPLAM: {total} krk (~{_approx_tok(total)} tok)")

    # 3) TOOLS — şema da her çağrıda TEKRAR gönderilir (sabit maliyet).
    if tools:
        decls, raw_chars = [], 0
        for t in tools:
            for d in getattr(t, "function_declarations", None) or []:
                props = getattr(getattr(d, "parameters", None), "properties", None) or {}
                decls.append(f"{d.name}({', '.join(props.keys())})")
            try:
                raw_chars += len(_json(t.model_dump(exclude_none=True)))
            except Exception:
                pass
        lines.append(f"tools     : {len(decls)} fonksiyon, şema ~{raw_chars} krk (~{_approx_tok(raw_chars)} tok) — HER çağrıda tekrar gider")
        for d in decls:
            lines.append(f"  - {d}")
    else:
        lines.append("tools     : yok")
    return lines


def _render_output(response):
    lines = ["---- ÇIKTI (modelden gelen) ----"]
    try:
        for kind, text in _fmt_parts(response.candidates[0].content):
            c = len(text)
            lines.append(f"  {_TAGS.get(kind, kind):12} {c} krk (~{_approx_tok(c)} tok)")
            lines.append(_indent(text, 4))
    except Exception as e:
        lines.append(f"  (çıktı okunamadı: {type(e).__name__}: {e})")
    return lines


def _render_tokens(response):
    u = getattr(response, "usage_metadata", None)
    if not u:
        return ["---- TOKEN (gerçek, usage_metadata) ----", "  (usage yok)"]
    p = getattr(u, "prompt_token_count", None) or 0
    o = getattr(u, "candidates_token_count", None) or 0
    th = getattr(u, "thoughts_token_count", None) or 0
    cache = getattr(u, "cached_content_token_count", None) or 0
    tot = getattr(u, "total_token_count", None) or 0
    line = f"  GİRDİ(prompt)={p}   ÇIKTI(candidates)={o}"
    if th:
        line += f"   düşünce={th}"
    if cache:
        line += f"   cache={cache}"
    line += f"   ->  TOPLAM={tot}"
    return ["---- TOKEN (gerçek, usage_metadata) ----", line]


def log_llm_call(session, label, *, system=None, contents=None, tools=None,
                 response=None, model=None, note=None):
    """Bir LLM çağrısının ham girdi/çıktısını session.raw_log tamponuna ekler."""
    if not _ENABLED or session is None:
        return
    sys_seen = session.__dict__.setdefault("_raw_sys_seen", set())
    head = f"====== [RAW] {label}"
    if model:
        head += f"  |  model={model}"
    if note:
        head += f"  |  {note}"
    block = [head]
    # Varsayılan: SADECE token. Full prompt/içerik dökümü yalnızca OTEL_RAW_LOG_PROMPTS=1 iken.
    if _SHOW_PROMPTS:
        block += _render_input(system, contents, tools, sys_seen)
        if response is not None:
            block += _render_output(response)
    if response is not None:
        block += _render_tokens(response)
    session.raw_log.append("\n".join(block))
