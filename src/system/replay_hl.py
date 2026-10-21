"""Replay the Hyperliquid side over the last N days with real data (no peeking: data after each step is hidden)."""
import os, sys, time, json
import pandas as pd
os.environ.setdefault("SYSTEM_DATA", "/tmp/claude-0/-home-claude/99094e9b-e071-51e9-93c2-b35e96181cc9/scratchpad/sys_replay")
import system as SY
from l3_live import ReplayMarket, MS
days = float(sys.argv[1]) if len(sys.argv) > 1 else 7
for f in SY.CARDS.glob("*.md"): f.unlink()
if SY.STATE.exists(): SY.STATE.unlink()
SY.MK = ReplayMarket(); st = SY.load()
end = SY.now_ts().floor("5min"); t = end - pd.Timedelta(days=days); st["last_ms"] = MS(t); st["started"] = str(t)
while t < end:
    t += pd.Timedelta(minutes=15); SY.hl_cycle(st, t)
SY.save(st); print(SY.report(st))
cl = pd.DataFrame(st["closed"])
if len(cl): print(cl.groupby("type").agg(trades=("pnl", "size"), wins=("pnl", lambda x: (x > 0).sum()), pnl=("pnl", "sum"), avgR=("R", "mean")).round(2))
print("Types seen:", {k: v["type"] for k, v in st["types"].items()})
print("REPLAY DONE")
