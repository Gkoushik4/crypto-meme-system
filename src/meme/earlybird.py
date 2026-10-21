"""EARLY BIRD — practice (pretend money) momentum trading on brand-new Solana meme coins.
Entry: coins minutes old with a real crowd buying, video-style (Axiom) filters, rug checks (top 10 wallets < 35%).
Exit: free-ride at +100%, tightening trailing stop, early-buyer watch (3 sell -> 25%, 7 sell -> all), danger exits.
Data: GeckoTerminal (every buy/sell with wallet). Rules FIXED 2026-10-19 before the test.  Run: python earlybird.py run SECONDS"""
import sys, json, time, datetime as dt
from pathlib import Path
from collections import defaultdict, deque
import requests

# ============================ RULES (frozen) ============================
START_CASH, TRADE_USD, MAX_OPEN, MAX_SHADOW = 15.0, 5.0, 2, 0
TEST_DAYS = 7
DEXES = {"pump-fun", "pumpswap"}
MAX_AGE_MIN = 120
MIN_VOL_M5, MIN_VOL_H1 = 10_000, 25_000                  # video: minimum volume
MIN_FDV, MAX_FDV = 30_000, 2_000_000                     # video: minimum market cap (early, not huge)
MIN_RESERVE = 10_000
MIN_BUYERS_M5, BUYER_RATIO = 40, 1.5                     # the crowd
MAX_CHG_M5 = 40                                          # already +40% in 5 min = too late
MIN_AVG_TRADE, MAX_TOP5_VOLUME = 15, 0.60                # real traders, not bot spam (video: "global fees paid")
MAX_TOP10_HOLD, MAX_DEV_HOLD, MAX_BUNDLE = 0.35, 0.05, 3 # rug checks
NEED_SOCIALS = True
# exits
FREE_RIDE_AT, FREE_RIDE_SELL = 1.00, 0.50               # +100% -> sell half (money back)
BE_AT = 0.50                                             # +50% -> stop to break-even
TRAILS = [(1.00, 0.30), (3.00, 0.25), (1e9, 0.20)]       # trail below peak: <+100% 30%, <+300% 25%, above 20%
HARD_STOP, MAX_HOLD_H = -0.25, 6
WARN_SELLERS, EXIT_SELLERS, WARN_SELL = 3, 7, 0.25       # of top-20 early buyers
SPIKE, SPIKE_SELL = 0.50, 0.25                           # +50% within ~2 min -> sell 25%
STALL_MIN, STALL_SELL = 30, 0.50                         # no new high 30 min -> sell half
RESERVE_DROP = 0.20
SELLERS_WIN_CHECKS = 3
SLIP, DEX_FEE, NET_FEE = 0.02, 0.0125, 0.02              # new coins: wider slippage, pump fees ~1.25%

API = "https://api.geckoterminal.com/api/v2/networks/solana"
HERE = Path(__file__).resolve().parent
DATA = HERE / "data_earlybird"; DATA.mkdir(exist_ok=True)
CARDS = DATA / "cards"; CARDS.mkdir(exist_ok=True)
STATE = DATA / "state.json"
S = requests.Session(); S.headers["Accept"] = "application/json"
now = time.time
CALLS = deque()

def get(path, params=None):
    for k in range(4):
        while len(CALLS) >= 12 and now() - CALLS[0] < 60:          # shares the free limit (~30/min) with v2
            time.sleep(1);
            while CALLS and now() - CALLS[0] >= 60: CALLS.popleft()
        while CALLS and now() - CALLS[0] >= 60: CALLS.popleft()
        CALLS.append(now())
        try:
            r = S.get(API + path, params=params, timeout=20)
            if r.status_code == 429: time.sleep(10 * (k + 1)); continue
            if r.status_code == 404: return None
            r.raise_for_status(); return r.json()
        except Exception:
            time.sleep(3 * (k + 1))
    return None

ts = lambda t=None: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t or now()))
money = lambda x: f"${x:,.0f}" if abs(x) >= 100 else f"${x:,.2f}"
def px(x): return f"${x:.10f}".rstrip("0") if x < 0.01 else f"${x:,.4f}"
iso = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
f0 = lambda x: float(x or 0)

def card(text):
    with open(CARDS / f"{time.strftime('%Y-%m-%d', time.gmtime())}.md", "a") as f: f.write(text + "\n\n---\n\n")

