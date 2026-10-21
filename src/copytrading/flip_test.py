"""Check 'flip' ideas on the skilled traders' real trades (same signals as the Level 3 retest).
base = our exits | reverse = stop-and-reverse once | quick = take full profit at +1R | scale = sell half at +1R, rest rides (BE stop, trail, 3R)."""
import os, numpy as np, pandas as pd
src = open("level3_backtest.py").read(); src = src[:src.index("# ---------- trade check")]
exec(compile(src, "bt", "exec"))
SL, FE = L.SLIP, L.FEE
def walk(coin, d, t0, px, mode):
    c = L.candles[coin]; sd = max(1.5 * L.atr_pct(coin, t0), 0.004)
    if np.isnan(sd): return None
    e = px * (1 + d * SL); stop = e * (1 - d * sd); best = e; half_done = False; booked = 0.0; left = 1.0
    tp = e * (1 + d * (1 if mode == "quick" else 3) * sd)
    path = c[(c.index > t0.floor("h")) & (c.index <= t0 + pd.Timedelta(days=7))]
    for t, b in path.iterrows():
        if (d == 1 and b.low <= stop) or (d == -1 and b.high >= stop):
            x = (min(stop, b.open) if d == 1 else max(stop, b.open)) * (1 - d * SL)
            r = booked + left * (d * (x / e - 1) - 2 * FE)
            return {"R": r / sd, "t": t, "px": x, "stopped": (stop - e) * d < 0}
        if (d == 1 and b.high >= tp) or (d == -1 and b.low <= tp):
            r = booked + left * (d * (tp * (1 - d * SL) / e - 1) - 2 * FE)
            return {"R": r / sd, "t": t, "px": tp, "stopped": False}
        best = max(best, b.high) if d == 1 else min(best, b.low)
        g = d * (best / e - 1) / sd
        if mode == "scale" and not half_done and g >= 1:
            booked += 0.5 * (sd - 2 * FE); left = 0.5; half_done = True
        if g >= 1: stop = max(stop, e * (1 + 2 * FE)) if d == 1 else min(stop, e * (1 - 2 * FE))
        if g >= 2:
            tr = best * (1 - d * sd); stop = max(stop, tr) if d == 1 else min(stop, tr)
    if len(path) == 0: return None
    x = path.close.iloc[-1] * (1 - d * SL)
    return {"R": (booked + left * (d * (x / e - 1) - 2 * FE)) / sd, "t": path.index[-1], "px": x, "stopped": False}

rows = {m: [] for m in ("base (our exits)", "stop-and-reverse", "quick flip (all out at +1R)", "scale out (half at +1R)")}
for _, s in sig[sig.trader.isin(MAIN)].iterrows():
    b = walk(s.coin, s.dir, s.t, s.px, "base")
    if b is None: continue
    rows["base (our exits)"].append(b["R"])
    r = b["R"]
    if b["stopped"]:
        rv = walk(s.coin, -s.dir, b["t"], b["px"], "base")
        if rv: r += rv["R"]
    rows["stop-and-reverse"].append(r)
    q = walk(s.coin, s.dir, s.t, s.px, "quick"); rows["quick flip (all out at +1R)"].append(q["R"] if q else 0)
    h = walk(s.coin, s.dir, s.t, s.px, "scale"); rows["scale out (half at +1R)"].append(h["R"] if h else 0)
out = {}
for k, v in rows.items():
    v = np.array(v); eq = 85 * np.prod(1 + 0.01 * v) if len(v) else 85
    out[k] = {"trades": len(v), "win %": f"{(v > 0).mean():.0%}" if len(v) else "-", "avg R": f"{v.mean():+.2f}" if len(v) else "-",
              "total R": f"{v.sum():+.1f}", "$85 ->": f"${eq:.2f}"}
print(pd.DataFrame(out).T.to_string()); print("FLIP DONE")
