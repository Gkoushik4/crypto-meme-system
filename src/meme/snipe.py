"""LAUNCH SNIPE — practice (pretend money). Part of the INSIDER feature.
Watches every new pump.fun coin on Solana's free live feed (~1 s delay) and "snipes" the ones that pass the insider checks:
  creator isn't a known dumper · creator bought <= 5% of the coins · creator didn't launch another coin in the last 24 h ·
  not a copycat name from the last 24 h.
Honest fills: we buy at the price of the first trade at least 1 SECOND after we saw the launch (real snipers in the same block
pay less — we are measuring what WE would get). Exits are watched live: creator sells / known dumper sells / 5 of the first 10
buyers sell / curve money drops 50% -> out; +100% sell half; break-even at +50%; trailing 30%; stop -25%; no trades 2 min or
30 min max -> out; graduation -> sold at the last curve price. Exits also fill ~1 s after the signal.
Three books, so we learn whether sniping + insider checks really work:
  PRACTICE  $15, $5 trades, max 5 a day (what you'd actually do)
  SAMPLE    every coin that passed the checks (up to 60/day, no money limit) — the honest average
  CONTROL   1 in 40 coins that FAILED the checks (up to 30/day) — shows if the insider checks help
FINAL STRETCH (added 2026-10-23): coins that are about to graduate (launch curve ~70-90% full), still clean on the insider
checks (creator hasn't sold, fewer than 3 of the first buyers sold), with more money coming in than going out in the last minute.
Books: FS PRACTICE ($15, $5 trades, max 5/day) and FS SAMPLE (every coin that qualifies, up to 60/day).
The graduation point is measured live from real graduations (default 85 SOL until we have seen 5).
Run: python snipe.py run SECONDS"""
import sys, json, time
from pathlib import Path
from collections import defaultdict
import requests
import fastfeed as FF, lessons

START_CASH, TRADE_USD, PER_DAY, MAX_OPEN, TEST_DAYS = 15.0, 5.0, 5, 2, 7
SAMPLE_PER_DAY, SAMPLE_MAX_OPEN, CONTROL_EVERY, CONTROL_PER_DAY = 60, 30, 40, 30
MAX_CREATOR_SHARE, REACTION_S, NO_FILL_S = 0.05, 1.0, 60
HARD_STOP, BE_AT, HALF_AT, TRAIL, MAX_HOLD_MIN, QUIET_S = -0.25, 0.50, 1.00, 0.30, 30, 120
FIRST_BUYERS_S, FIRST_N, FIRST_SELL_EXIT, CURVE_DROP = 20, 10, 5, 0.50
SLIP, FEE, NET_FEE = 0.01, 0.022, 0.05        # Axiom ~1% + pump.fun curve ~1.25% per side, ~1% drift, network fee + snipe tip
DUMPER_SELL_USD = 50
FS_FROM, FS_TO, FS_FIRST_SOLD_MAX, FS_WINDOW_S, GRAD_SOL_DEFAULT = 0.70, 0.90, 3, 60, 85.0
CASH_KEY = {"practice": "cash", "fs_practice": "fs_cash"}

