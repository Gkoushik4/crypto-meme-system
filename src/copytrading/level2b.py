"""LEVEL 2b — experienced, skilled traders + trade check + slow-down for struggling traders.
Part A (3 periods, account level): copy the top-10 skilled traders; compare WITH vs WITHOUT the slow-down rule.
Part B (last 90 days, trade by trade): copy their real trades; compare base / +trade check / +slow-down / +both.
All thresholds fixed in advance."""
import os, sys, time, pickle, requests
import numpy as np, pandas as pd
from metrics import series
import veterans as V

D = "/home/claude/copytest/"
NOW = V.NOW
port = V.port
COST_M = 0.01
HALF_DD, PAUSE_DD, LOSS_STREAK, RESUME_GAIN = 0.05, 0.10, 3, 0.02

def pick(cut, n=10):
    cards = []
    for a, p in port.items():
        m, start = V.monthly(p, cut)
        if m is None: continue
        c = V.card(m, start, cut)
        if c is None or not V.is_skilled(c): continue
        c["trader"] = a; cards.append(c)
    d = pd.DataFrame(cards)
    return d.nlargest(n, "t_stat") if len(d) else d

def path(p, a, b):
    """Trader's cumulative copy return path between a and b (profit-based, relative to value at a)."""
    av, pnl = series(p["av"]), series(p["pnl"])
    v0 = np.interp(a.timestamp(), [x.timestamp() for x in av.index], av.values)
    seg = pnl[(pnl.index > a) & (pnl.index <= b)]
    p0 = np.interp(a.timestamp(), [x.timestamp() for x in pnl.index], pnl.values)
    if v0 < 50 or len(seg) == 0: return None
    return ((seg - p0) / v0).clip(lower=-1)

def copy_account(r, slowdown):
    """Our result copying one trader along their return path r, with optional slow-down rule."""
    eq, peak, w, paused_at, last_r, last_t = 1.0, 1.0, 1.0, None, 0.0, None
    for t, cum in r.items():
        step = cum - last_r; last_r = cum
        days = (t - last_t).days if last_t is not None else 0; last_t = t
        if w > 0:
            eq *= (1 + w * step) * (1 - w * COST_M * days / 30)
        if slowdown:
            peak = max(peak, eq); dd = eq / peak - 1
            if w > 0 and dd <= -PAUSE_DD:
                w, paused_at = 0.0, cum
            elif w == 1.0 and dd <= -HALF_DD:
                w = 0.5
            elif w == 0.0 and cum >= paused_at + RESUME_GAIN:
                w, peak = 0.5, eq
            elif w == 0.5 and dd > -0.02:
                w = 1.0
        if eq <= 0: return -1.0
    return eq - 1

def part_a():
    print("=" * 30, "PART A: skilled veterans, 3 periods, with vs without slow-down", "=" * 30)
    rows = []
    for k, cut in enumerate([NOW - pd.Timedelta(days=270), NOW - pd.Timedelta(days=180), NOW - pd.Timedelta(days=90)]):
        end = cut + pd.Timedelta(days=90)
        sk = pick(cut)
        res = []
        for a in sk.trader:
            r = path(port[a], cut, end)
            if r is None: continue
            res.append({"trader": a[:10], "no_slowdown": copy_account(r, False), "with_slowdown": copy_account(r, True)})
        R = pd.DataFrame(res)
        if len(R) == 0:
            print(f"Period {k+1}: no skilled traders"); continue
        print(f"\nPeriod {k+1}: pick up to {cut.date()}, copy {cut.date()}→{end.date()}  —  {len(R)} skilled traders")
        for col in ("no_slowdown", "with_slowdown"):
            v = R[col]
            print(f"  {col:14} $100 split → ${100 * (1 + v).mean():6.2f}  median {v.median():+6.1%}  made money {(v > 0).mean():4.0%}  "
                  f"worst {v.min():+.0%}")
        rows.append({"period": k + 1, "n": len(R), "no_slowdown": R.no_slowdown.mean(), "with_slowdown": R.with_slowdown.mean()})
    return pd.DataFrame(rows)

if __name__ == "__main__":
    A = part_a()
    print("\nSUMMARY A (average 90-day copy return):"); print(A.round(3).to_string(index=False))