# ============================ research ============================
BIG_TRADE = 50
def ledger(pool, mint, big=False):
    """Recent buys/sells (last ~300; big=True: only trades over $50, which reaches much further back)."""
    j = get(f"/pools/{pool}/trades", {"trade_volume_in_usd_greater_than": BIG_TRADE} if big else None) or {}
    out = []
    for t in j.get("data") or []:
        a = t["attributes"]; buy = a["kind"] == "buy"
        tok = f0(a["to_token_amount"]) if buy else f0(a["from_token_amount"])
        if (a["to_token_address"] if buy else a["from_token_address"]) != mint: continue
        out.append({"w": a["tx_from_address"], "buy": buy, "tok": tok, "usd": f0(a["volume_in_usd"]),
                    "p": f0(a["price_to_in_usd"] if buy else a["price_from_in_usd"]),
                    "block": int(a["block_number"]), "t": iso(a["block_timestamp"]), "tx": a["tx_hash"]})
    return sorted(out, key=lambda x: (x["block"], x["t"]))

def socials(mint):
    a = ((get(f"/tokens/{mint}/info") or {}).get("data") or {}).get("attributes") or {}
    s = [k for k in ("twitter_handle", "telegram_handle", "discord_url") if a.get(k)] + (["website"] if a.get("websites") else [])
    return s

def evaluate(p, mints_traded_24h):
    a = p["attributes"]; pool = a["address"]
    mint = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
    dex = p["relationships"]["dex"]["data"]["id"]
    age = (now() - iso(a["pool_created_at"])) / 60
    tx5 = (a.get("transactions") or {}).get("m5") or {}; vol = a.get("volume_usd") or {}; chg = a.get("price_change_percentage") or {}
    fdv, price, reserve = f0(a.get("fdv_usd")), f0(a.get("base_token_price_usd")), f0(a.get("reserve_in_usd"))
    sym = a["name"].split(" / ")[0]
    F = dict(pool=pool, mint=mint, sym=sym, dex=dex, age=age, fdv=fdv, price=price, reserve=reserve,
             vol_m5=f0(vol.get("m5")), vol_h1=f0(vol.get("h1")), buyers=tx5.get("buyers", 0), sellers=tx5.get("sellers", 0),
             chg_m5=f0(chg.get("m5")), chg_h1=f0(chg.get("h1")))
    C = []
    def chk(name, ok, why): C.append((name, bool(ok), why)); return ok
    ok = chk("Brand new", dex in DEXES and age <= MAX_AGE_MIN, f"{age:.0f} minutes old on {dex}")
    ok &= chk("Busy (video: min volume)", F["vol_m5"] >= MIN_VOL_M5 and F["vol_h1"] >= MIN_VOL_H1,
              f"{money(F['vol_m5'])} traded in 5 min, {money(F['vol_h1'])} in the hour")
    ok &= chk("Size (video: min market cap)", MIN_FDV <= fdv <= MAX_FDV, f"worth {money(fdv)} — {'early, room to grow' if MIN_FDV <= fdv <= MAX_FDV else 'too tiny' if fdv < MIN_FDV else 'already big'}")
    ok &= chk("Money in the pool", reserve >= MIN_RESERVE, f"{money(reserve)} in the pool")
    ok &= chk("A crowd is buying", F["buyers"] >= MIN_BUYERS_M5 and F["buyers"] >= BUYER_RATIO * max(F["sellers"], 1),
              f"{F['buyers']} different buyers vs {F['sellers']} sellers in the last 5 min")
    ok &= chk("Not too late", F["chg_m5"] <= MAX_CHG_M5, f"price {F['chg_m5']:+.0f}% in the last 5 min")
    ok &= chk("Not a copycat we already traded", sym.lower() not in mints_traded_24h, f"no other '{sym}' traded today")
    if not ok: return C, F, None
    L = ledger(pool, mint)
    if len(L) < 30: chk("Enough trade history", False, f"only {len(L)} trades visible"); return C, F, None
    lp = L[-1]["p"]; fresh = now() - L[-1]["t"] < 180 and price and abs(lp / price - 1) < 0.10
    if not chk("Live price data", fresh, f"last trade {now() - L[-1]['t']:.0f}s ago at {px(lp)} vs listed {px(price)}"): return C, F, None
    F["price"] = lp
    supply = fdv / price if price else 1e9
    net, bought = defaultdict(float), defaultdict(float)
    for t in L:
        net[t["w"]] += t["tok"] if t["buy"] else -t["tok"]
        if t["buy"]: bought[t["w"]] += t["usd"]
    holders = sorted([v for v in net.values() if v > 0], reverse=True)
    top10 = sum(holders[:10]) / supply
    vol_by = defaultdict(float)
    for t in L: vol_by[t["w"]] += t["usd"]
    tot = sum(vol_by.values()) or 1
    top5v = sum(sorted(vol_by.values(), reverse=True)[:5]) / tot
    avg = tot / len(L)
    from_launch = dex == "pump-fun" and L[0]["t"] - iso(a["pool_created_at"]) < 120
    first_block = [t for t in L if t["block"] == L[0]["block"] and t["buy"]]
    dev = L[0]["w"] if from_launch and L[0]["buy"] else None
    dev_hold = max(net.get(dev, 0), 0) / supply if dev else None
    ok &= chk("Real traders, not bots (video: fees paid)", avg >= MIN_AVG_TRADE and top5v <= MAX_TOP5_VOLUME,
              f"average trade {money(avg)}; top 5 wallets did {top5v:.0%} of the trading")
    ok &= chk("Top 10 wallets < 35% (rug check)", top10 < MAX_TOP10_HOLD, f"top 10 wallets hold about {top10:.0%} of all coins")
    ok &= chk("Creator holds ≤ 5%", dev_hold is None or dev_hold <= MAX_DEV_HOLD,
              f"creator holds about {dev_hold:.1%}" if dev_hold is not None else "creator not visible in recent trades (launch too far back) — skipped")
    ok &= chk("No bundle buying", not from_launch or len({t['w'] for t in first_block}) <= MAX_BUNDLE,
              f"{len({t['w'] for t in first_block})} wallets bought in the very first block" if from_launch else "launch not visible — skipped")
    if not ok: return C, F, None
    so = socials(mint)
    ok &= chk("Has socials (video: narrative)", (not NEED_SOCIALS) or bool(so), ", ".join(so) if so else "no Twitter/Telegram/website — no community")
    if not ok: return C, F, None
    BL = ledger(pool, mint, big=True); bnet = defaultdict(float)
    for t in BL: bnet[t["w"]] += t["tok"] if t["buy"] else -t["tok"]
    early = {w: v for w, v in sorted(bnet.items(), key=lambda kv: -kv[1])[:20] if v > 0}   # 20 biggest big-wallet holders when we buy
    last_big = BL[-1]["tx"] if BL else None
    F.update(top10=top10, dev=dev, dev_hold=dev_hold, early=early, seen_tx=[t["tx"] for t in BL] + [t["tx"] for t in L], socials=so, avg=avg)
    return C, F, L

