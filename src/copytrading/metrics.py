"""Trader report-card metrics, computed from public Hyperliquid fills and profit history.
Every function only uses data inside the window it is given (no peeking ahead)."""
from collections import defaultdict, deque
import numpy as np
import pandas as pd

MAJORS = {"BTC", "ETH", "SOL"}


def perp_fills(fills, start, end):
    """Perpetual-futures fills inside [start, end) (skips spot '@' and builder 'x:' markets)."""
    s, e = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    return [f for f in fills if s <= f["time"] < e and not f["coin"].startswith("@") and ":" not in f["coin"]]


def profit_factor(fills):
    """Gross realized profit / gross realized loss (fees counted as losses). inf if no losses."""
    gains = losses = 0.0
    for f in fills:
        p = float(f.get("closedPnl", 0)) - float(f.get("fee", 0))
        if p > 0:
            gains += p
        else:
            losses += -p
    if gains == 0 and losses == 0:
        return np.nan
    return np.inf if losses == 0 else gains / losses


def avg_hold_minutes(fills):
    """Size-weighted average holding time, matching closes to opens first-in-first-out per coin.
    Returns (minutes, n_closed_lots). Lots still open at the end are ignored."""
    lots, held, weight = defaultdict(deque), 0.0, 0.0
    for f in sorted(fills, key=lambda x: x["time"]):
        c, sz, px, t = f["coin"], float(f["sz"]), float(f["px"]), f["time"]
        start = float(f["startPosition"])
        delta = sz if f["side"] == "B" else -sz
        # portion that reduces an existing position
        reduce = min(sz, abs(start)) if start != 0 and np.sign(delta) != np.sign(start) else 0.0
        q = reduce
        while q > 1e-12 and lots[c]:
            lot_sz, lot_t = lots[c][0]
            take = min(q, lot_sz)
            held += take * px * (t - lot_t) / 60000.0
            weight += take * px
            q -= take
            if take >= lot_sz - 1e-12:
                lots[c].popleft()
            else:
                lots[c][0] = (lot_sz - take, lot_t)
        opened = sz - reduce
        if opened > 1e-12:
            if reduce > 0:          # flipped through zero: old lots are gone
                lots[c].clear()
            lots[c].append((opened, t))
    return (held / weight if weight > 0 else np.nan), weight


def worst_order_loss(fills):
    """Largest realized loss from a single closing order (fills grouped by order id), in $."""
    by_oid = defaultdict(float)
    for f in fills:
        by_oid[f["oid"]] += float(f.get("closedPnl", 0)) - float(f.get("fee", 0))
    return -min(by_oid.values()) if by_oid and min(by_oid.values()) < 0 else 0.0


def major_share(fills):
    """Share of traded dollar volume in BTC, ETH, SOL."""
    tot = maj = 0.0
    for f in fills:
        v = float(f["sz"]) * float(f["px"])
        tot += v
        if f["coin"] in MAJORS:
            maj += v
    return maj / tot if tot else np.nan


def series(points):
    s = pd.Series({pd.to_datetime(x[0], unit="ms"): float(x[1]) for x in points})
    return s[~s.index.duplicated(keep="last")].sort_index()


def value_at(points, t):
    s = series(points)
    if len(s) == 0 or s.index[0] > t:
        return np.nan
    return float(np.interp(t.timestamp(), [x.timestamp() for x in s.index], s.values))


def period_return(port, a, b):
    """Return from trading between a and b, using profit (so deposits/withdrawals don't count)."""
    av = value_at(port["av"], a)
    pa, pb = value_at(port["pnl"], a), value_at(port["pnl"], b)
    if not av or av <= 0 or np.isnan([pa, pb]).any():
        return np.nan
    return max(-1.0, (pb - pa) / av)


def max_drawdown(port, a, b):
    """Worst drop in (starting value + profit) between a and b. Profit-based so deposits don't hide drops."""
    pnl = series(port["pnl"])
    av0 = value_at(port["av"], a)
    p0 = value_at(port["pnl"], a)
    seg = pnl[(pnl.index >= a) & (pnl.index <= b)]
    if not av0 or av0 <= 0 or len(seg) == 0 or np.isnan(p0):
        return np.nan
    curve = av0 + (seg - p0)
    curve = pd.concat([pd.Series([av0]), curve.reset_index(drop=True)])
    return float((curve / curve.cummax() - 1).min())
