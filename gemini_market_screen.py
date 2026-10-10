"""Bounded Gemini market screening for the Alpha Edge scanner.

Gemini ranks live market feature packets; deterministic candidate validation still
controls whether a Telegram signal can be emitted. No trading or order execution.
"""
import json
import math
import os
import re
import urllib.request
import urllib.error

DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_PICKS = 6


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
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
    packet_by_symbol = {str(p.get("symbol", "")).upper(): p for p in packets}
    allowed = set(packet_by_symbol)
    cleaned = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        direction = str(item.get("direction", "")).strip().upper()
        if symbol not in allowed or direction not in {"LONG", "SHORT"}:
            continue
        packet = packet_by_symbol[symbol]
        readiness_key = f"{direction.lower()}_entry_ready"
        if readiness_key in packet and packet.get(readiness_key) is not True:
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
                "last_body_pct", "turnover", "liquidity_rank", "live_price",
                "long_entry_ready", "long_entry_timing", "long_entry_zone_low", "long_entry_zone_high",
                "short_entry_ready", "short_entry_timing", "short_entry_zone_low", "short_entry_zone_high"
            ) if k in p
        })
    prompt = (
        "You are the primary quantitative screener for live USDT perpetual futures, "
        "targeting 5m execution with 15m context. Evaluate the supplied current feature table. "
        "Look for LONG entries near a practical local bottom and SHORT entries near a practical local top; "
        "prefer reversal/exhaustion, pullback location, participation and liquid markets; reject chasing "
        "and contradictory evidence. HARD RULE: select a LONG only when long_entry_ready is true, and a "
        "SHORT only when short_entry_ready is true. These flags are deterministic live-price/pullback checks; "
        "never override them. Rank up to 6 of the ready candidates, or return an empty array if none is ready. "
        "Never invent symbols or data. Downstream code applies additional structure, quality and risk gates. "
        "Return ONLY a JSON array with objects "
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
    except urllib.error.HTTPError as exc:
        # Google API error bodies contain diagnostic status/message, not request headers.
        try:
            detail = exc.read().decode("utf-8", errors="replace").replace("\\n", " ")[:300]
        except Exception:
            detail = ""
        print(f"GEMINI_MARKET_SCREEN_UNAVAILABLE status={exc.code} detail={detail}")
        return {}
    except Exception as exc:
        # Never print the API key or request headers.
        print(f"GEMINI_MARKET_SCREEN_UNAVAILABLE error={type(exc).__name__}")
        return {}


def should_use_qwen_fallback(gemini_picks, gemini_only=False):
    """Keep production runtime lightweight when Gemini-only mode is enabled."""
    return not bool(gemini_picks) and not gemini_only
