"""Bounded Gemini market screening for the Alpha Edge scanner.

Gemini ranks live market feature packets; deterministic candidate validation still
controls whether a Telegram signal can be emitted. No trading or order execution.
"""
import json
import math
import os
import re
import urllib.request

DEFAULT_MODEL = "gemini-2.5-flash-lite"
MAX_PICKS = 6


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^\`\`\`(?:json)?\\s*|\\s*\`\`\`$", "", text, flags=re.IGNORECASE)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        value = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


def normalize_picks(raw, packets, model=DEFAULT_MODEL):
    allowed = {str(p.get("symbol", "")).upper() for p in packets}
    cleaned = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        direction = str(item.get("direction", "")).strip().upper()
        if symbol not in allowed or direction not in {"LONG", "SHORT"}:
            continue
        try:
            score = float(item.get("score", 0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        score = max(0.0, min(100.0, score))
        cleaned[symbol] = {
            "direction": direction,
            "score": score,
            "reason": str(item.get("reason", ""))[:240],
            "model": model,
        }
        if len(cleaned) >= MAX_PICKS:
            break
    return cleaned


def screen_market_packets(packets, api_key=None, model=None, opener=None):
    """Return validated symbol picks; return {} on missing key/API/schema failure."""
    key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
    if not key or not packets:
        return {}
    model = (model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL).strip()
    compact = []
    for p in packets[:40]:
        compact.append({
            k: p.get(k) for k in (
                "symbol", "price", "chg_3", "chg_12", "chg_24", "atr_pct",
                "rsi", "volume_ratio", "ema20_50_pct", "range_pos",
                "last_body_pct", "turnover", "liquidity_rank"
            ) if k in p
        })
    prompt = (
        "You are the primary quantitative screener for live USDT perpetual futures, "
        "targeting 5m execution with 15m context. Evaluate the supplied current feature table. "
        "Look for LONG entries near a practical local bottom and SHORT entries near a practical local top; "
        "prefer reversal/exhaustion, pullback location, participation and liquid markets; reject chasing "
        "and contradictory evidence. Rank up to 6 best relative candidates even if none is perfect, "
        "but never invent symbols or data. This is candidate discovery only; downstream code applies "
        "independent timing, price geometry and risk gates. Return ONLY a JSON array with objects "
        '{"symbol":"XXXUSDT","direction":"LONG|SHORT","score":0-100,"reason":"brief evidence"}. '
        "Use only symbols in this table. Table: " + json.dumps(compact, separators=(",", ":"))
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1200, "responseMimeType": "application/json"},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        send = opener or urllib.request.urlopen
        with send(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = "\n".join(
            part.get("text", "")
            for candidate in payload.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
            if isinstance(part, dict) and part.get("text")
        )
        return normalize_picks(_extract_json(text), packets, model)
    except Exception as exc:
        # Log only error class; never print the API key or request headers.
        print(f"GEMINI_MARKET_SCREEN_UNAVAILABLE error={type(exc).__name__}")
        return {}
