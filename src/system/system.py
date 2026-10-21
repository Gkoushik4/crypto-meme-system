"""CRYPTO & MEME SYSTEM — one system, two trading places, practice money only.
  • Hyperliquid side: copies the 10 skilled traders' NEW trades in major crypto, altcoins, established memes,
    commodities (oil, gold…), stocks/indexes and forex — each with the rules for its type.
  • Axiom side (Solana): finds brand-new meme coins with the meme safety + timing checks (same live data Axiom shows).
  • A detector labels every coin/market first (classifier.py) and every trade card says what it is and why.
Run:  python system.py once            one cycle
      python system.py loop SECONDS    keep running (used by the GitHub schedule)"""
import os, sys, json, time, math
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "copytrading" / "l3"), str(HERE.parent / "meme")]
import system_rules as R
import classifier as C
import regime as RG
from l3_live import Market, atr_pct, TS, MS
import meme_live as ML

DATA = Path(os.environ.get("SYSTEM_DATA", HERE.parent.parent / "results" / "system")); DATA.mkdir(parents=True, exist_ok=True)
CARDS = DATA / "cards"; CARDS.mkdir(exist_ok=True)
STATE = DATA / "state.json"
TEAM = json.loads((HERE.parent / "copytrading" / "l3" / "team.json").read_text())
now_ts = lambda: pd.Timestamp.utcnow().tz_localize(None)
def fmt(x): return f"${x:,.6f}".rstrip("0") if x < 1 else f"${x:,.2f}"

def card(text):
    with open(CARDS / f"{now_ts():%Y-%m-%d}.md", "a") as f: f.write(text + "\n\n---\n\n")

def load():
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"started": str(now_ts()), "safe": R.SAFE_START, "moon": R.MOON_START, "open": [], "closed": [], "last_ms": None,
            "types": {}, "seen_axiom": {}, "skipped": {}, "next_hl": 0, "next_scan": 0}
def save(st): STATE.write_text(json.dumps(st, default=str))

# ============================ detector (cached) ============================
MK = Market()
def coin_type(st, coin):
    c = st["types"].get(coin)
    if c and time.time() - c["t"] < 86400: return c["type"], c["why"]
    cg = C.coingecko_lists(str(DATA / "coingecko_cache.json"))
    vol = bvol = None
    if ":" not in coin:
        n = now_ts()
        d1 = MK.candles(coin, "1h", n - pd.Timedelta(days=31), n); b1 = MK.candles("BTC", "1h", n - pd.Timedelta(days=31), n)
        if len(d1) > 200 and len(b1) > 200:
            vol = C.daily_vol(d1.close.resample("1D").last().dropna().values); bvol = C.daily_vol(b1.close.resample("1D").last().dropna().values)
    t, why = C.classify(coin, vol=vol, btc_vol=bvol, cg=cg)
    st["types"][coin] = {"type": t, "why": why, "t": time.time()}
    return t, why

def is_weekend_block(t):
    wd, h = t.weekday(), t.hour
    after_fri = (wd == R.NO_ENTRY_FROM[0] and h >= R.NO_ENTRY_FROM[1]) or wd == 5 or (wd == 6 and h < R.REOPEN_AT[1])
    return after_fri

# ============================ positions (shared) ============================
def open_hl(st, sig, typ, rule, size, scale, rev_ok, reg, why_type, why_reg, px_now, c1, now):
    sd = max(rule["stop"] * atr_pct(c1, now), 0.004)
    if math.isnan(sd): return None
    bucket = rule["bucket"]; cash = st[bucket]
    e = px_now * (1 + sig["dir"] * R.SLIPPAGE)
    notional = min(cash * rule["risk"] * size / sd, R.MAX_NOTIONAL_X * cash / R.SAFE_MAX_OPEN)
    p = {"side": "hyperliquid", "type": typ, "bucket": bucket, "coin": sig["coin"], "dir": sig["dir"], "trader": sig["trader"], "opened": str(now),
         "entry": e, "stop": e * (1 - sig["dir"] * sd), "target": e * (1 + sig["dir"] * R.TAKE_PROFIT_R * sd), "sd": sd, "best": e,
         "notional": notional, "risk_usd": notional * sd, "last_bar": str(now), "hold_h": rule["hold_h"], "scale": scale, "frac": 1.0,
         "part": 0.0, "rev_ok": rev_ok, "regime": reg, "why_type": why_type, "why_regime": why_reg, "weekend": rule["weekend"]}
    return p