# ============================ positions ============================
def new_pos(F, book):
    e = F["price"] * (1 + SLIP)
    return {"book": book, "pool": F["pool"], "mint": F["mint"], "sym": F["sym"], "opened": now(), "entry": e,
            "qty0": (TRADE_USD * (1 - DEX_FEE) - NET_FEE) / e, "qty": None, "cost": TRADE_USD, "realized": 0.0,
            "peak": e, "peak_t": now(), "stop": e * (1 + HARD_STOP), "early": F["early"], "dev": F["dev"], "sold_early": [],
            "flags": [], "reserve0": F["reserve"], "seen_tx": list(F["seen_tx"]), "bad_checks": 0, "hist": [], "log": []}

def sell(p, share, price, why, quiet):
    q = min(p["qty"], p["qty0"] * share)
    if q <= 0: return
    got = q * price * (1 - SLIP) * (1 - DEX_FEE) - NET_FEE
    p["qty"] -= q; p["realized"] += got
    p["log"].append(f"{ts()} sold {share:.0%} at {px(price)} ({price / p['entry'] - 1:+.0%}) — {why}")
    if not quiet: card(f"### 🔴 {p['sym']}: sell {share:.0%} at {px(price)} ({price / p['entry'] - 1:+.0%}) — {why}")

def manage(p, info, L, quiet):
    if p["qty"] is None: p["qty"] = p["qty0"]
    a = info["attributes"]; price = f0(a.get("base_token_price_usd")); reserve = f0(a.get("reserve_in_usd"))
    if L and now() - L[-1]["t"] < 120: price = L[-1]["p"]          # newest real trade price beats the listed price
    # RUG GUARD: pool drained -> coins can't be sold; prices from an empty pool are fake
    p.setdefault("reserve_peak", p["reserve0"]); p["reserve_peak"] = max(p["reserve_peak"], reserve)
    if reserve < max(1000, 0.3 * p["reserve_peak"]):
        if p["qty"] > 0:
            p["log"].append(f"{ts()} pool drained (money in pool {money(reserve)}, was up to {money(p['reserve_peak'])}) — rug: remaining coins worth $0")
            if not quiet: card(f"### 🚨 {p['sym']}: POOL DRAINED (rug) — remaining coins worth $0")
            p["qty"] = 0; p["why"] = "pool drained (rug)"
        return True
    # FAKE-PRICE GUARD: a jump of more than 2x since the last check is not trusted until it holds for 3 checks (~1 min)
    # while the pool keeps at least half its money. Draining pools show fake spikes — we never sell at those.
    last = p.get("last_good")
    if last and price > 2 * last:
        p["jump_n"] = p.get("jump_n", 0) + 1
        if p["jump_n"] < 3 or reserve < 0.5 * p["reserve_peak"]:
            price = last
        else: p["jump_n"] = 0
    else: p["jump_n"] = 0
    p["last_good"] = price
    tx1 = None
    g = price / p["entry"] - 1
    p["hist"] = (p["hist"] + [[now(), price]])[-10:]
    if price > p["peak"]: p["peak"], p["peak_t"] = price, now()
    gp = p["peak"] / p["entry"] - 1
    # new trades since last check
    seen = set(p["seen_tx"]); new = [t for t in L if t["tx"] not in seen]
    p["seen_tx"] = (p["seen_tx"] + [t["tx"] for t in new])[-1500:]
    sold = p.setdefault("early_sold_tok", {})
    for t in new:
        if not t["buy"] and t["w"] in p["early"]:
            sold[t["w"]] = sold.get(t["w"], 0) + t["tok"]
            if sold[t["w"]] >= 0.5 * p["early"][t["w"]] and t["w"] not in p["sold_early"]: p["sold_early"].append(t["w"])   # sold half+ of their bag
    dev_sold = p["dev"] and any((not t["buy"]) and t["w"] == p["dev"] for t in new)
    m5 = (a.get("transactions") or {}).get("m5") or {}
    p["bad_checks"] = p["bad_checks"] + 1 if m5.get("sellers", 0) > m5.get("buyers", 0) else 0
    def once(flag):
        if flag in p["flags"]: return False
        p["flags"].append(flag); return True
    # danger: everything out
    out = None
    if dev_sold: out = "creator wallet sold (rug warning)"
    elif len(p["sold_early"]) >= EXIT_SELLERS: out = f"{len(p['sold_early'])} of the 20 biggest holders sold half or more of their coins"
    elif p["bad_checks"] >= SELLERS_WIN_CHECKS: out = "more sellers than buyers 3 checks in a row (1 min) — the crowd turned"
    elif now() - p["opened"] > MAX_HOLD_H * 3600: out = "6-hour limit"
    # partial sells
    if not out:
        if g >= FREE_RIDE_AT and once("free"): sell(p, FREE_RIDE_SELL, price, "+100%: took our money back — rest is a free ride", quiet)
        if len(p["sold_early"]) >= WARN_SELLERS and once("warn"): sell(p, WARN_SELL, price, f"{len(p['sold_early'])} of the biggest holders are selling — early warning", quiet)
        old = [x for x in p["hist"] if now() - x[0] <= 150]
        if old and price >= old[0][1] * (1 + SPIKE) and once("spike"): sell(p, SPIKE_SELL, price, "price spiked +50% in ~2 min — sold into strength", quiet)
        if now() - p["peak_t"] > STALL_MIN * 60 and gp > 0 and once("stall"): sell(p, STALL_SELL, price, "no new high for 30 min — hype cooling", quiet)
        # stops
        if gp >= BE_AT: p["stop"] = max(p["stop"], p["entry"] * (1 + DEX_FEE * 2 + SLIP * 2))
        trail = next(tr for lim, tr in TRAILS if gp < lim)
        if gp > 0.2: p["stop"] = max(p["stop"], p["peak"] * (1 - trail))
        if price <= p["stop"]:
            out = "hard stop −25%" if p["stop"] <= p["entry"] * (1 + HARD_STOP) + 1e-15 else ("break-even stop" if p["stop"] < p["entry"] * 1.1 else "trailing stop")
    if out and p["qty"] > 0: sell(p, p["qty"] / p["qty0"], price, out, quiet); p["why"] = out
    return p["qty"] <= p["qty0"] * 1e-9

