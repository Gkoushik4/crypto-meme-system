"""MARKET REGIME DETECTOR — rules FIXED 2026-10-20 before any test.
Labels the market from BTC 4-hour candles as TRENDING, CHOPPY or WILD, and says how to trade in each."""
import numpy as np, pandas as pd

SMA_BARS = 300          # 300 x 4h = 50 days
ER_BARS = 42            # 42 x 4h = 7 days (efficiency ratio window)
ER_TREND = 0.30         # >= 0.30 = price moved mostly in one direction
ATR_BARS, ATR_MED_BARS, WILD_X = 14, 540, 2.0   # swings > 2x the 90-day normal = WILD
CONFIRM = 2             # a new regime must hold for 2 bars (8 hours) before switching

PLAYBOOK = {
    "TRENDING": {"take": "all",        "size": 1.0, "exits": "normal",    "reverse": True},
    "CHOPPY":   {"take": "with_trend", "size": 0.5, "exits": "scale_out", "reverse": False},
    "WILD":     {"take": "none",       "size": 0.0, "exits": "normal",    "reverse": False},
}

def label_series(c4: pd.DataFrame) -> pd.DataFrame:
    """For every 4h bar: raw regime, confirmed regime, and the trend side (+1 above 50-day average, -1 below)."""
    c = c4.close; h, l = c4.high, c4.low
    sma = c.rolling(SMA_BARS, min_periods=SMA_BARS).mean()
    move = (c - c.shift(ER_BARS)).abs(); path = c.diff().abs().rolling(ER_BARS).sum()
    er = move / path
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_BARS).mean(); atr_med = atr.rolling(ATR_MED_BARS, min_periods=120).median()
    side = np.sign(c - sma)
    up7 = np.sign(c - c.shift(ER_BARS))
    raw = np.where(atr > WILD_X * atr_med, "WILD", np.where((er >= ER_TREND) & (side == up7), "TRENDING", "CHOPPY"))
    raw = pd.Series(raw, index=c4.index).where(sma.notna() & er.notna())
    conf, cur, run, prev = [], None, 0, None
    for r in raw:
        if r is None or (isinstance(r, float) and np.isnan(r)): conf.append(None); continue
        run = run + 1 if r == prev else 1; prev = r
        if cur is None or (r != cur and run >= CONFIRM): cur = r
        conf.append(cur)
    return pd.DataFrame({"raw": raw, "regime": conf, "side": side, "er": er, "vol_x": atr / atr_med}, index=c4.index)

def regime_at(lab: pd.DataFrame, t):
    """Regime known at time t (only finished bars: no peeking)."""
    x = lab[lab.index + pd.Timedelta(hours=4) <= pd.Timestamp(t)]
    x = x.dropna(subset=["regime"])
    if not len(x): return None, 0
    return x.regime.iloc[-1], int(x.side.iloc[-1])

def decide(regime, side, trade_dir):
    """Returns (take?, size multiplier, exit style, allow stop-and-reverse, reason)."""
    if regime is None: return True, 1.0, "normal", False, "regime unknown (not enough history) — normal rules"
    pb = PLAYBOOK[regime]
    if pb["take"] == "none": return False, 0, None, False, "WILD market — new trades paused"
    if pb["take"] == "with_trend" and trade_dir != side:
        return False, 0, None, False, "CHOPPY market — only trades with the bigger trend"
    return True, pb["size"], pb["exits"], pb["reverse"], f"{regime} market — {pb['exits'].replace('_', ' ')} exits, size x{pb['size']}"
