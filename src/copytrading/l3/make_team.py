"""Pick the team (top 10 skilled veterans + 5 bench) using ONLY history up to `cut`."""
import sys, json, pickle
sys.path.insert(0, "/home/claude/copychecker")
import pandas as pd
import level2b as B
days = float(sys.argv[1]) if len(sys.argv) > 1 else 0; out = sys.argv[2] if len(sys.argv) > 2 else "team.json"
cut = B.NOW - pd.Timedelta(days=days)
p = B.pick(cut, n=15)
prof = {r.trader: {k: (float(r[k]) if k != "months" else int(r[k])) for k in ("months", "profitable_months", "max_drawdown", "t_stat")} for _, r in p.iterrows()}
team = {"picked_at": str(cut), "main": list(p.trader[:10]), "bench": list(p.trader[10:]), "profiles": prof}
json.dump(team, open(f"/home/claude/copychecker/l3/{out}", "w"), indent=1)
print(f"{out}: main {len(team['main'])}, bench {len(team['bench'])}, picked with history up to {cut.date()}")