def close_card(p):
    r = p["realized"] / p["cost"] - 1
    lesson = (f"Peak was {p['peak'] / p['entry'] - 1:+.0%}. " +
              ("Taking money back at +100% made the rest a free ride — this is how big winners are kept." if "free" in p["flags"] and r > 0 else
               "Small win — the exits got us out before the crowd left." if r > 0 else
               "Danger exit saved us from worse — when the creator or early buyers sell, the party is ending." if "rug" in p.get("why", "") or "early buyers" in p.get("why", "") else
               "A loss. Most brand-new coins fail; the fixed stop keeps each loss small so one big winner can pay for many."))
    return (f"## 📗 EARLY BIRD CLOSED {p['sym']} — {'WIN' if r > 0.01 else 'LOSS' if r < -0.01 else 'EVEN'} {r:+.0%} "
            f"({money(p['realized'] - p['cost'])} on {money(p['cost'])})\n" + "\n".join(f"- {x}" for x in p["log"]) + f"\n- **Lesson:** {lesson}")

def buy_card(F, C, took, why_not):
    L = [f"## 🐣 EARLY BIRD BUY: {F['sym']}", f"*{ts()} UTC · pretend money · [chart](https://www.geckoterminal.com/solana/pools/{F['pool']})*", "",
         f"- {F['age']:.0f} minutes old · worth {money(F['fdv'])} · {money(F['reserve'])} in the pool · socials: {', '.join(F['socials'])}",
         f"- Price {F['chg_m5']:+.0f}% (5 min), {F['chg_h1']:+.0f}% (1 hour)", "", "### Every check (video filters + rug checks)"]
    L += [f"- ✅ **{n}:** {w}" for n, ok, w in C]
    L += ["", "### The plan (set before buying)",
          f"- Buy {money(TRADE_USD)} at about {px(F['price'])}. Watching the top 20 early buyers' wallets.",
          "- +50% → stop moves to break-even. +100% → sell half (money back, rest is free).",
          "- Trailing stop: 30% below the top until +100%, 25% until +300%, then 20%.",
          "- 3 early buyers sell → sell 25%. 7 early buyers sell → sell everything.",
          "- Creator sells, or sellers outnumber buyers 3 checks in a row → sell everything.",
          "- Spike +50% in 2 min → sell 25%. No new high in 30 min → sell half. Hard stop −25%. Out within 6 hours.",
          "", f"**Practice account:** {'BOUGHT' if took else 'not bought — ' + why_not} (also tracked in the shadow log).",
          "", "### How to spot this yourself",
          "> Minutes-old coin, a real crowd of different buyers (not a few bots), nobody holding too much, the creator not loaded up, "
          "and the price hasn't exploded yet. Decide your exits *before* you buy — then follow them."]
    return "\n".join(L)

