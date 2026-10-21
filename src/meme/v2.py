"""MEME v2 — practice (pretend money). Early Bird entries + PRO/EARLY-WALLET watch + profit lock + scam alarms.
- Scorebook: learns which wallets are real pros / early wallets from every coin we watch (grows every day).
- Entry A: Early Bird filters.  Entry B: 2+ trusted wallets with real money bet big on a new coin (plus safety checks).
- Exits: 25% at +50%, 25% at +100%, floor stop +40%; stay while the pros stay, sell when 1-2 top wallets sell;
  scam alarms (staircase bot pattern, pool money dropping, creator selling); fake-price guard; 5-second price checks.
Rules fixed 2026-10-20 before the v2 test.  Run: python v2.py run SECONDS"""
import sys, json, time, statistics
from pathlib import Path
from collections import deque, defaultdict
import requests
import earlybird as EB

# ============================ RULES (frozen) ============================
START_CASH, TRADE_USD, MAX_OPEN, TEST_DAYS = 30.0, 10.0, 2, 7
GT_RATE = 14                                   # GeckoTerminal calls/min for v2 (v1 uses 12; free limit ~30)
PRICE_EVERY, HOLDERS_EVERY, STAIR_EVERY, SCAN_EVERY = 5, 30, 300, 60
# scorebook
MIN_COINS, PRO_WIN, PRO_PNL, MAX_RUG_SHARE, MAX_FIRSTBLOCK, MIN_HOLD_MIN = 5, 0.60, 1000, 0.30, 0.20, 3
EARLY_HIT_X, EARLY_SHARE = 2.0, 0.50           # coin later reached 2x their buy price in >=50% of their coins
TOP_PRO_PNL = 5000
CONVICTION, BIG_WALLET_USD = 0.10, 5000        # bet >=10% of wallet, or wallet >= $5k
COLLECT_HOURS, REVISIT_MIN, MAX_REVISITS_PER_MIN = 6, 30, 4
# entry B (smart money)
B_MIN_TRUSTED, B_WINDOW_MIN, B_MAX_AGE_H = 2, 30, 6
# exits
HARD_STOP, STEP1_AT, STEP1, STEP2_AT, STEP2, FLOOR = -0.25, 0.50, 0.25, 1.00, 0.25, 0.40
POOL_DROP, DRAINED = 0.20, 0.30
WARN_SELLERS, EXIT_SELLERS = 3, 7
SELL_PRESSURE_CHECKS = 6
MAX_HOLD_H = 12
STAIR_N, STAIR_GREEN, STAIR_MAX_DIP, STAIR_VOL_CV = 24, 0.85, 0.05, 0.35
SLIP, FEE, NET_FEE = EB.SLIP, EB.DEX_FEE, EB.NET_FEE
# rug-risk mode (added 2026-10-20, user's idea): high rug-risk coins sell faster at big gains
RR_POOL_VS_VALUE, RR_TOP10, RR_CREATOR, RR_SOFT_STAIR = 0.15, 0.25, 0.01, (0.75, 0.08)
RUG_USER = [(1.50, 0.75), (2.00, 1.00)]                 # user's version: +150% sell 75%, +200% sell the rest
RUG_BLEND = [(0.50, 0.25), (1.50, 0.50), (2.00, 1.00)]  # safer blend: +50% 25%, +150% 50%, +200% the rest

HERE = Path(__file__).resolve().parent
DATA = HERE / "data_v2"; DATA.mkdir(exist_ok=True)
CARDS = DATA / "cards"; CARDS.mkdir(exist_ok=True)
STATE = DATA / "state.json"
now = time.time; ts = EB.ts; money = EB.money; px = EB.px; f0 = EB.f0
RPC = "https://api.mainnet-beta.solana.com"
S = requests.Session()

# ---- shared GeckoTerminal limiter for this process (Early Bird helpers use it too) ----
CALLS = deque()
def gget(path, params=None):
    for k in range(4):
        while True:
            while CALLS and now() - CALLS[0] >= 60: CALLS.popleft()
            if len(CALLS) < GT_RATE: break
            time.sleep(0.5)
        CALLS.append(now())
        try:
            r = S.get(EB.API + path, params=params, timeout=20)
            if r.status_code == 429: time.sleep(10 * (k + 1)); continue
            if r.status_code == 404: return None
            r.raise_for_status(); return r.json()
        except Exception: time.sleep(3 * (k + 1))
    return None
