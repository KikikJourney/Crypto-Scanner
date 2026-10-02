"""Telegram formatting for the unified Alpha Edge Council."""
from alpha_edge_engine import format_price

def format_action(row):
    return "\n".join([
        f"🏛️ ZORATHVAEL ALPHA EDGE | {row.get('direction','')} {row.get('symbol','')}",
        "",
        "ENTRY CALIBRATION",
        f"Entry Zone: {format_price(row.get('entry_zone_low'))} – {format_price(row.get('entry_zone_high'))}",
        f"Calibrated Entry: {format_price(row.get('entry'))}",
        f"Pullback Timing: {row.get('timing','')}/100",
        f"Calibration: {row.get('calibration','')}",
        "",
        "EXECUTION GEOMETRY",
        f"SL: {format_price(row.get('stop'))} (-10% margin)",
        f"TP1: {format_price(row.get('tp1'))} (+30% margin)",
        f"TP2: {format_price(row.get('tp2'))} (+60% margin)",
        f"TP3: {format_price(row.get('tp3'))} (+120% margin)",
        f"Margin: {row.get('geometry',{}).get('margin_usdt',10)} USDT | Leverage: {row.get('geometry',{}).get('leverage',20)}x",
        "",
        "EDGE CONTEXT",
        f"Quality: {row.get('quality','')}/100",
        f"Regime: {row.get('regime',{}).get('type','')}",
        f"Liquidity sweep: {row.get('liquidity',{}).get('sweep','')}",
        f"Flow delta: {row.get('flow',{}).get('delta','')}",
        f"Displacement: {row.get('flow',{}).get('impulse','')}",
        f"Exhaustion: {row.get('flow',{}).get('exhaustion','')}",
        f"Open Interest: {row.get('external',{}).get('open_interest','')}",
        f"Funding: {row.get('external',{}).get('funding','')}",
        f"Crowding: {row.get('external',{}).get('crowding','')}",
        f"MTF alignment: {row.get('mtf_score','')}/3",
        "",
        "Calibration determines WHERE/WHEN. Geometry determines SL/TP."
    ])

def send_message(text, token=None, chat_id=None):
    from alpha_edge_engine import SESSION
    import os
    token=token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id=chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:return False,"Telegram credentials not configured"
    r=SESSION.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat_id,"text":text},timeout=15)
    r.raise_for_status()
    return True,"sent"