# ============================ loop ============================
def load():
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"started": now(), "cash": START_CASH, "open": [], "closed": [], "sh_open": [], "sh_closed": [], "seen": {},
            "traded_syms": {}, "rejects": {}, "scans": 0, "checked": 0, "gaps": []}

def scan(st):
    st["scans"] += 1
    pools, seen_now = [], set()
    for path, prm in (("/trending_pools", {"duration": "5m", "include": "base_token,dex"}), ("/new_pools", {"include": "base_token,dex"})):
        for p in (get(path, prm) or {}).get("data") or []:
            if p["attributes"]["address"] in seen_now: continue
            seen_now.add(p["attributes"]["address"]); pools.append(p)
    syms24 = {s for s, t in st["traded_syms"].items() if now() - t < 86400}
    for p in pools:
        pool = p["attributes"]["address"]
        if now() < st["seen"].get(pool, 0): continue
        if any(x["pool"] == pool for x in st["open"] + st["sh_open"]): continue
        C, F, L = evaluate(p, syms24)
        st["checked"] += 1
        fails = [n for n, ok, _ in C if not ok]
        if fails:
            for n in fails: st["rejects"][n] = st["rejects"].get(n, 0) + 1
            st["seen"][pool] = now() + (600 if fails[0] in ("Busy (video: min volume)", "A crowd is buying", "Not too late", "Size (video: min market cap)") else 3 * 3600)
            continue
        if now() - st["traded_syms"].get(F["sym"].lower(), 0) < 86400:
            st["seen"][pool] = now() + 86400; st["rejects"]["Not a copycat we already traded"] = st["rejects"].get("Not a copycat we already traded", 0) + 1; continue
        st["seen"][pool] = now() + 86400; st["traded_syms"][F["sym"].lower()] = now()
        took, why = False, ""
        if len(st["open"]) >= MAX_OPEN: why = f"already {MAX_OPEN} open"
        else:
            if st["cash"] < TRADE_USD and not st.get("ran_out"):
                st["ran_out"] = f"{ts()} UTC (day {(now() - st['started']) / 86400:.1f})"   # account would be out of money here
            st["open"].append(new_pos(F, "practice")); st["cash"] -= TRADE_USD; took = True
        if len(st["sh_open"]) < MAX_SHADOW: st["sh_open"].append(new_pos(F, "shadow"))
        card(buy_card(F, C, took, why)); print(f"[{ts()}] BUY {F['sym']} fdv {money(F['fdv'])} took={took}", flush=True)
    st["seen"] = {k: v for k, v in st["seen"].items() if v > now()}