def step_hl(p, bars, now):
    d, e, sd = p["dir"], p["entry"], p["sd"]
    for t, b in bars[bars.index > pd.Timestamp(p["last_bar"])].iterrows():
        x = why = None
        if (d == 1 and b.low <= p["stop"]) or (d == -1 and b.high >= p["stop"]):
            x = min(p["stop"], b.open) if d == 1 else max(p["stop"], b.open)
            why = "stop-loss" if (p["stop"] - e) * d < 0 else ("break-even stop" if abs(p["stop"] / e - 1) < 0.002 else "trailing stop")
        elif (d == 1 and b.high >= p["target"]) or (d == -1 and b.low <= p["target"]): x, why = p["target"], "take-profit (3x risk)"
        elif t >= pd.Timestamp(p["opened"]) + pd.Timedelta(hours=p["hold_h"]): x, why = b.close, f"time limit ({p['hold_h'] // 24} days)"
        elif p["weekend"] and t.weekday() == R.CLOSE_ALL_AT[0] and (t.hour, t.minute) >= (R.CLOSE_ALL_AT[1], 30):
            x, why = b.close, "closed before the weekend (real market closes → price gaps)"
        p["last_bar"] = str(t)
        if x is not None:
            x *= (1 - d * R.SLIPPAGE); ret = d * (x / e - 1) - 2 * R.FEE
            pnl = p["part"] + p["notional"] * p["frac"] * ret
            return {**p, "closed": str(t), "exit": x, "pnl": pnl, "R": pnl / (p["notional"] * sd), "why": why}
        p["best"] = max(p["best"], b.high) if d == 1 else min(p["best"], b.low); g = d * (p["best"] / e - 1) / sd
        if p["scale"] and p["frac"] == 1.0 and g >= 1:
            lvl = e * (1 + d * sd) * (1 - d * R.SLIPPAGE); p["part"] = p["notional"] * 0.5 * (d * (lvl / e - 1) - 2 * R.FEE); p["frac"] = 0.5
        if g >= R.BREAK_EVEN_R:
            be = e * (1 + d * 2 * R.FEE); p["stop"] = max(p["stop"], be) if d == 1 else min(p["stop"], be)
        if g >= R.TRAIL_START_R:
            tr = p["best"] * (1 - d * R.TRAIL_R * sd); p["stop"] = max(p["stop"], tr) if d == 1 else min(p["stop"], tr)
    return None

def hl_card(p, sig, size_note):
    side = "LONG" if p["dir"] == 1 else "SHORT"
    return "\n".join([f"## {C.ICON[p['type']]} {p['coin']} {side} — {p['type'].upper()} (Hyperliquid)", f"*{p['opened'][:16]} UTC · practice money*",
        f"- **What it is:** {p['why_type']}.", f"- **Copied from** skilled trader `{sig['trader'][:6]}…{sig['trader'][-4:]}` (opened at {fmt(sig['px'])}).",
        f"- **Market:** {p['why_regime']}.", f"- **Money:** {'Safe side (85%)' if p['bucket'] == 'safe' else 'Moonshot side (15%)'} · risk {fmt(p['risk_usd'])}{size_note}.",
        f"- **Plan:** entry ≈{fmt(p['entry'])}, stop {fmt(p['stop'])}, target {fmt(p['target'])} (3x risk)" + (", sell half at +1x risk" if p["scale"] else "") +
        f", max hold {p['hold_h'] // 24} days" + (", closed before the weekend" if p["weekend"] else "") + "."])

