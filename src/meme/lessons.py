"""LESSONS — what the meme tests learned from past trades, shared by all the meme systems.
- Built from the archived week-1 trades (archive/week1_2026-10-23) + keeps growing while tests run.
- DUMPERS: wallets that sold into a crash (rug) of a coin we held, creators of crashed coins, and wallets
  that bundle-bought / sold before crashes in 2+ coins (from v2's wallet scorebook).
  New coins where 2+ of the biggest holders are known dumpers are skipped.
Run:  python lessons.py build   -> writes lessons.json + lessons.md (human-readable)"""
import json, sys, time
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
BASE = HERE / "lessons.json"                      # built once from the archive
ARCHIVES = sorted((HERE / "archive").glob("week*"))
MAX_DUMPERS_IN_TOP = 2                            # 2+ known dumpers among a coin's biggest holders -> skip

def _rug(why): w = (why or "").lower(); return any(k in w for k in ("pool", "rug", "drain", "price disappeared"))

def build():
    dumpers, stats = {}, defaultdict(lambda: [0, 0.0])
    def add(w, why):
        if w: dumpers.setdefault(w, why)
    for A in ARCHIVES:
        for sysname in ("data_earlybird", "data_v2", "data"):
            f = A / sysname / "state.json"
            if not f.exists(): continue
            s = json.loads(f.read_text())
            for t in s.get("closed", []):
                if t.get("shadow"): continue
                cost = t.get("cost") or 1; pnl = t["realized"] - cost
                why = t.get("why") or t.get("exit_reason") or "other"
                key = ("crash (rug)" if _rug(why) else "biggest holders sold (7-of-20 rule)" if "biggest holders" in why
                       else "hard stop" if "hard stop" in why else why[:40])
                stats[(sysname, key)][0] += 1; stats[(sysname, key)][1] += pnl
                if _rug(t.get("why")):
                    for w in t.get("sold_early", []): add(w, f"sold into the {t.get('sym')} crash ({A.name})")
                    add(t.get("dev"), f"creator of {t.get('sym')}, which crashed ({A.name})")
            # v2 scorebook: wallets that bought in the very first block of 2+ coins that later crashed (bundle insiders)
            coins, wallets = s.get("coins", {}), s.get("wallets", {})
            for w, recs in wallets.items():
                bad = [p for p, r in recs.items() if coins.get(p, {}).get("rugged") and r.get("fb")]
                if len(bad) >= 2: add(w, f"bought in the very first block of {len(bad)} coins that crashed — bundle insider ({A.name})")
    BASE.write_text(json.dumps({"built": time.time(), "dumpers": dumpers}))
    md = ["# 📚 Meme lessons (learned from past trades)", f"*Built {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC from {', '.join(a.name for a in ARCHIVES)}*", "",
          f"- **Known dumper wallets:** {len(dumpers)} (coins with {MAX_DUMPERS_IN_TOP}+ of them among the biggest holders are skipped)", "",
          "## What happened, by exit reason (practice trades)"]
    for (sysname, key), (n, usd) in sorted(stats.items(), key=lambda kv: kv[1][1]):
        md.append(f"- {sysname}: **{key}** — {n} trades, {usd:+.2f}")
    md += ["", "## Rules changed because of these lessons (week 2, 2026-10-23)",
           "1. **Costs are real (~6% per buy+sell on new coins)** → max 5 trades a day per system; costs set from Axiom (~1%) + PumpSwap (~1–1.25%) fees.",
           "2. **Half the trades never went up 5% (we bought the top)** → only buy at least 8% below the last 15-minute high, and not after +15% in 5 minutes.",
           "3. **Crashes happened in coins under 1 hour old** → coin must have survived 45 minutes (max 4 hours old).",
           "4. **Crash insiders repeat** → skip coins where 2+ known dumper wallets are among the biggest holders (list grows every crash).",
           "5. **Early Bird had no pool-money alarm** → sell everything when pool money drops 20% from its peak (v2's alarm saved trades).",
           "6. **v2 sold within seconds on old sells** → holder sells from before we bought no longer count; quick flippers (held < 3 min) don't count as 'biggest holders'."]
    (HERE / "lessons.md").write_text("\n".join(md))
    print("\n".join(md))

_CACHE = {"t": 0, "d": {}}
def dumpers():
    """All known dumper wallets (archive + what the live tests learned). Refreshed every 5 minutes."""
    if time.time() - _CACHE["t"] < 300: return _CACHE["d"]
    d = {}
    for f in [BASE] + sorted(HERE.glob("lessons_live_*.json")):
        try: d.update(json.loads(f.read_text()).get("dumpers", {}))
        except Exception: pass
    _CACHE.update(t=time.time(), d=d); return d

def learn(system, wallets, why):
    """A live test saw a crash: remember the wallets that dumped (each test writes its own file — no clashes)."""
    f = HERE / f"lessons_live_{system}.json"
    try: d = json.loads(f.read_text())
    except Exception: d = {"dumpers": {}}
    for w in wallets:
        if w: d["dumpers"].setdefault(w, why)
    f.write_text(json.dumps(d)); _CACHE["t"] = 0

def dumper_check(holder_wallets):
    """(ok, text) — fails when 2+ of these big holders are known dumpers."""
    D = dumpers(); bad = [w for w in holder_wallets if w in D]
    return len(bad) < MAX_DUMPERS_IN_TOP, (f"{len(bad)} of the biggest holders dumped on us before" + (f" (e.g. {D[bad[0]]})" if bad else ""))

if __name__ == "__main__":
    if sys.argv[1:] == ["build"]: build()
    else: print(len(dumpers()), "known dumpers")