EB.get = gget
def budget(n):
    while CALLS and now() - CALLS[0] >= 60: CALLS.popleft()
    return len(CALLS) + n <= GT_RATE

def card(text):
    with open(CARDS / f"{time.strftime('%Y-%m-%d', time.gmtime())}.md", "a") as f: f.write(text + "\n\n---\n\n")

def dex_prices(mints):
    """Fast prices + pool money from DexScreener (allows ~300 calls/min)."""
    out = {}
    for i in range(0, len(mints), 30):
        try: data = S.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(mints[i:i + 30]), timeout=10).json()
        except Exception: continue
        for p in data or []:
            a = p.get("baseToken", {}).get("address"); liq = ((p.get("liquidity") or {}).get("usd")) or 0
            if a in mints and (a not in out or liq > out[a]["liq"]):
                tx = (p.get("txns") or {}).get("m5") or {}
                out[a] = {"price": f0(p.get("priceUsd")), "liq": liq, "buys": tx.get("buys", 0), "sells": tx.get("sells", 0)}
    return out

SOL_PX = {"v": 0, "t": 0}
def sol_price():
    if now() - SOL_PX["t"] > 600:
        try:
            d = S.get("https://api.dexscreener.com/tokens/v1/solana/So11111111111111111111111111111111111111112", timeout=10).json()
            SOL_PX["v"] = max(f0(p.get("priceUsd")) for p in d if p.get("baseToken", {}).get("symbol") in ("SOL", "WSOL")); SOL_PX["t"] = now()
        except Exception: pass
    return SOL_PX["v"] or 150.0

def wallet_usd(wallets):
    out = {}
    for i in range(0, len(wallets), 100):
        try:
            r = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                                  "params": [wallets[i:i + 100], {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}]}, timeout=15).json()
            for w, acc in zip(wallets[i:i + 100], r["result"]["value"]):
                out[w] = (acc["lamports"] / 1e9 * sol_price()) if acc else 0.0
        except Exception: pass
    return out

# ============================ scorebook ============================
def ingest(st, pool, mint, trades, price, reserve, created=None, sym=""):
    """Record big trades of a coin into the wallet scorebook and track the coin's outcome."""
    c = st["coins"].setdefault(pool, {"mint": mint, "sym": sym, "first": now(), "peak": price, "last": price, "res_peak": reserve,
                                      "rugged": False, "seen": [], "visits": 0, "next": now() + REVISIT_MIN * 60, "first_block": None})
    c["last"] = price or c["last"]; c["peak"] = max(c["peak"], price or 0); c["res_peak"] = max(c["res_peak"], reserve or 0)
    if (reserve is not None and c["res_peak"] and reserve < DRAINED * c["res_peak"]) or (c["peak"] and price and price < 0.1 * c["peak"]):
        c["rugged"] = True
    seen = set(c["seen"])
    if trades and c["first_block"] is None: c["first_block"] = trades[0]["block"]
    for t in trades:
        if t["tx"] in seen: continue
        seen.add(t["tx"])
        w = st["wallets"].setdefault(t["w"], {})
        r = w.setdefault(pool, {"b": 0.0, "s": 0.0, "tok": 0.0, "t0": None, "px0": None, "fb": False, "ts": None})
        if t["buy"]:
            r["b"] += t["usd"]; r["tok"] += t["tok"]
            if r["t0"] is None: r["t0"], r["px0"] = t["t"], t["p"]; r["fb"] = (t["block"] == c["first_block"])
        else:
            r["s"] += t["usd"]; r["tok"] -= t["tok"]
            if r["ts"] is None: r["ts"] = t["t"]
    c["seen"] = list(seen)[-3000:]

def profile(st, w, exclude_pool=None):
    recs = {p: r for p, r in st["wallets"].get(w, {}).items() if p != exclude_pool and p in st["coins"]
            and now() - st["coins"][p]["first"] > 3600 and r["b"] > 0}
    n = len(recs)
    if n < MIN_COINS: return None
    pnl, wins, rug, fb, hits, holds = 0.0, 0, 0, 0, 0, []
    for p, r in recs.items():
        c = st["coins"][p]; left = max(r["tok"], 0) * (0 if c["rugged"] else c["last"])
        x = r["s"] + left - r["b"]; pnl += x; wins += x > 0; rug += c["rugged"]; fb += r["fb"]
        hits += bool(r["px0"] and c["peak"] >= EARLY_HIT_X * r["px0"])
        if r["t0"] and r["ts"]: holds.append((r["ts"] - r["t0"]) / 60)
    med_hold = statistics.median(holds) if holds else 999
    clean = rug / n <= MAX_RUG_SHARE and fb / n <= MAX_FIRSTBLOCK and med_hold >= MIN_HOLD_MIN
    pro = clean and wins / n >= PRO_WIN and pnl >= PRO_PNL
    early = clean and hits / n >= EARLY_SHARE
    if not (pro or early): return None
    return {"n": n, "pnl": pnl, "win": wins / n, "early": hits / n, "pro": pro, "early_w": early, "top": pro and pnl >= TOP_PRO_PNL, "hold": med_hold}

