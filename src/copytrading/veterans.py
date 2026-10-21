"""Experienced-trader test: pick 10 traders with long, consistent, statistically strong records using ONLY
history before a cut-off date, then measure what copying them earned over the next 90 days.
Repeated for 3 cut-off dates. Copy = their % return (minus ~1%/month copy costs)."""
import pickle
import numpy as np, pandas as pd
from metrics import series

D = "/home/claude/copytest/"
port = pickle.load(open(D + "portfolio.pkl", "rb"))
candles = pickle.load(open(D + "candles.pkl", "rb"))
COPY_COST_M = 0.01
NOW = pd.Timestamp.now("UTC").tz_localize(None)

def monthly(p, end):
    """30-day returns from first activity up to `end`, profit-based (deposits don't count)."""
    av, pnl = series(p["av"]), series(p["pnl"])
    act = av[av > 10]
    if len(act) == 0 or len(pnl) < 5:
        return None, None
    start = act.index[0]
    edges = pd.date_range(start, end, freq="30D")
    if len(edges) < 2:
        return None, start
    ts = np.array([x.timestamp() for x in pnl.index]); tv = np.array([x.timestamp() for x in av.index])
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        v0 = np.interp(a.timestamp(), tv, av.values)
        if v0 < 50:
            out.append(np.nan); continue
        out.append((np.interp(b.timestamp(), ts, pnl.values) - np.interp(a.timestamp(), ts, pnl.values)) / v0)
    return pd.Series(out, index=edges[1:]).clip(-1, 5), start

def forward(p, a, b):
    av, pnl = series(p["av"]), series(p["pnl"])
    if len(pnl) < 2 or pnl.index[-1] < b - pd.Timedelta(days=3):
        return np.nan
    v0 = np.interp(a.timestamp(), [x.timestamp() for x in av.index], av.values)
    if v0 < 50:
        return np.nan
    ts = [x.timestamp() for x in pnl.index]
    r = (np.interp(b.timestamp(), ts, pnl.values) - np.interp(a.timestamp(), ts, pnl.values)) / v0
    return max(-1.0, r - 3 * COPY_COST_M)

def card(m, start, cut):
    m = m.dropna()
    active = m[m != 0]
    if len(active) < 9 or (cut - start).days < 365:
        return None
    eq = (1 + m).cumprod(); dd = float((eq / eq.cummax() - 1).min())
    tot = m.sum(); best = m.max()
    half = len(m) // 2
    t = m.mean() / (m.std(ddof=1) / np.sqrt(len(m))) if m.std(ddof=1) > 0 else 0
    return {"months": len(m), "profitable_months": float((active > 0).mean()), "avg_month": m.mean(),
            "t_stat": t, "max_drawdown": dd, "best_month_share": best / tot if tot > 0 else np.inf,
            "both_halves_positive": m.iloc[:half].sum() > 0 and m.iloc[half:].sum() > 0}

RULES = dict(min_profitable_months=0.60, min_t=2.5, max_dd=-0.30, max_best_share=0.5)
def is_skilled(c):
    return (c["profitable_months"] >= RULES["min_profitable_months"] and c["t_stat"] >= RULES["min_t"]
            and c["max_drawdown"] >= RULES["max_dd"] and c["best_month_share"] <= RULES["max_best_share"]
            and c["both_halves_positive"])

if __name__ == '__main__':
    btc = candles[("BTC", "4h")].close if ("BTC", "4h") in candles else candles[("BTC", "1h")].close
    rows_all = []
    for k, cut in enumerate([NOW - pd.Timedelta(days=270), NOW - pd.Timedelta(days=180), NOW - pd.Timedelta(days=90)]):
        end = cut + pd.Timedelta(days=90)
        cards = []
        for a, p in port.items():
            m, start = monthly(p, cut)
            if m is None:
                continue
            c = card(m, start, cut)
            if c is None:
                continue
            c.update(trader=a, skilled=is_skilled(c), fwd=forward(p, cut, end))
            cards.append(c)
        d = pd.DataFrame(cards).dropna(subset=["fwd"])
        skilled = d[d.skilled].nlargest(10, "t_stat")
        lucky = d[(~d.skilled) & (d.avg_month > 0.10)].nlargest(10, "avg_month")   # big returns, failed the skill test
        def line(sub):
            if len(sub) == 0: return "  none"
            v = 100 * (1 + sub.fwd)
            return (f"{len(sub):3} traders | $100 split → ${v.mean():6.2f} | median {sub.fwd.median():+6.1%} | "
                    f"made money {(sub.fwd > 0).mean():4.0%} | lost 50%+ {(sub.fwd <= -0.5).mean():3.0%}")
        b = btc[(btc.index >= cut) & (btc.index <= end)]
        btc_r = b.iloc[-1] / b.iloc[0] - 1 if len(b) > 10 else np.nan
        print(f"\n=== Test {k + 1}: pick with history up to {cut.date()}, copy {cut.date()} → {end.date()} ===")
        print(f"Experienced traders (12+ months, 9+ active months): {len(d)};  passed the skill test: {int(d.skilled.sum())}")
        print("TOP 10 SKILLED     ", line(skilled))
        print("Big-return 'lucky' ", line(lucky))
        print("All experienced    ", line(d))
        print(f"Hold BTC            $100 → ${100 * (1 + btc_r):.2f}" if not np.isnan(btc_r) else "Hold BTC            (no price data this far back)")
        if len(skilled):
            print(skilled[["months", "profitable_months", "avg_month", "t_stat", "max_drawdown", "fwd"]]
                  .assign(trader=skilled.trader.str[:10]).round(3).to_string(index=False))
        rows_all.append({"test": k + 1, "skilled": skilled.fwd.mean() if len(skilled) else np.nan,
                         "lucky": lucky.fwd.mean() if len(lucky) else np.nan, "all": d.fwd.mean(), "btc": btc_r,
                         "n_skilled": len(skilled)})
    print("\n=== SUMMARY (average copy return over 90 days) ===")
    print(pd.DataFrame(rows_all).round(3).to_string(index=False))
