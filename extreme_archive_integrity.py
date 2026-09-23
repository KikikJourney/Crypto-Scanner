"""Integrity checks for persisted extreme-reversal research archives.

The validator is deliberately strict: malformed timestamps, non-crypto symbols,
duplicate IDs, non-positive prices, and future-dated observations are rejected.
No trading rule is changed here.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_MAX_FUTURE_MINUTES = 15


def _ts(value):
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _universe(path=Path("data/crypto_universe.csv")):
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {str(r.get("symbol", "")).upper() for r in csv.DictReader(f) if r.get("symbol")}


def _read(path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames or []


def validate(path, *, now=None, max_future_minutes=DEFAULT_MAX_FUTURE_MINUTES,
             universe=None, require_price=False):
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "rows": 0, "valid": True, "errors": []}

    rows, _ = _read(path)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    universe = _universe() if universe is None else {str(x).upper() for x in universe}
    errors = []
    ids = set()

    for index, row in enumerate(rows, start=2):
        ident = str(row.get("id", "")).strip()
        if not ident:
            errors.append(f"line {index}: missing id")
        elif ident in ids:
            errors.append(f"line {index}: duplicate id {ident}")
        else:
            ids.add(ident)

        symbol = str(row.get("symbol", "")).strip().upper()
        if universe and symbol not in universe:
            errors.append(f"line {index}: non-crypto or unknown symbol {symbol}")

        try:
            ts = _ts(row.get("timestamp", ""))
        except (TypeError, ValueError):
            errors.append(f"line {index}: invalid timestamp {row.get('timestamp')!r}")
            continue

        if ts > now + timedelta(minutes=max_future_minutes):
            errors.append(f"line {index}: future timestamp {ts.isoformat()}")

        if require_price:
            try:
                price = float(row.get("price", ""))
                if price <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"line {index}: invalid price {row.get('price')!r}")

    return {"path": str(path), "rows": len(rows), "valid": not errors, "errors": errors}


def sanitize(path, output=None, *, now=None, max_future_minutes=DEFAULT_MAX_FUTURE_MINUTES,
             universe=None, require_price=False):
    """Rewrite a research archive with only valid rows and return rejected rows.

    Rejected rows are returned to the caller so the workflow can archive them
    as a diagnostic artifact instead of silently discarding evidence.
    """
    path = Path(path)
    rows, fields = _read(path)
    now = now or datetime.now(timezone.utc)
    universe = _universe() if universe is None else {str(x).upper() for x in universe}
    kept, rejected = [], []

    for row in rows:
        ok = True
        if not str(row.get("id", "")).strip():
            ok = False
        symbol = str(row.get("symbol", "")).strip().upper()
        if universe and symbol not in universe:
            ok = False
        try:
            ts = _ts(row.get("timestamp", ""))
            if ts > now + timedelta(minutes=max_future_minutes):
                ok = False
        except (TypeError, ValueError):
            ok = False
        if require_price:
            try:
                if float(row.get("price", "")) <= 0:
                    ok = False
            except (TypeError, ValueError):
                ok = False
        if ok:
            kept.append(row)
        else:
            rejected.append(row)

    if output is None:
        output = path
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(kept)
    return kept, rejected


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()

    files = [
        ("data/extreme_market_snapshots.csv", True),
        ("data/extreme_reversal_forward_test.csv", False),
        ("data/actionable_forward_test.csv", False),
    ]
    failed = False
    quarantine = Path("data/quarantine")
    for path, price in files:
        if args.sanitize and Path(path).exists():
            _, rejected = sanitize(path, require_price=price)
            if rejected:
                quarantine.mkdir(parents=True, exist_ok=True)
                rejected_path = quarantine / (Path(path).stem + "_rejected.csv")
                with rejected_path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rejected[0]))
                    writer.writeheader()
                    writer.writerows(rejected)
                print(f"{path}: quarantined={len(rejected)} -> {rejected_path}")
        result = validate(path, require_price=price)
        print(f"{path}: rows={result['rows']} valid={result['valid']} errors={len(result['errors'])}")
        if result["errors"]:
            print("\n".join(result["errors"][:10]))
            failed = True
    raise SystemExit(1 if failed else 0)
