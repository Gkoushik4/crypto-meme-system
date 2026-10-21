"""Level 1a: unit tests on hand-made traders. Each rule must catch exactly what it is meant to."""
import pandas as pd
from metrics import profit_factor, avg_hold_minutes, worst_order_loss, major_share, max_drawdown
from filters import score_trader

T0 = pd.Timestamp("2026-01-01"); T1 = pd.Timestamp("2026-01-31")
ms = lambda t: int(t.timestamp() * 1000)
_oid = [0]

def fill(coin, side, sz, px, minutes, start_pos, pnl=0.0, fee=0.0, oid=None):
    _oid[0] += 1
    return {"coin": coin, "side": side, "sz": str(sz), "px": str(px), "time": ms(T0) + int(minutes * 60000),
            "startPosition": str(start_pos), "closedPnl": str(pnl), "fee": str(fee), "oid": oid or _oid[0]}

def round_trip(coin, minutes_open, hold, pnl, sz=1.0, px=100.0):
    return [fill(coin, "B", sz, px, minutes_open, 0), fill(coin, "A", sz, px, minutes_open + hold, sz, pnl)]

def port(start_value, pnl_path):
    """pnl_path: list of (day, cumulative pnl)."""
    return {"av": [[ms(T0), str(start_value)], [ms(T1), str(start_value + pnl_path[-1][1])]],
            "pnl": [[ms(T0 + pd.Timedelta(days=d)), str(p)] for d, p in pnl_path]}

def good_trader(**kw):
    fl = []
    for k in range(20):
        fl += round_trip("BTC", k * 600, kw.get("hold", 240), kw.get("pnl", 30 if k % 3 else -10))
    return fl

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print("  ✅", name)

print("Metric tests")
check("profit factor: 300 profit / 100 loss = 3", abs(profit_factor([{"closedPnl": 300}, {"closedPnl": -100}]) - 3) < 1e-9)
m, _ = avg_hold_minutes(round_trip("BTC", 0, 120, 5))
check("hold time: 120-minute trade measured as 120 min", abs(m - 120) < 1e-6)
m, _ = avg_hold_minutes([fill("ETH", "B", 2, 100, 0, 0), fill("ETH", "A", 1, 100, 30, 2), fill("ETH", "A", 1, 100, 90, 1)])
check("hold time: partial closes average to 60 min", abs(m - 60) < 1e-6)
check("worst order loss groups fills of one order",
      worst_order_loss([{"oid": 1, "closedPnl": -30}, {"oid": 1, "closedPnl": -20}, {"oid": 2, "closedPnl": -40}]) == 50)
check("major share: 75% BTC volume", abs(major_share([{"coin": "BTC", "sz": 3, "px": 1}, {"coin": "DOGE", "sz": 1, "px": 1}]) - 0.75) < 1e-9)
check("drawdown: 1000 → +200 → 0 profit = -16.7%", abs(max_drawdown(port(1000, [(0, 0), (10, 200), (20, 0)]), T0, T1) - (-200 / 1200)) < 1e-6)

print("Rule tests (each trader breaks exactly one rule)")
base_port = port(10_000, [(0, 0), (15, 400), (30, 800)])
c = score_trader(good_trader(), base_port, T0, T1)
check(f"good trader passes all rules (failed: {c['failed']})", c["passed"])
c = score_trader(good_trader(hold=5), base_port, T0, T1)
check("5-minute scalper is skipped", c["failed"] == ["avg hold ≥ 15 min"])
c = score_trader(good_trader(pnl=-10), port(10_000, [(0, 0), (30, 500)]), T0, T1)
check("profit factor below 1.5 is skipped", "profit factor ≥ 1.5" in c["failed"])
c = score_trader(good_trader() + round_trip("BTC", 30000, 240, -400), base_port, T0, T1)
check("a single 4% loss blocks the trader (risk per trade)", "risk per trade ≤ 2%" in c["failed"])
c = score_trader(good_trader(), port(10_000, [(0, 0), (10, 2000), (20, -200), (30, 800)]), T0, T1)
check("hidden-loss drawdown > 15% blocks the trader", c["failed"] == ["hidden losses / drawdown ≤ 15%"])
c = score_trader(good_trader(), port(10_000, [(0, 0), (15, 15_000), (30, 25_000)]), T0, T1)
check("flashy +250% month is skipped", "not flashy (< +200%)" in c["failed"])
memes = []
for k in range(20):
    memes += round_trip("PEPE", k * 600, 240, 30 if k % 3 else -10)
c = score_trader(memes, base_port, T0, T1)
check("meme-coin trader is not in the Safe Engine", c["failed"] == ["mostly BTC/ETH/SOL"])
print(f"\nLEVEL 1a: {ok} tests passed")