HERE = Path(__file__).resolve().parent
DATA = HERE / "data_snipe"; DATA.mkdir(exist_ok=True); CARDS = DATA / "cards"; CARDS.mkdir(exist_ok=True)
STATE = DATA / "state.json"
now = time.time
ts = lambda t=None: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t or now()))
money = lambda x: f"${x:,.2f}"
SOL = {"v": 0, "t": 0}
def sol_usd():
    if now() - SOL["t"] > 600:
        try:
            d = requests.get("https://api.dexscreener.com/tokens/v1/solana/So11111111111111111111111111111111111111112", timeout=10).json()
            v = sorted(float(p["priceUsd"]) for p in d if p.get("quoteToken", {}).get("symbol") in ("USDC", "USDT"))
            if v: SOL.update(v=v[len(v) // 2], t=now())
        except Exception: pass
    return SOL["v"] or 150.0

def card(text):
    with open(CARDS / f"{time.strftime('%Y-%m-%d', time.gmtime())}.md", "a") as f: f.write(text + "\n\n---\n\n")

def load():
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"started": now(), "cash": START_CASH, "open": [], "closed": [], "launches": 0, "passed": 0, "rejects": {},
            "creators": {}, "syms": {}, "fails_seen": 0, "gaps": [], "no_fill": 0, "ran_out": None,
            "fs_cash": START_CASH, "grad_sol": [], "fs_seen": 0}

COINS = {}            # live, not saved: mint -> recent launch info + first buyers

def opened_today(st, book): return sum(1 for p in st["open"] + st["closed"] if p["book"] == book and now() - p["t_signal"] < 86400)

def on_create(st, e, creator_tok):
    st["launches"] += 1
    sym = (e["sym"] or "").strip().lower()
    D = lessons.dumpers()
    checks = [("Creator isn't a known dumper", e["w"] not in D, D.get(e["w"], "clean")),
              ("Creator bought ≤ 5%", creator_tok <= MAX_CREATOR_SHARE * FF.PUMP_SUPPLY, f"creator bought {creator_tok / FF.PUMP_SUPPLY:.1%}"),
              ("Not a serial launcher", now() - st["creators"].get(e["w"], 0) > 86400, "creator launched another coin in the last 24 h" if now() - st["creators"].get(e["w"], 0) <= 86400 else "first launch today"),
              ("Not a copycat name", now() - st["syms"].get(sym, 0) > 86400, f"'{e['sym']}' already launched today" if now() - st["syms"].get(sym, 0) <= 86400 else "new name")]
    st["creators"][e["w"]] = now(); st["syms"][sym] = now()
    COINS[e["mint"]] = {"t": now(), "creator": e["w"], "first": {}, "sym": e["sym"], "name": e["name"], "flow": [], "ok": None}
    fails = [n for n, ok, _ in checks if not ok]
    COINS[e["mint"]]["ok"] = not fails; COINS[e["mint"]]["checks"] = checks
    for n in fails: st["rejects"][n] = st["rejects"].get(n, 0) + 1
    books = []
    if not fails:
        st["passed"] += 1
        if opened_today(st, "practice") < PER_DAY and sum(p["book"] == "practice" for p in st["open"]) < MAX_OPEN: books.append("practice")
        if opened_today(st, "sample") < SAMPLE_PER_DAY and sum(p["book"] == "sample" for p in st["open"]) < SAMPLE_MAX_OPEN: books.append("sample")
    else:
        st["fails_seen"] += 1
        if st["fails_seen"] % CONTROL_EVERY == 0 and opened_today(st, "control") < CONTROL_PER_DAY: books.append("control")
    for b in books: add_pos(st, b, e["mint"], e["sym"], e["name"], e["w"], checks, fails)

def add_pos(st, b, mint, sym, name, creator, checks, fails):
    st["open"].append({"book": b, "mint": mint, "sym": sym, "name": name, "creator": creator, "t_signal": now(),
                       "entry": None, "qty0": 0, "qty": 0, "cost": TRADE_USD, "realized": 0.0, "peak": 0, "flags": [], "log": [],
                       "checks": [(n, ok, w) for n, ok, w in checks], "curve_peak": 0, "first_sold": [], "last_trade": now(),
                       "pending_out": None, "last_px": None, "fails": fails})

def grad_sol(st):
    g = sorted(st.get("grad_sol", [])[-50:]); return g[len(g) // 2] if len(g) >= 5 else GRAD_SOL_DEFAULT

def final_stretch(st, mint, c):
    """Coin crossed ~70% of its launch curve: buy if it's still clean and money keeps coming in."""
    if c.get("fs_done") or not c.get("ok"): return
    prog = c.get("pool_sol", 0) / grad_sol(st)
    if not (FS_FROM <= prog <= FS_TO): return
    c["fs_done"] = True; st["fs_seen"] = st.get("fs_seen", 0) + 1
    flow = [x for x in c["flow"] if now() - x[0] <= FS_WINDOW_S]
    inflow = sum(x[2] for x in flow if x[1]) - sum(x[2] for x in flow if not x[1])
    n_first_sold = sum(1 for w in c["first"] if w in c.get("sold", {}))
    checks = [(n, ok, w) for n, ok, w in c.get("checks", [])] + [
        ("Almost graduated", True, f"launch curve {prog:.0%} full ({c.get('pool_sol', 0):.0f} of ~{grad_sol(st):.0f} SOL)"),
        ("Creator hasn't sold", c["creator"] not in c.get("sold", {}), "creator still holding" if c["creator"] not in c.get("sold", {}) else "creator already sold"),
        ("First buyers mostly holding", n_first_sold < FS_FIRST_SOLD_MAX, f"{n_first_sold} of the first {len(c['first'])} buyers sold"),
        ("Money still coming in", inflow > 0, f"{inflow:+.1f} SOL net in the last minute")]
    fails = [n for n, ok, _ in checks if not ok]
    if fails:
        for n in fails: st["rejects"]["FS: " + n] = st["rejects"].get("FS: " + n, 0) + 1
        return
    for b, cap in (("fs_practice", PER_DAY), ("fs_sample", SAMPLE_PER_DAY)):
        if opened_today(st, b) < cap and sum(p["book"] == b for p in st["open"]) < (MAX_OPEN if b == "fs_practice" else SAMPLE_MAX_OPEN):
            add_pos(st, b, mint, c["sym"], c.get("name", c["sym"]), c["creator"], checks, [])

def sell(p, share, px_usd, why):
    q = min(p["qty"], p["qty0"] * share)
    if q <= 0: return
    p["qty"] -= q; p["realized"] += q * px_usd * (1 - SLIP) * (1 - FEE) - NET_FEE
    p["log"].append(f"{ts()} sold {share:.0%} at {px_usd / p['entry'] - 1:+.0%} — {why}")

def close(st, p, why):
    p["why"] = why; st["open"].remove(p); st["closed"].append(p)
    if p["book"] in CASH_KEY:
        st[CASH_KEY[p["book"]]] = st.get(CASH_KEY[p["book"]], START_CASH) + p["realized"]; r = p["realized"] / p["cost"] - 1
        card(f"## {'🏁 FINAL STRETCH' if p['book'] == 'fs_practice' else '🎯 SNIPE'} CLOSED {p['sym']} — {'WIN' if r > 0.01 else 'LOSS' if r < -0.01 else 'EVEN'} {r:+.0%} ({money(p['realized'] - p['cost'])} on $5) · "
             f"peak {p['peak'] / p['entry'] - 1 if p['entry'] else 0:+.0%}\n" + "\n".join(f"- {x}" for x in p["log"]))
    if p["entry"] and (p["peak"] and p["last_px"] and p["last_px"] < 0.2 * p["peak"] or "creator" in why or "dumper" in why or "first buyers" in why):
        c = COINS.get(p["mint"], {})
        big_sellers = [w for w, x in c.get("sold", {}).items() if x >= 0.5]
        lessons.learn("snipe", [p["creator"]] + big_sellers, f"dumped {p['sym']} right after launch (snipe test, {ts()})")

def on_trade(st, e, sol):
    c = COINS.get(e["mint"])
    if c is not None:
        if e["buy"] and now() - c["t"] <= FIRST_BUYERS_S and e["w"] != c["creator"] and len(c["first"]) < FIRST_N: c["first"].setdefault(e["w"], 0)
        if not e["buy"]: c.setdefault("sold", {}); c["sold"][e["w"]] = c["sold"].get(e["w"], 0) + e["sol"]
        c["flow"] = (c["flow"] + [[now(), e["buy"], e["sol"]]])[-400:]; c["pool_sol"] = e["pool_sol"]
        final_stretch(st, e["mint"], c)
    for p in [x for x in st["open"] if x["mint"] == e["mint"]]:
        px = e["px_sol"] * sol; p["last_trade"] = now(); p["curve_peak"] = max(p["curve_peak"], e["pool_sol"])
        if px <= 0: continue
        if p["entry"] is None:                                     # honest fill: first trade >= 1 s after the signal
            if e["got"] >= p["t_signal"] + REACTION_S:
                p["entry"] = px * (1 + SLIP); p["qty0"] = p["qty"] = (TRADE_USD * (1 - FEE) - NET_FEE) / p["entry"]; p["peak"] = p["entry"]
                p["stop"] = p["entry"] * (1 + HARD_STOP); p["t_open"] = now()
                p["log"].append(f"{ts()} bought {money(TRADE_USD)} {(now() - p['t_signal']):.1f} s after the signal (coin worth ≈{money(px * FF.PUMP_SUPPLY)})")
                if p["book"] == "fs_practice":
                    st["fs_cash"] = st.get("fs_cash", START_CASH) - TRADE_USD
                    card(f"## 🏁 FINAL STRETCH BUY: {p['sym']}\n*{ts()} UTC · pretend money*\n" + "\n".join(f"- ✅ **{n}:** {w}" for n, ok, w in p["checks"]) +
                         "\n\n**Plan:** same exits as the snipe (insider exits, +100% half, trail 30%, stop −25%); graduation → sold at the last curve price."
                         "\n\n> How to spot this yourself (Axiom 'Final Stretch' column): a clean coin close to graduating, creator and first buyers still holding, money still flowing in.")
                if p["book"] == "practice":
                    if st["cash"] < TRADE_USD and not st["ran_out"]: st["ran_out"] = f"{ts()} UTC (day {(now() - st['started']) / 86400:.1f})"
                    st["cash"] -= TRADE_USD
                    card(f"## 🎯 SNIPE BUY: {p['sym']} ({p['name']})\n*{ts()} UTC · pretend money · bought {(now() - p['t_signal']):.1f} s after launch*\n" +
                         "\n".join(f"- ✅ **{n}:** {w}" for n, ok, w in p["checks"]) +
                         "\n\n**Plan:** +100% → sell half (money back) · +50% → stop to break-even · trail 30% below the top · stop −25%."
                         "\n**Insider exits:** creator sells, a known dumper sells, 5 of the first 10 buyers sell, or curve money −50% → sell everything."
                         "\n\n> How to spot this yourself: brand-new coin, creator didn't grab a big bag, isn't a serial launcher and isn't on the dumper list. Snipes are lottery tickets — tiny size, strict exits.")
            continue
        p["last_px"] = px; p["peak"] = max(p["peak"], px)
        if p["pending_out"] or e["buy"]: continue
        D = lessons.dumpers()
        if e["w"] == p["creator"]: p["insider"] = "creator sold"
        elif e["w"] in D and e["sol"] * sol >= DUMPER_SELL_USD: p["insider"] = f"known dumper sold ({D[e['w']][:60]})"
        elif e["w"] in (c or {}).get("first", {}) and e["w"] not in p["first_sold"]:
            p["first_sold"].append(e["w"])
            if len(p["first_sold"]) >= FIRST_SELL_EXIT: p["insider"] = f"{len(p['first_sold'])} of the first {FIRST_N} buyers sold (insider cluster)"

def manage(st, p, sol):
    if p["entry"] is None:
        if now() - p["t_signal"] > NO_FILL_S: st["open"].remove(p); st["no_fill"] += 1
        return
    if p["pending_out"]:
        why, t0 = p["pending_out"]
        if now() - t0 >= REACTION_S:
            if p["qty"] > 0: sell(p, p["qty"] / p["qty0"], p["last_px"] or p["entry"], why + " (filled ~1 s later)")
            close(st, p, why)
        return
    if not p["entry"] or p["entry"] <= 0 or not p["qty0"]: st["open"].remove(p); return
    px = p["last_px"] or p["entry"]; g = px / p["entry"] - 1
    def out(why): p["pending_out"] = [why, now()]
    if p.get("insider"): return out("INSIDER EXIT: " + p["insider"])
    if p.get("graduated"):
        if p["qty"] > 0: sell(p, p["qty"] / p["qty0"], px, "graduated to PumpSwap — sold at the last curve price")
        return close(st, p, "graduated")
    if p["curve_peak"] and COINS.get(p["mint"], {}).get("pool_sol", p["curve_peak"]) < (1 - CURVE_DROP) * p["curve_peak"]: return out("curve money down 50% from its peak")
    if g >= HALF_AT and "half" not in p["flags"]: p["flags"].append("half"); sell(p, 0.5, px, "+100%: half sold — our $5 is back")
    if g >= BE_AT: p["stop"] = max(p["stop"], p["entry"] * 1.05)
    if p["peak"] / p["entry"] - 1 >= 0.3: p["stop"] = max(p["stop"], p["peak"] * (1 - TRAIL))
    if px <= p["stop"]: return out("stop hit" if p["stop"] < p["entry"] else "trailing / break-even stop")
    if now() - p["last_trade"] > QUIET_S: return out("no trades for 2 minutes — the crowd left")
    if now() - p["t_open"] > MAX_HOLD_MIN * 60: return out("30-minute limit")

def report(st, feed):
    def line(book):
        cl = [p for p in st["closed"] if p["book"] == book and p["entry"]]
        if not cl: return "no closed trades yet"
        r = [p["realized"] / p["cost"] - 1 for p in cl]; w = sum(x > 0.01 for x in r)
        return (f"{len(r)} trades · {w} wins ({w / len(r):.0%}) · avg {sum(r) / len(r):+.0%} · best {max(r):+.0%} · worst {min(r):+.0%} · "
                f"+100% trades {sum(x >= 1 for x in r)} · total {sum(p['realized'] - p['cost'] for p in cl):+.2f} on $5 trades")
    why = defaultdict(lambda: [0, 0.0])
    for p in st["closed"]:
        if p["book"] in ("sample", "fs_sample") and p["entry"]:
            k = p["why"].split(" (")[0][:60]; why[k][0] += 1; why[k][1] += p["realized"] - p["cost"]
    days = (now() - st["started"]) / 86400
    txt = "\n".join([f"# 🎯 Launch-snipe practice (insider feature) — day {days:.1f} of {TEST_DAYS}", f"*Updated {ts()} UTC · pretend money*", "",
        f"- **Live feed:** {'connected' if feed.stats['connected'] else 'reconnecting'} · delay ≈{(feed.lag() or 0):.1f} s · we buy ~1 s after launch (real snipers: same block)",
        f"- **Launches seen:** {st['launches']} · passed insider checks: {st['passed']} ({st['passed'] / max(st['launches'], 1):.0%}) · no trades after our signal: {st['no_fill']}",
        f"- **PRACTICE ($15, $5 trades, max 5/day):** {money(st['cash'])} cash + {sum(p['book'] == 'practice' for p in st['open'])} open · {line('practice')}",
        f"- **SAMPLE (every coin that passed):** {line('sample')}",
        f"- **CONTROL (coins that FAILED the checks):** {line('control')}",
        f"- 🏁 **FINAL STRETCH PRACTICE ($15, $5 trades, max 5/day):** {money(st.get('fs_cash', START_CASH))} cash + {sum(p['book'] == 'fs_practice' for p in st['open'])} open · {line('fs_practice')}",
        f"- 🏁 **FINAL STRETCH SAMPLE (every coin that qualified):** {line('fs_sample')}",
        f"- Final Stretch: {st.get('fs_seen', 0)} clean coins reached 70% of the curve · graduation point ≈{grad_sol(st):.0f} SOL (from {len(st.get('grad_sol', []))} graduations seen)",
        (f"- ⚠️ Practice account ran out at {st['ran_out']} — continuing in tracking mode." if st.get("ran_out") else ""),
        f"- Known dumpers: {len(lessons.dumpers())} (grows with every dump we see)", "", "## Why the sample trades ended (snipe + final stretch)"] +
        [f"- {k}: {n} trades, {u:+.2f}" for k, (n, u) in sorted(why.items(), key=lambda kv: kv[1][1])] +
        ["", "## Why launches were skipped"] + [f"- {k}: {v}" for k, v in sorted(st["rejects"].items(), key=lambda kv: -kv[1])] +
        (["", "## Gaps"] + [f"- {g}" for g in st["gaps"]] if st["gaps"] else []))
    (DATA / "report.md").write_text(txt); return txt

def run(seconds):
    st = load(); feed = FF.Feed(programs=[FF.PUMP])
    try: COINS.update(json.loads((DATA / "coins.json").read_text()))       # clean coins we were following (for Final Stretch)
    except Exception: pass
    if st.get("alive") and now() - st["alive"] > 300:
        st["gaps"].append(f"{ts(st['alive'])} → {ts()} UTC")
        for p in list(st["open"]):                                  # we were offline: close what we held at the last known price
            if p["entry"] and p["qty"] > 0: sell(p, p["qty"] / p["qty0"], p["last_px"] or p["entry"], "test was offline — closed at last known price")
            if p["entry"]: close(st, p, "offline gap")
            else: st["open"].remove(p)
    end = min(now() + seconds, st["started"] + TEST_DAYS * 86400); last_save = 0
    while now() < end:
        try:
            sol = sol_usd(); ev = feed.drain()
            creates = {e["sig"]: e for e in ev if e["k"] == "create"}
            for e in ev:
                if e["k"] == "create":
                    ctok = sum(x["tok"] for x in ev if x["k"] == "trade" and x["sig"] == e["sig"] and x["w"] == e["w"] and x["buy"])
                    on_create(st, e, ctok)
                elif e["k"] == "trade" and e["mint"]:
                    if e["mint"] in COINS: COINS[e["mint"]]["pool_sol"] = e["pool_sol"]
                    if e["sig"] in creates: continue                       # the creator's own launch buy
                    on_trade(st, e, sol)
                elif e["k"] == "complete":
                    c = COINS.get(e["mint"])
                    if c and c.get("pool_sol"): st.setdefault("grad_sol", []).append(c["pool_sol"]); st["grad_sol"] = st["grad_sol"][-200:]
                    for p in st["open"]:
                        if p["mint"] == e["mint"]: p["graduated"] = True
            for p in list(st["open"]): manage(st, p, sol)
            for m in [m for m, c in COINS.items() if now() - c["t"] > (6 * 3600 if c.get("ok") else 3600) and not any(p["mint"] == m for p in st["open"])]: COINS.pop(m)
            st["creators"] = {k: v for k, v in st["creators"].items() if now() - v < 86400} if len(st["creators"]) > 200_000 else st["creators"]
        except Exception as ex:
            import traceback; print("error:", repr(ex), traceback.format_exc().splitlines()[-3:], flush=True)
        st["alive"] = now()
        if now() - last_save > 60:
            st["creators"] = {k: v for k, v in st["creators"].items() if now() - v < 86400}; st["syms"] = {k: v for k, v in st["syms"].items() if now() - v < 86400}
            STATE.write_text(json.dumps(st)); report(st, feed); last_save = now()
            keep = {m: dict(c, flow=c["flow"][-100:]) for m, c in COINS.items() if c.get("ok") and now() - c["t"] < 6 * 3600}
            (DATA / "coins.json").write_text(json.dumps(keep))
        time.sleep(0.5)
    STATE.write_text(json.dumps(st)); print(report(st, feed))
    if now() >= st["started"] + TEST_DAYS * 86400: print("WEEK DONE")

if __name__ == "__main__":
    if sys.argv[1] == "run": run(float(sys.argv[2]))
