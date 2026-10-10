"""Production entrypoint for the unified Alpha Edge Council.

All production scanning is delegated to alpha_edge_engine.
Legacy engines are not part of the production path.
"""
from alpha_edge_engine import scan, notify, VERSION
import json
import os
from pathlib import Path

if __name__ == "__main__":
    result = scan()
    Path("scanner_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if os.getenv("DEFER_TELEGRAM", "0") == "1":
        print("TELEGRAM_DEFERRED_TO_DEDUP_STEP")
    else:
        notify(result)