# ============================ Hyperliquid side ============================
def hl_cycle(st, now):
    since = TS(st["last_ms"]) if st["last_ms"] else now - pd.Timedelta(minutes=10)
    # manage open Hyperliquid positions
    for p in [x for x in st["open"] if x["side"] == "hyperliquid"]:
        bars = MK.candles(p["coin"], "5m", pd.Timestamp(p["last_bar"]) - pd.Timedelta(minutes=10), now)
        c = step_hl(p, bars, now)
        if c:
            st["open"].remove(p); st[c["bucket"]] += c["pnl"]; st["closed"].append(c)
            card(f"### 📗 CLOSED {C.ICON[c['type']]} {c['coin']} ({c['type']}) — {'WIN' if c['pnl'] > 0.001 else 'LOSS' if c['pnl'] < -0.001 else 'EVEN'} "
                 f"{c['R']:+.2f}x risk = {c['pnl']:+.2f} USD · {c['why']}")
            if c["rev_ok"] and c["why"] == "stop-loss" and not c.get("reversed"):
                c1 = MK.candles(c["coin"], "1h", now - pd.Timedelta(days=30), now)
                rule = R.TYPE_RULES[c["type"]]
                rp = open_hl(st, {"coin": c["coin"], "dir": -c["dir"], "trader": c["trader"], "px": c["exit"]}, c["type"], rule, 1.0, False, False,
                             c["regime"], c["why_type"], "stop-and-reverse (trending market)", c["exit"], c1, pd.Timestamp(c["closed"])) if len(c1) > 50 else None
                if rp: rp["reversed"] = True; st["open"].append(rp); card(f"### ↩️ {c['coin']}: stopped out in a trending market — flipped once")
    # new trades by the main team
    for a in TEAM["main"]:
        fl = MK.fills(a, since - pd.Timedelta(minutes=1), now)
        seen = set()
        for f in fl:
            if f["time"] <= MS(since) or abs(float(f["startPosition"])) > 1e-12 or f["coin"].startswith("@") or "/" in f["coin"]: continue
            key = (f["coin"], f["time"])
            if key in seen: continue
            seen.add(key); new_signal(st, a, f, now)
    st["last_ms"] = MS(now)

def skip(st, typ, why):
    st["skipped"][f"{typ}: {why}"] = st["skipped"].get(f"{typ}: {why}", 0) + 1

