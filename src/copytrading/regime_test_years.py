"""Regime test on 8.75 YEARS of BTC & ETH (2018-01 → 2026-09, Binance 4h candles).
There are no copy-trader signals that far back, so we use a simple, standard signal (20-bar breakout, both directions)
and our exact exits. Compare: 1 base · 5 scale-out · 6 stop-and-reverse · 7 REGIME. Rules fixed in advance (regime.py)."""
import numpy as np, pandas as pd
import regime as RG
H = "/home/claude/history_dl/"
SLIP, FEE = 0.001, 0.00045
BREAK, ATR_N, STOP_X, TP_R, BE_R, TRAIL_START, TRAIL_R, MAX_BARS = 20, 14, 1.5, 3, 1, 2, 1, 42

def atr(df):
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_N).mean()

def run(df, lab, variant):
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    A = atr(df).values; hi20 = df.high.rolling(BREAK).max().shift(1).values; lo20 = df.low.rolling(BREAK).min().shift(1).values
    reg = lab.regime.reindex(df.index).ffill().shift(1).values; side = lab.side.reindex(df.index).ffill().shift(1).values   # known before the bar
    trades, i = [], BREAK + ATR_N + 1
    pending_rev = None
    while i < len(c) - 1:
        if pending_rev is not None: d, size, style, allow_rev, i0 = pending_rev; pending_rev = None
        else:
            d = 1 if c[i] > hi20[i] else (-1 if c[i] < lo20[i] else 0)
            if d == 0 or np.isnan(A[i]): i += 1; continue
            size, style, allow_rev = 1.0, ("scale" if variant == "5" else "normal"), variant == "6"
            if variant == "7":
                rg = reg[i] if isinstance(reg[i], str) else None
                take, size, ex, allow_rev, _ = RG.decide(rg, int(side[i]) if not np.isnan(side[i]) else 0, d)
                if not take: i += 1; continue
                style = "scale" if ex == "scale_out" else "normal"
            i0 = i + 1
        e = o[i0] * (1 + d * SLIP); sd = max(STOP_X * A[i0 - 1] / e, 0.004)
        stop = e * (1 - d * sd); tp = e * (1 + d * TP_R * sd); best = e; part, frac = 0.0, 1.0; exit_px = None; stopped = False
        for j in range(i0, min(i0 + MAX_BARS, len(c))):
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                exit_px = min(stop, o[j]) if d == 1 else max(stop, o[j]); stopped = (stop - e) * d < 0; break
            if (d == 1 and h[j] >= tp) or (d == -1 and l[j] <= tp): exit_px = tp; break
            best = max(best, h[j]) if d == 1 else min(best, l[j]); g = d * (best / e - 1) / sd
            if style == "scale" and frac == 1.0 and g >= 1: part = 0.5 * (sd - 2 * FEE - 2 * SLIP); frac = 0.5
            if g >= BE_R: stop = max(stop, e * (1 + 2 * FEE)) if d == 1 else min(stop, e * (1 - 2 * FEE))
            if g >= TRAIL_START:
                t_ = best * (1 - d * TRAIL_R * sd); stop = max(stop, t_) if d == 1 else min(stop, t_)
        if exit_px is None: j = min(i0 + MAX_BARS, len(c)) - 1; exit_px = c[j]
        ret = d * (exit_px * (1 - d * SLIP) / e - 1) - 2 * FEE
        R = (part + frac * ret) / sd * size
        trades.append({"t": df.index[i0], "R": R, "size": size})
        i = j + 1
        if stopped and allow_rev and i < len(c) - 1 and not getattr(run, "_in_rev", False):
            pending_rev = (-d, size, "normal", False, i)       # flip once, entering next bar
    return pd.DataFrame(trades)

PERIODS = [("2018 crash/bear", "2018-01-01", "2019-01-01"), ("2019 recovery", "2019-01-01", "2020-01-01"),
           ("2020-21 boom", "2020-01-01", "2022-01-01"), ("2022 crash", "2022-01-01", "2023-01-01"),
           ("2023-24 recovery", "2023-01-01", "2025-01-01"), ("2025-26", "2025-01-01", "2026-10-01")]
btc = pd.read_pickle(H + "BTCUSDT_4h.pkl"); eth = pd.read_pickle(H + "ETHUSDT_4h.pkl")
LAB = RG.label_series(btc)
print("Time spent in each market type (BTC):", (LAB.regime.value_counts(normalize=True) * 100).round(0).to_dict(), "%")
names = {"1": "1 Base (all trades)", "5": "5 Scale out", "6": "6 Stop-and-reverse", "7": "7 REGIME (adapts)"}
allres = {}
for v in names:
    T = pd.concat([run(btc, LAB, v).assign(coin="BTC"), run(eth, LAB, v).assign(coin="ETH")]).sort_values("t")
    allres[v] = T
rows = []
for v, T in allres.items():
    r = {"version": names[v], "trades": len(T), "win %": f"{(T.R > 0).mean():.0%}", "total R": round(T.R.sum(), 1)}
    eq = 85 * np.cumprod(1 + 0.01 * T.R.values); r["$85 → (1% risk)"] = f"${eq[-1]:,.0f}"
    r["worst drop"] = f"{(eq / np.maximum.accumulate(eq) - 1).min():.0%}"
    for name, a, b in PERIODS:
        r[name] = round(T[(T.t >= a) & (T.t < b)].R.sum(), 1)
    rows.append(r)
pd.set_option("display.width", 300)
R = pd.DataFrame(rows).set_index("version")
print("\nTotal R by period (R = profit in units of risk; positive = made money):")
print(R.to_string())
best = {name: R[name].idxmax() for name, _, _ in PERIODS}
print("\nBest version per period:", best)
print("Regime beat base in", sum(R.loc[names["7"], n] > R.loc[names["1"], n] for n, _, _ in PERIODS), "of", len(PERIODS), "periods")
print("YEARS TEST DONE")