def tick(st):
    byp = {}
    for p in st["open"] + st["sh_open"]: byp.setdefault(p["pool"], []).append(p)
    for pool, ps in byp.items():
        info = (get(f"/pools/{pool}") or {}).get("data")
        L = ledger(pool, ps[0]["mint"], big=True)
        for p in ps:
            practice = p["book"] == "practice"
            if not info:
                p.setdefault("gone", now())
                if now() - p["gone"] > 1800:
                    p["qty"] = 0; p["why"] = "pool vanished (rug)"; p["log"].append("pool vanished — counted as total loss")
                else: continue
                done = True
            else:
                p.pop("gone", None); done = manage(p, info, L, quiet=not practice)
            if done:
                (st["closed"] if practice else st["sh_closed"]).append(p)
                (st["open"] if practice else st["sh_open"]).remove(p)
                if practice: st["cash"] += p["realized"]; card(close_card(p)); print(f"[{ts()}] CLOSED {p['sym']} {p['realized'] / p['cost'] - 1:+.0%}", flush=True)

def report(st):
    def stats(cl):
        r = [p["realized"] / p["cost"] - 1 for p in cl]
        if not r: return "no closed trades yet"
        w = [x for x in r if x > 0.01]
        return (f"{len(r)} trades · {len(w)} wins ({len(w) / len(r):.0%}) · average {sum(r) / len(r):+.0%} · best {max(r):+.0%} · worst {min(r):+.0%} · "
                f"total {sum(p['realized'] - p['cost'] for p in cl):+.2f} on {money(TRADE_USD)} trades")
    txt = "\n".join([f"# 🐣 Early Bird practice — day {(now() - st['started']) / 86400:.1f} of {TEST_DAYS}", f"*Updated {ts()} UTC · pretend money*", "",
        f"- **Practice account ($15 start):** {money(st['cash'])} cash + {len(st['open'])} open",
        f"- **Practice trades:** {stats(st['closed'])}",
        (f"- ⚠️ **The $15 account ran out of money at {st['ran_out']}.** Trading continues in TRACKING MODE (balance can go below $0) so we keep collecting data." if st.get("ran_out") else ""),
        f"- Scans {st['scans']} · coins checked {st['checked']}", "", "## Why coins were skipped"] +
        [f"- {k}: {v}" for k, v in sorted(st["rejects"].items(), key=lambda kv: -kv[1])] +
        (["", "## Gaps"] + [f"- {g}" for g in st["gaps"]] if st["gaps"] else []))
    (DATA / "report.md").write_text(txt); return txt

def run(seconds):
    st = load()
    if st.get("alive") and now() - st["alive"] > 900: st["gaps"].append(f"{ts(st['alive'])} → {ts()} UTC")
    end = min(now() + seconds, st["started"] + TEST_DAYS * 86400); last = 0
    while now() < end:
        try:
            tick(st)                                               # positions checked every ~20 s
            if now() - last >= 60: scan(st); last = now()
        except Exception as e: print("error:", repr(e), flush=True)
        st["alive"] = now(); STATE.write_text(json.dumps(st)); report(st)
        time.sleep(20)
    STATE.write_text(json.dumps(st)); print(report(st))
    if now() >= st["started"] + TEST_DAYS * 86400: print("WEEK DONE")

if __name__ == "__main__":
    if sys.argv[1] == "run": run(float(sys.argv[2]))
    else: print(report(load()))