def new_signal(st, trader, f, now):
    coin, d = f["coin"], 1 if f["side"] == "B" else -1
    typ, why_t = coin_type(st, coin)
    if typ in R.NOT_TRADED: skip(st, typ, "not traded"); card(f"### {C.ICON[typ]} skipped {coin}: {why_t} — not traded"); return
    rule = R.TYPE_RULES[typ]
    if rule["weekend"] and is_weekend_block(now): skip(st, typ, "weekend (real market closed)"); return
    opn = [p for p in st["open"] if p["side"] == "hyperliquid"]
    if typ in R.MACRO and sum(p["type"] in R.MACRO for p in opn) >= R.MACRO_MAX_OPEN: skip(st, typ, "macro limit reached"); return
    if rule["bucket"] == "safe" and sum(p["bucket"] == "safe" for p in opn) >= R.SAFE_MAX_OPEN: skip(st, typ, "Safe side full"); return
    if rule["bucket"] == "moon" and sum(p["bucket"] == "moon" for p in st["open"]) >= R.MOON_MAX_OPEN: skip(st, typ, "Moonshot side full"); return
    if any(p["coin"] == coin and p["dir"] == d for p in opn): return
    # market regime: BTC's for crypto, the market's own chart for oil/stocks/forex
    if rule["regime"] == "own":
        own4 = MK.candles(coin, "4h", now - pd.Timedelta(days=200), now)
        reg, side = RG.regime_at(RG.label_series(own4), now) if len(own4) > 320 else (None, 0)
        regname = f"{coin}'s own chart"
    else:
        b4 = MK.candles("BTC", "4h", now - pd.Timedelta(days=160), now)
        reg, side = RG.regime_at(RG.label_series(b4), now) if len(b4) > 400 else (None, 0); regname = "BTC"
    if rule["regime"] == "btc_wild_only":
        take, size, exits, rev, why_r = (reg != "WILD"), 1.0, "scale_out", False, f"{regname} market is {reg or 'unknown'}" + (" — memes paused" if reg == "WILD" else "")
    else:
        take, size, exits, rev, why_r = RG.decide(reg, side, d); why_r = f"{regname}: {why_r}"
    if not take: skip(st, typ, why_r.split(' — ')[-1]); card(f"### {C.ICON[typ]} skipped {coin} {'long' if d == 1 else 'short'} ({typ}): {why_r}"); return
    c1 = MK.candles(coin, "1h", now - pd.Timedelta(days=30), now); c5 = MK.candles(coin, "5m", now - pd.Timedelta(hours=2), now)
    if len(c1) < 50 or not len(c5): skip(st, typ, "not enough price history"); return
    scale = rule["scale"] == "always" or exits == "scale_out"
    p = open_hl(st, {"coin": coin, "dir": d, "trader": trader, "px": float(f["px"])}, typ, rule, size, scale, rev and typ in ("major", "altcoin"),
                reg, why_t, why_r, float(c5.close.iloc[-1]), c1, now)
    if not p: return
    st["open"].append(p); card(hl_card(p, {"trader": trader, "px": float(f["px"])}, f" (half size)" if size < 1 else ""))
    print(f"[{now:%m-%d %H:%M}] HL {typ} {coin} {'long' if d == 1 else 'short'}", flush=True)

# ============================ Axiom side (new Solana memes) ============================
def axiom_scan(st, now):
    st["seen_axiom"] = {k: v for k, v in st["seen_axiom"].items() if v > time.time()}          # keep the file small
    addrs, meta = ML.candidates(); fresh = [a for a in addrs if time.time() >= st["seen_axiom"].get(a, 0)]
    best = ML.pairs_for(fresh)
    for a in fresh:
        p = best.get(a)
        if not p: continue
        checks, f = ML.research(a, p, meta.get(a, {}))
        fails = [n for n, ok, _ in checks if not ok]
        typ, why_t = C.classify(f["symbol"], venue="solana", age_h=f["age_h"], launchpad=None)
        if fails: st["seen_axiom"][a] = time.time() + 1800; skip(st, "new meme", fails[0]); continue
        sc, sfails = ML.safety(a); time.sleep(1)
        if sc is None or sfails: st["seen_axiom"][a] = time.time() + 6 * 3600; skip(st, "new meme", (sfails or ["no safety data"])[0]); continue
        st["seen_axiom"][a] = time.time() + 86400
        n_new = sum(x["side"] == "axiom" for x in st["open"])
        if n_new >= R.NEW_MEME_MAX_OPEN or sum(x["bucket"] == "moon" for x in st["open"]) >= R.MOON_MAX_OPEN or st["moon"] < R.NEW_MEME_USD:
            skip(st, "new meme", "Moonshot side full"); continue
        pos = ML.open_pos(f, a, "system", style="Ladder", cost=R.NEW_MEME_USD)
        pos.update(side="axiom", type="new meme", bucket="moon", coin=f["symbol"], why_type=why_t, opened_ts=str(now))
        st["moon"] -= R.NEW_MEME_USD; st["open"].append(pos)
        card(f"## 🟥 {f['symbol']} — NEW MEME (Axiom side · practice) [chart]({f['url']})\n- **What it is:** {why_t}; worth {ML.money(f['mcap'])}, "
             f"{ML.money(f['liq'])} in the pool.\n" + "\n".join(f"- ✅ {n}: {w}" for n, ok, w in sc + checks) +
             f"\n- **Plan:** $5 from the Moonshot side. Sell 25% at +25%, +50%, +100%; trail the rest; −20% stop; out if not +15% in 30 min; max 24 h.")
        print(f"[{now:%m-%d %H:%M}] AXIOM new meme {f['symbol']}", flush=True)