def trusted_in(st, pool, trades, window_min=None):
    """Trusted wallets that bought this coin (optionally in the last N minutes) and still hold."""
    net, bought, last_buy = defaultdict(float), defaultdict(float), {}
    for t in trades:
        net[t["w"]] += t["tok"] if t["buy"] else -t["tok"]
        if t["buy"]: bought[t["w"]] += t["usd"]; last_buy[t["w"]] = t["t"]
    out = {}
    for w, v in net.items():
        if v <= 0 or w not in st["wallets"]: continue
        if window_min and now() - last_buy.get(w, 0) > window_min * 60: continue
        pr = profile(st, w, exclude_pool=pool)          # fair: judged only on OTHER coins
        if pr: out[w] = dict(pr, tok=v, bet=bought[w])
    if out:
        bal = wallet_usd(list(out))
        for w in out:
            u = bal.get(w, 0); out[w]["wallet"] = u; out[w]["conv"] = out[w]["bet"] / (u + out[w]["bet"]) if (u + out[w]["bet"]) else 0
    return out

def collect(st):
    due = sorted([(c["next"], p) for p, c in st["coins"].items() if c["next"] <= now() and c["visits"] < COLLECT_HOURS * 60 / REVISIT_MIN])
    for _, pool in due[:MAX_REVISITS_PER_MIN]:
        if not budget(3): break
        c = st["coins"][pool]; info = (gget(f"/pools/{pool}") or {}).get("data")
        a = (info or {}).get("attributes") or {}
        L = EB.ledger(pool, c["mint"], big=True)
        ingest(st, pool, c["mint"], L, f0(a.get("base_token_price_usd")) or c["last"], f0(a.get("reserve_in_usd")) if info else 0)
        c["visits"] += 1; c["next"] = now() + REVISIT_MIN * 60
    for p in [p for p, c in st["coins"].items() if now() - c["first"] > 7 * 86400]: st["coins"].pop(p, None)
    if now() - st.get("pruned", 0) > 3600:           # drop one-coin wallets older than a day (keeps the file small)
        for w in [w for w, r in st["wallets"].items() if len(r) == 1 and all(p not in st["coins"] or now() - st["coins"][p]["first"] > 86400 for p in r)]:
            st["wallets"].pop(w, None)
        st["pruned"] = now()

