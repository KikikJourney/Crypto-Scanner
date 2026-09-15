from pathlib import Path

p = Path("scanner.py")
s = p.read_text(encoding="utf-8")
old = '                if x.get("side")==buy_side or x.get("side","").lower()=="buy": buy += float(x.get("price",x[1]))*float(x.get("size",x[2]))\n                elif x.get("side")==sell_side or x.get("side","").lower()=="sell": sell += float(x.get("price",x[1]))*float(x.get("size",x[2]))'
new = '''                if isinstance(x, dict):\n                    side = str(x.get("side", ""))\n                    price = float(x.get("price", 0))\n                    size = float(x.get("size", 0))\n                else:\n                    side = str(x[4] if len(x) > 4 else x[3])\n                    price = float(x[1])\n                    size = float(x[2])\n                if side.lower() in (str(buy_side).lower(), "buy"):\n                    buy += price * size\n                elif side.lower() in (str(sell_side).lower(), "sell"):\n                    sell += price * size'''
if old in s:
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("v1.9 source guard applied")
else:
    print("v1.9 source already guarded")
