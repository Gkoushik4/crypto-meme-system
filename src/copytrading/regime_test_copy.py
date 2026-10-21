"""Regime test on the skilled traders' real trades (same signals as the Level 3 retest).
Compares: 1 base · 5 scale-out · 6 stop-and-reverse · 7 REGIME (rules from regime.py, fixed in advance)."""
import os, time, requests, numpy as np, pandas as pd
import regime as RG
src = open("flip_test.py").read(); src = src[:src.index("rows = {m: [] for m")]
exec(compile(src, "flip", "exec"))           # loads signals (sig, MAIN), candles, and walk()

now = int(time.time() * 1000)
d = requests.post("https://api.hyperliquid.xyz/info", json={"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "4h",
                  "startTime": now - 800 * 86400000, "endTime": now}}, timeout=30).json()
b4 = pd.DataFrame({"open": [float(x["o"]) for x in d], "high": [float(x["h"]) for x in d], "low": [float(x["l"]) for x in d],
                   "close": [float(x["c"]) for x in d]}, index=pd.to_datetime([x["t"] for x in d], unit="ms"))
LAB = RG.label_series(b4)

res = {k: [] for k in ("1 Copy every trade", "5 Scale out", "6 Stop-and-reverse", "7 REGIME (adapts)")}
regimes = []
for _, s in sig[sig.trader.isin(MAIN)].iterrows():
    b = walk(s.coin, s.dir, s.t, s.px, "base")
    if b is None: continue
    res["1 Copy every trade"].append(b["R"])
    h = walk(s.coin, s.dir, s.t, s.px, "scale"); res["5 Scale out"].append(h["R"] if h else 0)
    r = b["R"]
    if b["stopped"]:
        rv = walk(s.coin, -s.dir, b["t"], b["px"], "base"); r += rv["R"] if rv else 0
    res["6 Stop-and-reverse"].append(r)
    reg, side = RG.regime_at(LAB, s.t); regimes.append(reg)
    take, size, ex, rev, why = RG.decide(reg, side, s.dir)
    if not take: res["7 REGIME (adapts)"].append(0.0); continue
    x = walk(s.coin, s.dir, s.t, s.px, "scale" if ex == "scale_out" else "base")
    rr = x["R"] if x else 0
    if rev and x and x["stopped"]:
        rv = walk(s.coin, -s.dir, x["t"], x["px"], "base"); rr += rv["R"] if rv else 0
    res["7 REGIME (adapts)"].append(rr * size)
out = {}
for k, v in res.items():
    v = np.array(v); taken = v[v != 0] if k.startswith("7") else v
    out[k] = {"trades taken": len(taken), "win %": f"{(taken > 0).mean():.0%}" if len(taken) else "-", "total R": f"{v.sum():+.1f}",
              "$85 ->": f"${85 * np.prod(1 + 0.01 * v):.2f}", "worst trade R": f"{v.min():+.2f}" if len(v) else "-"}
print(pd.DataFrame(out).T.to_string())
print("Market regime when trades came in:", pd.Series(regimes).value_counts().to_dict())
print("REGIME TEST DONE")