# ============================ staircase detector ============================
def staircase(pool, raw=False):
    j = gget(f"/pools/{pool}/ohlcv/minute", {"aggregate": 5, "limit": STAIR_N, "currency": "usd"}) or {}
    l = sorted(((j.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
    if len(l) < 12: return (False, "not enough history", None, None) if raw else (False, "not enough history")
    green = sum(1 for x in l if x[4] >= x[1]) / len(l)
    peak, dip = 0, 0
    for x in l: peak = max(peak, x[2]); dip = max(dip, 1 - x[3] / peak if peak else 0)
    vols = [x[5] for x in l]; cv = statistics.pstdev(vols) / statistics.mean(vols) if statistics.mean(vols) else 9
    hit = green >= STAIR_GREEN and dip < STAIR_MAX_DIP and cv < STAIR_VOL_CV
    if raw: return hit, f"{green:.0%} of 5-min candles up, biggest dip {dip:.0%}, volume evenness {cv:.2f}", green, dip
    return hit, f"{green:.0%} of 5-min candles up, biggest dip {dip:.0%}, volume evenness {cv:.2f}"

def rug_risk(F, stair_green, stair_dip):
    why = []
    if F.get("fdv") and F.get("reserve", 0) / F["fdv"] < RR_POOL_VS_VALUE: why.append(f"thin pool ({F['reserve'] / F['fdv']:.0%} of the coin's value)")
    if F.get("top10", 0) > RR_TOP10: why.append(f"top 10 wallets hold {F['top10']:.0%}")
    if F.get("dev_hold") is not None and F["dev_hold"] > RR_CREATOR: why.append(f"creator still holds {F['dev_hold']:.1%}")
    if stair_green is not None and stair_green >= RR_SOFT_STAIR[0] and stair_dip < RR_SOFT_STAIR[1]: why.append("smooth climb, close to the staircase bot pattern")
    return why

# ============================ positions ============================
def new_pos(F, path, trusted, mode="normal", shadow=False):
    e = F["price"] * (1 + SLIP)
    return {"mode": mode, "shadow": shadow, "id": f"{F['pool'][:8]}-{int(now())}", "pool": F["pool"], "mint": F["mint"], "sym": F["sym"], "path": path, "opened": now(), "entry": e,
            "qty0": (TRADE_USD * (1 - FEE) - NET_FEE) / e, "qty": None, "cost": TRADE_USD, "realized": 0.0, "peak": e,
            "stop": e * (1 + HARD_STOP), "flags": [], "log": [], "early": F.get("early", {}), "dev": F.get("dev"),
            "sold_early": [], "early_sold_tok": {}, "trusted": {w: {"tok": v["tok"], "top": v["top"]} for w, v in trusted.items()},
            "trusted_sold": [], "seen_tx": list(F.get("seen_tx", []))[-2000:], "liq_peak": F.get("reserve", 0), "last_good": None,
            "jump_n": 0, "pressure": 0, "next_holders": now(), "next_stair": now() + 60}

def sell(p, share, price, why, practice=True):
    q = min(p["qty"], p["qty0"] * share)
    if q <= 0: return
    p["qty"] -= q; p["realized"] += q * price * (1 - SLIP) * (1 - FEE) - NET_FEE
    p["log"].append(f"{ts()} sold {share:.0%} at {px(price)} ({price / p['entry'] - 1:+.0%}) — {why}")
    if practice and not p.get("shadow"): card(f"### 🔴 v2 {p['sym']}: sell {share:.0%} at {px(price)} ({price / p['entry'] - 1:+.0%}) — {why}")

def manage(st, p, d):
    if p["qty"] is None: p["qty"] = p["qty0"]
    if p.get("shadow") and p.get("parent"):          # shadow copies share the parent's holder/pro/alarm info (no extra data calls)
        par = next((x for x in st["open"] if x["id"] == p["parent"]), None)
        if par:
            for k in ("sold_early", "trusted_sold", "dev_sold"): p[k] = par.get(k, p.get(k))
            if "staircase" in par["flags"] and "staircase" not in p["flags"]: p["flags"].append("staircase")
    price, liq = d["price"], d["liq"]
    p["liq_peak"] = max(p["liq_peak"], liq)
    def out(why):
        if p["qty"] > 0: sell(p, p["qty"] / p["qty0"], price, why)
        p["why"] = why; return True
    # 1) drained pool: coins can't be sold
    if liq < max(1000, DRAINED * p["liq_peak"]):
        p["log"].append(f"{ts()} pool drained ({money(liq)} left, was {money(p['liq_peak'])}) — rug: remaining coins worth $0")
        card(f"### 🚨 v2 {p['sym']}: POOL DRAINED — remaining coins worth $0"); p["qty"] = 0; p["why"] = "pool drained (rug)"; return True
    # 2) fake-price guard
    if p["last_good"] and price > 2 * p["last_good"]:
        p["jump_n"] += 1
        if p["jump_n"] < 3 or liq < 0.5 * p["liq_peak"]: price = p["last_good"]
        else: p["jump_n"] = 0
    else: p["jump_n"] = 0
    p["last_good"] = price
    p["peak"] = max(p["peak"], price); g = price / p["entry"] - 1
    def once(f):
        if f in p["flags"]: return False
        p["flags"].append(f); return True
    # 3) scam alarms
    if liq < (1 - POOL_DROP) * p["liq_peak"]: return out(f"pool money down {1 - liq / p['liq_peak']:.0%} from its peak (drain warning)")
    if "staircase" in p["flags"]: return out("staircase bot pattern (smooth climb = farm before a drain)")
    if p.get("mode") in ("rug_user", "rug_blend"):        # rug-risk mode: sell fast at big gains
        g0 = price / p["entry"] - 1
        for k, (lvl, share) in enumerate(RUG_USER if p["mode"] == "rug_user" else RUG_BLEND):
            if g0 >= lvl and once(f"rr{k}"):
                sell(p, min(share, p["qty"] / p["qty0"]) if share < 1 else p["qty"] / p["qty0"], price, f"rug-risk mode: +{lvl:.0%} → sold {'the rest' if share >= 1 else f'{share:.0%}'}")
                if lvl >= 0.5: p["stop"] = max(p["stop"], p["entry"] * (1.03 if lvl < 1.5 else 1 + FLOOR))
        if p["qty"] <= p["qty0"] * 1e-9: p["why"] = "rug-risk mode: all sold at target"; return True
    if p.get("dev_sold"): return out("creator wallet sold")
    # 4) the pros
    pros_holding = [w for w in p["trusted"] if w not in p["trusted_sold"]]
    if p["trusted"]:
        tops = [w for w in p["trusted_sold"] if p["trusted"][w]["top"]]
        if tops or len(p["trusted_sold"]) >= 2: return out(f"{len(p['trusted_sold'])} trusted pro/early wallet(s) sold — following them out")
    if not pros_holding:
        if len(p["sold_early"]) >= EXIT_SELLERS: return out(f"{len(p['sold_early'])} of the 20 biggest holders sold half+ (no pros in this coin)")
        if len(p["sold_early"]) >= WARN_SELLERS and once("warn"): sell(p, 0.25, price, f"{len(p['sold_early'])} big holders selling — early warning")
        p["pressure"] = p["pressure"] + 1 if d["sells"] > d["buys"] else 0
        if p["pressure"] >= SELL_PRESSURE_CHECKS: return out("more sellers than buyers for 30 seconds — the crowd turned")
    # 5) profit lock (normal-risk coins)
    if p.get("mode") == "normal" and g >= STEP1_AT and once("s1"): sell(p, STEP1, price, "+50%: sold 25% — fees and risk covered"); p["stop"] = max(p["stop"], p["entry"] * 1.03)
    if p.get("mode") == "normal" and g >= STEP2_AT and once("s2"): sell(p, STEP2, price, "+100%: sold 25% — our $10 is back"); p["stop"] = max(p["stop"], p["entry"] * (1 + FLOOR))
    if price <= p["stop"]:
        return out("hard stop −25%" if "s1" not in p["flags"] else ("floor stop +40% (profit locked)" if "s2" in p["flags"] else "break-even stop"))
    if now() - p["opened"] > MAX_HOLD_H * 3600: return out("12-hour limit")
    return False

def holders_update(st, p):
    L = EB.ledger(p["pool"], p["mint"], big=True)
    seen = set(p["seen_tx"]); new = [t for t in L if t["tx"] not in seen]
    p["seen_tx"] = (p["seen_tx"] + [t["tx"] for t in new])[-3000:]
    for t in new:
        if t["buy"]: continue
        if t["w"] == p["dev"]: p["dev_sold"] = True
        if t["w"] in p["early"]:
            p["early_sold_tok"][t["w"]] = p["early_sold_tok"].get(t["w"], 0) + t["tok"]
            if p["early_sold_tok"][t["w"]] >= 0.5 * p["early"][t["w"]] and t["w"] not in p["sold_early"]: p["sold_early"].append(t["w"])
        if t["w"] in p["trusted"]:
            tr = p["trusted"][t["w"]]; tr["sold"] = tr.get("sold", 0) + t["tok"]
            if tr["sold"] >= 0.5 * tr["tok"] and t["w"] not in p["trusted_sold"]:
                p["trusted_sold"].append(t["w"]); p["log"].append(f"{ts()} trusted wallet {t['w'][:6]}… sold half+ of its coins")

# ============================ cards ============================
def wallet_lines(tr):
    if not tr: return ["- No trusted pro/early wallets in this coin yet (the scorebook is still learning) — using the 7-of-20 big-holder rule."]
    return [f"- {'⭐ TOP PRO' if v['top'] else 'PRO' if v['pro'] else 'EARLY'} `{w[:6]}…{w[-4:]}` — {v['n']} past coins, won {v['win']:.0%}, "
            f"profit {money(v['pnl'])}, early on {v['early']:.0%}; wallet ≈{money(v.get('wallet', 0))}, bet {money(v['bet'])} "
            f"({v.get('conv', 0):.0%} of wallet{' — high conviction' if v.get('conv', 0) >= CONVICTION else ''})" for w, v in tr.items()]

def buy_card(F, C, path, tr, stair_txt, took, why):
    L = [f"## 🦅 v2 BUY ({'A: Early Bird filters' if path == 'A' else 'B: smart money'}): {F['sym']}",
         f"*{ts()} UTC · pretend money · [chart](https://www.geckoterminal.com/solana/pools/{F['pool']})*", "",
         f"- {F['age']:.0f} min old · worth {money(F['fdv'])} · {money(F['reserve'])} in the pool", "", "### Checks"]
    L += [f"- ✅ **{n}:** {w}" for n, ok, w in C] + [f"- ✅ **Not a staircase bot pattern:** {stair_txt}", "", "### Pros & early wallets in this coin"]
    L += wallet_lines(tr)
    L += ["", "### The plan", f"- Buy $10 at ≈{px(F['price'])}. Hard stop −25%.",
          "- +50% → sell 25% (stop to break-even). +100% → sell 25% (our $10 back) → floor stop at +40%: can't lose after that.",
          "- Stay while the pros stay. If a top pro or 2 trusted wallets sell → sell everything." if tr else
          "- No pros in it: 3 big holders sell → sell 25%; 7 sell → sell everything.",
          "- Scam alarms → sell everything: pool money −20%, staircase pattern, creator sells. Drained pool = $0.",
          "", f"**Practice account:** {'BOUGHT' if took else 'not bought — ' + why}"]
    return "\n".join(L)

def close_card(p):
    r = p["realized"] / p["cost"] - 1
    return (f"## 📗 v2 CLOSED {p['sym']} ({'smart money' if p['path'] == 'B' else 'Early Bird'}) — {'WIN' if r > 0.01 else 'LOSS' if r < -0.01 else 'EVEN'} "
            f"{r:+.0%} ({money(p['realized'] - p['cost'])} on $10) · peak {p['peak'] / p['entry'] - 1:+.0%} · pros in coin: {len(p['trusted'])}\n" +
            "\n".join(f"- {x}" for x in p["log"]))

# ============================ main loop ============================
def load():
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"started": now(), "cash": START_CASH, "open": [], "closed": [], "coins": {}, "wallets": {}, "seen": {},
            "traded_syms": {}, "rejects": {}, "scans": 0, "checked": 0, "gaps": [], "ran_out": None}

def safety_only(st, p):
    """Entry B: the rug/safety parts of Early Bird, without the crowd/volume rules."""
    a = p["attributes"]; pool = a["address"]; mint = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
    age_h = (now() - EB.iso(a["pool_created_at"])) / 3600
    if age_h > B_MAX_AGE_H or f0(a.get("reserve_in_usd")) < EB.MIN_RESERVE: return None
    BL = EB.ledger(pool, mint, big=True)
    ingest(st, pool, mint, BL, f0(a.get("base_token_price_usd")), f0(a.get("reserve_in_usd")), sym=a["name"].split(" / ")[0])
    tr = trusted_in(st, pool, BL, window_min=B_WINDOW_MIN)
    strong = [w for w, v in tr.items() if v["conv"] >= CONVICTION or v["wallet"] >= BIG_WALLET_USD]
    if len(tr) < B_MIN_TRUSTED or not strong: return None
    # run the Early Bird rug/safety checks with the crowd/volume/size/late rules switched off
    keep = {k: getattr(EB, k) for k in ("MIN_VOL_M5", "MIN_VOL_H1", "MIN_FDV", "MAX_FDV", "MIN_BUYERS_M5", "BUYER_RATIO", "MAX_CHG_M5", "MAX_AGE_MIN")}
    try:
        EB.MIN_VOL_M5 = EB.MIN_VOL_H1 = EB.MIN_FDV = EB.MIN_BUYERS_M5 = EB.BUYER_RATIO = 0
        EB.MAX_FDV, EB.MAX_CHG_M5, EB.MAX_AGE_MIN = 1e12, 1e9, B_MAX_AGE_H * 60
        C, F, L = EB.evaluate(p, set())
    finally:
        for k, v in keep.items(): setattr(EB, k, v)
    if L is None: return None
    C = [c for c in C if c[0] not in ("Busy (video: min volume)", "A crowd is buying", "Size (video: min market cap)", "Not too late", "Brand new")]
    C.append(("Smart money is in", True, f"{len(tr)} trusted wallets bought in the last {B_WINDOW_MIN} min, {len(strong)} with real money / a big bet"))
    return C, F, L, tr

def scan(st):
    st["scans"] += 1
    pools, seen_now = [], set()
    for path, prm in (("/trending_pools", {"duration": "5m", "include": "base_token,dex"}), ("/new_pools", {"include": "base_token,dex"})):
        for p in (gget(path, prm) or {}).get("data") or []:
            if p["attributes"]["address"] not in seen_now: seen_now.add(p["attributes"]["address"]); pools.append(p)
    trusted_known = sum(1 for w in list(st["wallets"])[:20000] if profile(st, w)) if st["scans"] % 10 == 1 else st.get("n_trusted", 0)
    st["n_trusted"] = trusted_known
    b_checks = 0
    fed = 0
    for p in pools:                                  # feed the scorebook with real coins (not only the ones we buy)
        a = p["attributes"]; pool = a["address"]
        if fed >= 3 or not budget(4): break
        if pool in st["coins"] or f0(a.get("reserve_in_usd")) < EB.MIN_RESERVE: continue
        if (now() - EB.iso(a["pool_created_at"])) / 3600 > B_MAX_AGE_H: continue
        mint = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
        ingest(st, pool, mint, EB.ledger(pool, mint, big=True), f0(a.get("base_token_price_usd")), f0(a.get("reserve_in_usd")), sym=a["name"].split(" / ")[0]); fed += 1
    for p in pools:
        pool = p["attributes"]["address"]
        if now() < st["seen"].get(pool, 0) or any(x["pool"] == pool for x in st["open"]): continue
        if not budget(5): break
        C, F, L = EB.evaluate(p, set())
        st["checked"] += 1
        fails = [n for n, ok, _ in C if not ok]
        path, tr = None, {}
        BL = None
        if L is not None:
            BL = EB.ledger(pool, F["mint"], big=True)
            ingest(st, pool, F["mint"], BL, F["price"], F["reserve"], sym=F["sym"])
            path = "A"
        elif trusted_known >= 5 and b_checks < 3 and set(fails) <= {"Busy (video: min volume)", "A crowd is buying", "Size (video: min market cap)", "Not too late"}:
            b_checks += 1; res = safety_only(st, p)
            if res: C, F, L, tr = res; path = "B"
        if path is None:
            for n in fails: st["rejects"][n] = st["rejects"].get(n, 0) + 1
            st["seen"][pool] = now() + 600; continue
        if now() - st["traded_syms"].get(F["sym"].lower(), 0) < 86400:
            st["seen"][pool] = now() + 86400; continue
        if path == "A": tr = trusted_in(st, pool, BL or [])
        hit, stxt, sgreen, sdip = staircase(pool, raw=True)
        if hit:
            st["rejects"]["Staircase bot pattern"] = st["rejects"].get("Staircase bot pattern", 0) + 1; st["seen"][pool] = now() + 86400; continue
        dp = dex_prices([F["mint"]]).get(F["mint"])
        if not dp or abs(dp["price"] / F["price"] - 1) > 0.05:
            st["rejects"]["Two price sources disagree"] = st["rejects"].get("Two price sources disagree", 0) + 1; st["seen"][pool] = now() + 600; continue
        st["seen"][pool] = now() + 86400; st["traded_syms"][F["sym"].lower()] = now()
        took, why = False, ""
        if len(st["open"]) >= MAX_OPEN: why = f"already {MAX_OPEN} open"
        else:
            if st["cash"] < TRADE_USD and not st["ran_out"]: st["ran_out"] = f"{ts()} UTC (day {(now() - st['started']) / 86400:.1f})"
            F["dev_hold"] = F.get("dev_hold")
            rr = rug_risk(F, sgreen, sdip)
            pos = new_pos(F, path, tr, mode="rug_user" if rr else "normal"); pos["rug_why"] = rr
            st["open"].append(pos); st["cash"] -= TRADE_USD; took = True
            if rr:      # same coin, safer blend, tracked side by side (no money)
                sh = new_pos(F, path, tr, mode="rug_blend", shadow=True); sh["parent"] = pos["id"]; st.setdefault("shadow", []).append(sh)
        rr_txt = (f"\n\n**⚠️ RUG-RISK MODE:** {', '.join(pos['rug_why'])} → sell 75% at +150%, the rest at +200% "
                  f"(the safer blend is tracked side by side)") if took and pos.get("rug_why") else ("\n\n**Normal-risk coin:** standard v2 profit lock." if took else "")
        card(buy_card(F, C, path, tr, stxt, took, why) + rr_txt); print(f"[{ts()}] v2 BUY {F['sym']} path {path} pros {len(tr)} took={took}", flush=True)
    st["seen"] = {k: v for k, v in st["seen"].items() if v > now()}

def tick(st):
    sh = st.setdefault("shadow", [])
    if not st["open"] and not sh: return
    d = dex_prices(list({p["mint"] for p in st["open"] + sh}))
    for p in list(sh):
        x = d.get(p["mint"])
        if x is not None and manage(st, p, x): sh.remove(p); st.setdefault("shadow_closed", []).append(p)
    for p in list(st["open"]):
        if now() >= p["next_holders"]: holders_update(st, p); p["next_holders"] = now() + HOLDERS_EVERY
        if now() >= p["next_stair"]:
            hit, txt = staircase(p["pool"]); p["next_stair"] = now() + STAIR_EVERY
            if hit and "staircase" not in p["flags"]: p["flags"].append("staircase"); p["log"].append(f"{ts()} staircase alarm: {txt}")
        x = d.get(p["mint"])
        if x is None:
            p.setdefault("gone", now())
            if now() - p["gone"] < 600: continue
            p["qty"] = 0; p["why"] = "price disappeared (rug)"; done = True
        else:
            p.pop("gone", None); done = manage(st, p, x)
        if done:
            st["open"].remove(p); st["closed"].append(p); st["cash"] += p["realized"]; card(close_card(p))
            print(f"[{ts()}] v2 CLOSED {p['sym']} {p['realized'] / p['cost'] - 1:+.0%}", flush=True)

def report(st):
    cl = st["closed"]; r = [p["realized"] / p["cost"] - 1 for p in cl]
    days = (now() - st["started"]) / 86400
    big = [x for x in r if x >= 1.0]
    def line(sub):
        rr = [p["realized"] / p["cost"] - 1 for p in sub]
        if not rr: return "no closed trades yet"
        return f"{len(rr)} trades · {sum(x > 0.01 for x in rr)} wins · avg {sum(rr) / len(rr):+.0%} · best {max(rr):+.0%} · worst {min(rr):+.0%} · total {sum(p['realized'] - p['cost'] for p in sub):+.2f}"
    txt = "\n".join([f"# 🦅 Meme v2 practice — day {days:.1f} of {TEST_DAYS}", f"*Updated {ts()} UTC · pretend money*", "",
        f"- **Practice account ($30 start, $10 trades):** {money(st['cash'])} cash + {len(st['open'])} open",
        f"- **All trades:** {line(cl)}",
        f"- **Early Bird entries (A):** {line([p for p in cl if p['path'] == 'A'])}",
        f"- **Smart-money entries (B):** {line([p for p in cl if p['path'] == 'B'])}",
        f"- **Trades with pros in the coin:** {line([p for p in cl if p['trusted']])}",
        f"- **Normal-risk coins (standard profit lock):** {line([p for p in cl if p.get('mode') == 'normal'])}",
        f"- **Rug-risk coins — your version (75% at +150%, rest at +200%):** {line([p for p in cl if p.get('mode') == 'rug_user'])}",
        f"- **Rug-risk coins — safer blend (same coins, tracked side by side):** {line(st.get('shadow_closed', []))}",
        f"- **🚀 +100% trades:** {len(big)} so far (≈{len(big) / max(days, 0.01) * 30:.0f} per month at this pace)",
        (f"- ⚠️ Account ran out of money at {st['ran_out']} — continuing in tracking mode." if st.get("ran_out") else ""),
        f"- Scorebook: {len(st['wallets'])} wallets seen across {len(st['coins'])} coins · trusted pro/early wallets: {st.get('n_trusted', 0)}",
        f"- Scans {st['scans']} · coins checked {st['checked']}", "", "## Why coins were skipped"] +
        [f"- {k}: {v}" for k, v in sorted(st["rejects"].items(), key=lambda kv: -kv[1])] +
        (["", "## Gaps"] + [f"- {g}" for g in st["gaps"]] if st["gaps"] else []))
    (DATA / "report.md").write_text(txt); return txt

def run(seconds):
    st = load()
    if st.get("alive") and now() - st["alive"] > 900: st["gaps"].append(f"{ts(st['alive'])} → {ts()} UTC")
    end = min(now() + seconds, st["started"] + TEST_DAYS * 86400); last_scan = last_save = 0
    while now() < end:
        try:
            tick(st)
            if now() - last_scan >= SCAN_EVERY: scan(st); collect(st); last_scan = now()
        except Exception as e: print("error:", repr(e), flush=True)
        st["alive"] = now()
        if now() - last_save > 60: STATE.write_text(json.dumps(st)); report(st); last_save = now()
        time.sleep(PRICE_EVERY)
    STATE.write_text(json.dumps(st)); print(report(st))
    if now() >= st["started"] + TEST_DAYS * 86400: print("WEEK DONE")

if __name__ == "__main__":
    if sys.argv[1] == "run": run(float(sys.argv[2]))
    else: print(report(load()))