def axiom_tick(st):
    ax = [p for p in st["open"] if p["side"] == "axiom"]
    if not ax: return
    pr = ML.prices([p["mint"] for p in ax])
    for p in ax:
        price = pr.get(p["mint"])
        if price is None: continue
        if price == "DRAINED": p["qty"] = 0; p["exit_reason"] = "pool drained (rug) — coins worth $0"; done = True
        else:
            last = p.get("last_good")
            if last and price > 2 * last:
                p["jump_n"] = p.get("jump_n", 0) + 1
                if p["jump_n"] < 3: price = last
                else: p["jump_n"] = 0
            else: p["jump_n"] = 0
            p["last_good"] = price; done = ML.manage(p, price, quiet=True)
        if done:
            st["open"].remove(p); st["moon"] += p["realized"]
            r = p["realized"] / p["cost"] - 1
            c = {"side": "axiom", "type": "new meme", "bucket": "moon", "coin": p["coin"], "pnl": p["realized"] - p["cost"], "R": r, "why": p["exit_reason"] or "sold in steps", "closed": str(now_ts())}
            st["closed"].append(c); card(f"### 📗 CLOSED 🟥 {p['coin']} (new meme) — {'WIN' if r > 0.005 else 'LOSS'} {r:+.0%} ({c['pnl']:+.2f} USD) · peak {p['peak'] / p['entry'] - 1:+.0%} · {c['why']}")

# ============================ report ============================
def report(st):
    cl = pd.DataFrame(st["closed"]) if st["closed"] else pd.DataFrame(columns=["type", "pnl"])
    rows = []
    for t in (C.MAJOR, C.ALT, C.MEME, C.NEW_MEME, C.COMMODITY, C.STOCK, C.FOREX):
        g = cl[cl.type == t]; o = [p for p in st["open"] if p["type"] == t]
        rows.append(f"| {C.ICON[t]} {t} | {len(g)} | {int((g.pnl > 0).sum()) if len(g) else 0} | {g.pnl.sum() if len(g) else 0:+.2f} | {len(o)} |")
    started = pd.Timestamp(st["started"])
    txt = "\n".join([f"# 🧭 Crypto & Meme System — live practice", f"*Started {started:%Y-%m-%d %H:%M} UTC · updated {now_ts():%Y-%m-%d %H:%M} UTC · pretend money*", "",
        f"- **Safe side (85%):** ${st['safe']:.2f} (started $85) · **Moonshot side (15%):** ${st['moon']:.2f} (started $15)",
        f"- Open positions: {len(st['open'])}", "", "| Type | Closed trades | Wins | Profit/loss $ | Open |", "|---|---|---|---|---|"] + rows +
        ["", "## Why trades were skipped (top 12)"] + [f"- {k}: {v}" for k, v in sorted(st["skipped"].items(), key=lambda kv: -kv[1])[:12]])
    (DATA / "report.md").write_text(txt); return txt

def cycle(st, force_hl=False):
    now = now_ts()
    if force_hl or time.time() >= st["next_hl"]: hl_cycle(st, now); st["next_hl"] = time.time() + R.HL_EVERY_S
    if time.time() >= st["next_scan"]: axiom_scan(st, now); st["next_scan"] = time.time() + R.SCAN_EVERY_S
    axiom_tick(st)

if __name__ == "__main__":
    st = load(); mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "once": cycle(st, force_hl=True)
    else:
        end = time.time() + float(sys.argv[2])
        while time.time() < end:
            try: cycle(st)
            except Exception as e: print("error:", repr(e), flush=True)
            save(st); report(st); time.sleep(R.TICK_EVERY_S)
    save(st); print(report(st))
