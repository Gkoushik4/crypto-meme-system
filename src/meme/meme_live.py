"""MEME PRACTICE SIMULATOR — live, present-day Solana meme coins, PRETEND money only.
Every 5 min: scan trending/new coins (DexScreener), research each one (safety via GoPlus, attention, timing),
buy with pretend money if every rule passes, then sell fast with the sell-first ladder (prices checked every minute).
Writes a research/trade card for every buy and sell.  Rules below are FIXED before the test starts (2026-10-19).
Run: python meme_live.py run SECONDS"""
import os, sys, json, time, math
from pathlib import Path
import requests

# ============================ RULES (frozen) ============================
START_CASH = 15.0            # Moonshot practice money
TRADE_USD = 7.50
MAX_OPEN = 2
TEST_DAYS = 7
SCAN_EVERY_S, PRICE_EVERY_S = 300, 60
BONDING_DEXES = {"pumpfun", "moonshot", "launchlab", "boop", "believe"}   # not graduated yet
MIN_LIQ, MIN_MCAP, MAX_MCAP = 50_000, 100_000, 50_000_000
MAX_AGE_H, MIN_VOL_H1 = 7 * 24, 50_000
MAX_CHG_M5, MAX_CHG_H1 = 15, 50                              # % already moved = late
COOLDOWN_H = 24
# exits: sell-first ladder
LADDER = [(0.25, 0.25), (0.50, 0.25), (1.00, 0.25)]          # (+gain, share of original position)
TRAIL = 0.20                                                  # last 25% trails 20% below the peak
HARD_STOP = -0.20
FAST_FAIL_MIN, FAST_FAIL_GAIN = 30, 0.15                      # not +15% within 30 min -> out
MAX_HOLD_H = 24
# Promising book ($10 -> $20-30): A-grade coins only
PROM_CASH, PROM_TRADE, PROM_MAX_OPEN = 20.0, 10.0, 2
PROM_BUY_RATIO, PROM_TOP10 = 2.0, 0.20
PROM_STOP, PROM_HALF_AT, PROM_SELL2_AT, PROM_SELL2, PROM_TRAIL = -0.30, 1.00, 2.00, 0.40, 0.25
# Early-Bird-style exits (price only), used for comparison in the shadow log
EB_STOP, EB_BE, EB_FREE, EB_SPIKE, EB_STALL_MIN, EB_MAX_H = -0.25, 0.50, 1.00, 0.50, 30, 6
NEAR_MISS_RULES = {"Attention growing", "More buyers than sellers", "Not late", "Busy"}
# costs (honest): slippage + DEX fee per side, plus network fee per transaction
SLIP, DEX_FEE, NET_FEE_USD = 0.01, 0.0025, 0.02

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
CARDS = DATA / "cards"; CARDS.mkdir(exist_ok=True)
STATE = DATA / "state.json"
S = requests.Session(); S.headers["User-Agent"] = "meme-practice/1.0"
now = time.time

def get(url, tries=4):
    for k in range(tries):
        try:
            r = S.get(url, timeout=20)
            if r.status_code == 429: time.sleep(5 * (k + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception:
            time.sleep(2 * (k + 1))
    return None

def ts(t=None): return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t or now()))
def money(x): return f"${x:,.0f}" if abs(x) >= 100 else f"${x:,.2f}"
def px(x): return f"${x:.10f}".rstrip("0") if x < 0.01 else f"${x:,.4f}"

# ============================ data ============================
def candidates():
    out, meta = [], {}
    for url, tag in (("https://api.dexscreener.com/token-profiles/latest/v1", "new profile"),
                     ("https://api.dexscreener.com/token-boosts/latest/v1", "newly boosted"),
                     ("https://api.dexscreener.com/token-boosts/top/v1", "top boosted")):
        for x in get(url) or []:
            if x.get("chainId") != "solana": continue
            a = x["tokenAddress"]
            if a not in meta: out.append(a); meta[a] = {"source": tag, "boost": x.get("totalAmount") or x.get("amount") or 0,
                                                        "links": [l.get("url") for l in (x.get("links") or []) if l.get("url")]}
    return out, meta

def pairs_for(addrs):
    best = {}
    for i in range(0, len(addrs), 30):
        for p in get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(addrs[i:i + 30])) or []:
            a = p.get("baseToken", {}).get("address")
            if a not in addrs: continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if a not in best or liq > ((best[a].get("liquidity") or {}).get("usd") or 0): best[a] = p
        time.sleep(0.3)
    return best

def safety(mint):
    g = (get(f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={mint}") or {}).get("result") or {}
    g = list(g.values())[0] if g else {}
    if not g: return None, ["no safety data"]
    st = lambda k: str((g.get(k) or {}).get("status", "1")) if isinstance(g.get(k), dict) else str(g.get(k, "1"))
    holders = [h for h in (g.get("holders") or []) if not h.get("tag") and not h.get("is_locked")]
    pcts = sorted([float(h.get("percent", 0)) for h in holders], reverse=True)
    creators = {c.get("address") for c in (g.get("creators") or [])}
    creator = sum(float(h.get("percent", 0)) for h in (g.get("holders") or []) if h.get("account") in creators)
    top10, big = sum(pcts[:10]), (pcts[0] if pcts else 0)
    checks = [
        ("Can't print more coins", st("mintable") == "0", "creators can't create new coins to dump on us"),
        ("Can't freeze wallets", st("freezable") == "0", "nobody can freeze our coins so we can't sell"),
        ("Can't block selling", st("balance_mutable_authority") == "0" and str(g.get("non_transferable", "1")) == "0" and not g.get("transfer_hook"),
         "no hidden switch that stops sells or changes balances"),
        ("Creator holds ≤ 5%", creator <= 0.05, f"creator holds {creator:.1%}"),
        ("Biggest wallet ≤ 10%", big <= 0.10, f"biggest normal wallet holds {big:.1%}"),
        ("Top 10 wallets ≤ 30%", top10 <= 0.30, f"top 10 wallets hold {top10:.1%}"),
    ]
    safety.last = {"top10": top10, "creator": creator, "big": big}
    return checks, [n for n, ok, _ in checks if not ok]

def research(a, p, meta):
    """All non-safety rules. Returns (checks, facts)."""
    liq = (p.get("liquidity") or {}).get("usd") or 0; mcap = p.get("marketCap") or p.get("fdv") or 0
    age_h = (now() * 1000 - (p.get("pairCreatedAt") or now() * 1000)) / 3.6e6
    v = p.get("volume") or {}; c = p.get("priceChange") or {}; tx = p.get("txns") or {}
    m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
    vm5, vh1 = v.get("m5") or 0, v.get("h1") or 0
    info = p.get("info") or {}
    socials = [s.get("type") for s in info.get("socials") or []] + (["website"] if info.get("websites") else [])
    facts = dict(name=p["baseToken"].get("name"), symbol=p["baseToken"].get("symbol"), dex=p.get("dexId"), liq=liq, mcap=mcap,
                 age_h=age_h, vol_m5=vm5, vol_h1=vh1, vol_h6=v.get("h6") or 0, vol_h24=v.get("h24") or 0, chg_m5=c.get("m5") or 0, chg_h1=c.get("h1") or 0, chg_h24=c.get("h24") or 0,
                 buys_m5=m5.get("buys", 0), sells_m5=m5.get("sells", 0), buys_h1=h1.get("buys", 0), sells_h1=h1.get("sells", 0),
                 socials=socials, source=meta.get("source"), boost=meta.get("boost"), url=p.get("url"), price=float(p.get("priceUsd") or 0))
    pace = (vm5 * 12) / vh1 if vh1 else 0
    checks = [
        ("Graduated", p.get("dexId") not in BONDING_DEXES, f"trading on {p.get('dexId')}" + (" — still on the launch curve, where most rugs happen" if p.get("dexId") in BONDING_DEXES else " — it survived launch and moved to a real market")),
        ("Enough money in the pool", liq >= MIN_LIQ, f"{money(liq)} liquidity" + (" — we can sell easily" if liq >= MIN_LIQ else " — too thin, selling could crash the price")),
        ("Right size", MIN_MCAP <= mcap <= MAX_MCAP, f"coin is worth {money(mcap)}" + (" — room to grow" if MIN_MCAP <= mcap <= MAX_MCAP else (" — too tiny" if mcap < MIN_MCAP else " — already huge"))),
        ("New (present-day)", age_h <= MAX_AGE_H, f"{age_h:.1f} hours old"),
        ("Busy", vh1 >= MIN_VOL_H1, f"{money(vh1)} traded in the last hour"),
        ("Attention growing", pace >= 1.0, f"last 5 min traded at {pace:.1f}× the hour's pace" + (" — attention is speeding up" if pace >= 1 else " — attention is slowing down")),
        ("More buyers than sellers", m5.get("buys", 0) > m5.get("sells", 0) and h1.get("buys", 0) > h1.get("sells", 0),
         f"last 5 min {m5.get('buys', 0)} buys vs {m5.get('sells', 0)} sells; last hour {h1.get('buys', 0)} vs {h1.get('sells', 0)}"),
        ("Not late", (c.get("m5") or 0) < MAX_CHG_M5 and (c.get("h1") or 0) < MAX_CHG_H1,
         f"price {c.get('m5') or 0:+.0f}% in 5 min, {c.get('h1') or 0:+.0f}% in 1 hour" + (" — not chasing" if (c.get("m5") or 0) < MAX_CHG_M5 and (c.get("h1") or 0) < MAX_CHG_H1 else " — already pumped, we'd be buying from early buyers")),
    ]
    return checks, facts

# ============================ cards ============================
def card(text):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with open(CARDS / f"{day}.md", "a") as f: f.write(text + "\n\n---\n\n")

def buy_card(f, checks, sc, book_took, why_not):
    L = [f"## 🟢 RESEARCH + BUY: {f['symbol']} ({f['name']})", f"*{ts()} UTC · pretend money · [chart]({f['url']})*", "",
         "### What it is",
         f"- Found via DexScreener **{f['source']}**" + (f" (team paid for {f['boost']} boosts)" if f.get("boost") else "") + ".",
         f"- {f['age_h']:.1f} hours old, worth {money(f['mcap'])}, {money(f['liq'])} in the pool, trading on {f['dex']}.",
         f"- Socials: {', '.join(f['socials']) if f['socials'] else 'none listed (a warning sign — no community to grow)'}.",
         f"- Price: {f['chg_m5']:+.0f}% (5 min), {f['chg_h1']:+.0f}% (1 hour), {f['chg_h24']:+.0f}% (24 hours).", "",
         "### Safety checks (can they scam us?)"] + [f"- ✅ **{n}:** {w}" for n, ok, w in sc] + ["", "### Timing & attention (is now the moment?)"] + \
        [f"- ✅ **{n}:** {w}" for n, ok, w in checks] + ["",
         "### The plan (set before buying)",
         f"- Buy {money(TRADE_USD)} at about {px(f['price'])}.",
         "- Sell 25% at +25%, 25% at +50%, 25% at +100% — take money off the table early.",
         "- Last 25% rides with a stop 20% below its highest price (to try to catch the top).",
         "- Hard stop −20%. If it isn't up +15% within 30 minutes, sell everything (the hype failed). Always out within 24 h.",
         "", f"**Practice account:** {'BOUGHT' if book_took else 'not bought — ' + why_not} (every passing coin is also tracked in the shadow log)."]
    L += ["", "### How to spot this yourself",
          "> A coin that already survived launch, is safe on every check, has real money in its pool, and where buyers are speeding up "
          "*right now* — but the price hasn't run yet. Plan your sells before you buy."]
    return "\n".join(L)

def sell_card(pos, part, price, reason):
    gain = price / pos["entry"] - 1
    return (f"### 🔴 SELL {int(part * 100)}% of {pos['symbol']} at {px(price)} ({gain:+.0%}) — {reason}\n"
            f"- Held {(now() - pos['opened']) / 60:.0f} min. {'Locked in profit.' if gain > 0 else 'Cut the loss early — small losses keep us in the game.'}")

def close_card(pos):
    r = pos["realized"] / pos["cost"] - 1
    lesson = ("The ladder took profits on the way up — that's how you sell near the top without guessing it." if pos["steps"] >= 2 and r > 0 else
              "It went up but not far; the trailing stop/ladder still kept a profit." if r > 0 else
              "Hype faded fast — the 30-minute rule got us out before it got worse." if pos["exit_reason"].startswith("not up") else
              "Hit the −20% stop. Most meme coins fail — small fixed losses are the price of finding the winners.")
    return (f"## 📗 CLOSED {pos['symbol']} — {'WIN' if r > 0.005 else 'LOSS' if r < -0.005 else 'EVEN'} {r:+.0%} "
            f"({money(pos['realized'] - pos['cost'])} on {money(pos['cost'])}) · peak was {pos['peak'] / pos['entry'] - 1:+.0%}\n"
            f"- **Lesson:** {lesson}")

# ============================ positions ============================
def open_pos(f, mint, book, style="Ladder", cost=TRADE_USD, tag=""):
    entry = f["price"] * (1 + SLIP)
    qty = (cost * (1 - DEX_FEE) - NET_FEE_USD) / entry
    return {"mint": mint, "symbol": f["symbol"], "book": book, "style": style, "tag": tag, "opened": now(), "entry": entry,
            "qty0": qty, "qty": qty, "cost": cost, "realized": 0.0, "peak": entry, "peak_t": now(), "steps": 0, "flags": [],
            "stop": entry * (1 + (PROM_STOP if style == "Promising" else EB_STOP if style == "EarlyBird" else HARD_STOP)),
            "hist": [], "exit_reason": "", "url": f["url"]}

def manage_any(pos, price, quiet=False):
    if pos.get("style", "Ladder") == "Ladder": return manage(pos, price, quiet)
    if price > pos["peak"]: pos["peak"], pos["peak_t"] = price, now()
    g, gp = price / pos["entry"] - 1, pos["peak"] / pos["entry"] - 1
    pos["hist"] = (pos["hist"] + [[now(), price]])[-5:]
    def once(f):
        if f in pos["flags"]: return False
        pos["flags"].append(f); return True
    reason = None
    if pos["style"] == "Promising":
        if g >= PROM_HALF_AT and once("half"): sell(pos, 0.5, price, "+100%: half sold — our $10 is back", quiet); pos["stop"] = max(pos["stop"], pos["entry"] * 1.03)
        if g >= PROM_SELL2_AT and once("two"): sell(pos, PROM_SELL2, price, "+200%: sold 40% more — target reached", quiet)
        if "two" in pos["flags"]: pos["stop"] = max(pos["stop"], pos["peak"] * (1 - PROM_TRAIL))
        if price <= pos["stop"]: reason = "stop −30%" if "half" not in pos["flags"] else "protective stop"
        elif now() - pos["opened"] > MAX_HOLD_H * 3600: reason = "24-hour limit"
    else:  # EarlyBird-style, price only
        if gp >= EB_BE: pos["stop"] = max(pos["stop"], pos["entry"] * 1.03)
        if g >= EB_FREE and once("free"): sell(pos, 0.5, price, "+100%: half sold (free ride)", quiet)
        old = [x for x in pos["hist"] if now() - x[0] <= 150]
        if old and price >= old[0][1] * (1 + EB_SPIKE) and once("spike"): sell(pos, 0.25, price, "spike: sold 25% into strength", quiet)
        if now() - pos["peak_t"] > EB_STALL_MIN * 60 and gp > 0 and once("stall"): sell(pos, 0.5, price, "no new high 30 min: sold half", quiet)
        trail = 0.30 if gp < 1 else 0.25 if gp < 3 else 0.20
        if gp > 0.2: pos["stop"] = max(pos["stop"], pos["peak"] * (1 - trail))
        if price <= pos["stop"]: reason = "stop"
        elif now() - pos["opened"] > EB_MAX_H * 3600: reason = "6-hour limit"
    if reason and pos["qty"] > 1e-12:
        sell(pos, pos["qty"] / pos["qty0"], price, reason, quiet); pos["exit_reason"] = reason
    return pos["qty"] <= 1e-12 * pos["qty0"] + 1e-18

def sell(pos, share_of_original, price, reason, quiet=False):
    q = min(pos["qty"], pos["qty0"] * share_of_original)
    got = q * price * (1 - SLIP) * (1 - DEX_FEE) - NET_FEE_USD
    pos["qty"] -= q; pos["realized"] += got
    if not quiet: card(sell_card(pos, share_of_original, price, reason))
    return got

def manage(pos, price, quiet=False):
    """Apply the sell ladder. Returns True when fully closed."""
    pos["peak"] = max(pos["peak"], price); g = price / pos["entry"] - 1
    age_min = (now() - pos["opened"]) / 60
    while pos["steps"] < len(LADDER) and g >= LADDER[pos["steps"]][0]:
        lvl, share = LADDER[pos["steps"]]; sell(pos, share, price, f"ladder step {pos['steps'] + 1} (+{lvl:.0%})", quiet); pos["steps"] += 1
    reason = None
    if g <= HARD_STOP: reason = "hard stop −20%"
    elif pos["steps"] == len(LADDER) and price <= pos["peak"] * (1 - TRAIL): reason = "trailing stop (20% below peak)"
    elif pos["steps"] == 0 and age_min >= FAST_FAIL_MIN and pos["peak"] / pos["entry"] - 1 < FAST_FAIL_GAIN: reason = "not up 15% in 30 min"
    elif age_min >= MAX_HOLD_H * 60: reason = "24-hour limit"
    if reason and pos["qty"] > 1e-12:
        sell(pos, pos["qty"] / pos["qty0"], price, reason, quiet); pos["exit_reason"] = reason
    return pos["qty"] <= 1e-12 * pos["qty0"] + 1e-18

# ============================ main loop ============================
def load():
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"started": now(), "cash": START_CASH, "open": [], "closed": [], "shadow_open": [], "shadow_closed": [],
            "prom_cash": PROM_CASH, "prom_open": [], "prom_closed": [], "nm_open": [], "nm_closed": [],
            "seen": {}, "rejects": {}, "scans": 0, "coins_checked": 0, "gaps": []}

def save(st): STATE.write_text(json.dumps(st))

def prices(mints):
    if not mints: return {}
    best = pairs_for(list(set(mints)))
    # RUG GUARD: a pool with under $1,000 left is drained — its price is fake and coins can't be sold
    return {a: (float(p.get("priceUsd") or 0) if ((p.get("liquidity") or {}).get("usd") or 0) >= 1000 else "DRAINED")
            for a, p in best.items() if p.get("priceUsd")}

def scan(st):
    st["scans"] += 1
    addrs, meta = candidates()
    fresh = [a for a in addrs if now() >= st["seen"].get(a, 0)]     # 'seen' = time we may look at this coin again
    best = pairs_for(fresh)
    for a in fresh:
        p = best.get(a)
        if not p: continue
        st["coins_checked"] += 1
        checks, f = research(a, p, meta.get(a, {}))
        fails = [n for n, ok, _ in checks if not ok]
        if fails:
            for n in fails: st["rejects"][n] = st["rejects"].get(n, 0) + 1
            st["seen"][a] = now() + 1800      # failed timing/size rules: look again in 30 min
            if len(fails) == 1 and fails[0] in NEAR_MISS_RULES and not any(x["mint"] == a for x in st["nm_open"]):
                sc, sfails = safety(a); time.sleep(1.0)
                if sc is not None and not sfails:          # safe coin that missed only one timing rule -> track it
                    st["nm_open"].append(open_pos(f, a, "nearmiss", tag=fails[0])); st["seen"][a] = now() + 6 * 3600
            continue
        sc, sfails = safety(a); time.sleep(1.0)
        if sc is None or sfails:
            for n in sfails: st["rejects"][n] = st["rejects"].get(n, 0) + 1
            st["seen"][a] = now() + 6 * 3600; continue      # unsafe: ignore for 6 hours
        held = any(x["mint"] == a for x in st["open"] + st["shadow_open"])
        if held: continue
        st["seen"][a] = now() + COOLDOWN_H * 3600
        took, why_not = False, ""
        if len(st["open"]) >= MAX_OPEN: why_not = f"already {MAX_OPEN} coins open"
        elif st["cash"] < TRADE_USD: why_not = "not enough practice cash"
        else:
            pos = open_pos(f, a, "practice"); st["cash"] -= TRADE_USD; st["open"].append(pos); took = True
        for style in ("Ladder", "EarlyBird", "Promising"):
            st["shadow_open"].append(open_pos(f, a, "shadow", style=style))
        # Promising book: A-grade only
        sf = getattr(safety, "last", {})
        grade = {"buyers ≥ 2× sellers (5 min)": f["buys_m5"] >= PROM_BUY_RATIO * max(f["sells_m5"], 1),
                 "top 10 wallets < 20%": sf.get("top10", 1) < PROM_TOP10,
                 "has socials": bool(f["socials"]),
                 "volume growing (5m > 1h > 6h > 24h pace)": f["vol_m5"] * 12 > f["vol_h1"] and f["vol_h1"] * 6 > f["vol_h6"] and f["vol_h6"] * 4 > f["vol_h24"]}
        if all(grade.values()):
            if len(st["prom_open"]) < PROM_MAX_OPEN and st["prom_cash"] >= PROM_TRADE:
                st["prom_open"].append(open_pos(f, a, "promising", style="Promising", cost=PROM_TRADE)); st["prom_cash"] -= PROM_TRADE
                card(f"## ⭐ PROMISING BUY: {f['symbol']} — $10 aiming for $20–30\n" + "\n".join(f"- ✅ {k}" for k in grade) +
                     "\n- Plan: sell half at +100% ($10 back), 40% more at +200%, trail the rest; stop −30%.")
            else: card(f"## ⭐ {f['symbol']} was A-grade but the Promising book was full.")
        else:
            why_not += "" if took else ""
        card(buy_card(f, checks, sc, took, why_not) + "\n\n*A-grade check:* " + ", ".join(f"{'✅' if v else '❌'} {k}" for k, v in grade.items()))
        print(f"[{ts()}] PASS {f['symbol']} mcap {money(f['mcap'])} took={took}", flush=True)

def tick(st):
    allpos = st["open"] + st["shadow_open"] + st["prom_open"] + st["nm_open"]
    if not allpos: return
    pr = prices([p["mint"] for p in allpos])
    for lst, done, practice in ((st["open"], st["closed"], True), (st["shadow_open"], st["shadow_closed"], False),
                                (st["prom_open"], st["prom_closed"], "prom"), (st["nm_open"], st["nm_closed"], False)):
        still = []
        for p in lst:
            price = pr.get(p["mint"])
            if price is None:                       # coin vanished (pulled liquidity) -> count as a total loss after 30 min
                p.setdefault("missing_since", now())
                if now() - p["missing_since"] > 1800:
                    p["exit_reason"] = "price disappeared (likely rug)"; p["qty"] = 0
                    done.append(p)
                    if practice == "prom": card("⭐ " + close_card(p))
                    elif practice: card(close_card(p))
                else: still.append(p)
                continue
            p.pop("missing_since", None)
            if price == "DRAINED":
                p["qty"] = 0; p["exit_reason"] = "pool drained (rug) — remaining coins worth $0"; done.append(p)
                if practice == "prom": st["prom_cash"] += p["realized"]; card("⭐ 🚨 " + close_card(p))
                elif practice: st["cash"] += p["realized"]; card("🚨 " + close_card(p))
                continue
            last = p.get("last_good")
            if last and price > 2 * last:
                p["jump_n"] = p.get("jump_n", 0) + 1
                if p["jump_n"] < 3: price = last          # not trusted until it holds for 3 checks
                else: p["jump_n"] = 0
            else: p["jump_n"] = 0
            p["last_good"] = price
            if manage_any(p, price, quiet=not practice):
                done.append(p)
                if practice == "prom": st["prom_cash"] += p["realized"]; card("⭐ " + close_card(p))
                elif practice: st["cash"] += p["realized"]; card(close_card(p)); print(f"[{ts()}] CLOSED {p['symbol']} {p['realized'] / p['cost'] - 1:+.0%}", flush=True)
            else: still.append(p)
        lst[:] = still
    # cash from partial sells (practice): realized money returns as it is sold
    st["cash_partials"] = sum(p["realized"] for p in st["open"])

def report(st):
    def stats(cl):
        r = [p["realized"] / p["cost"] - 1 for p in cl]
        if not r: return "no closed trades yet"
        w = [x for x in r if x > 0.005]
        return (f"{len(r)} trades · {len(w)} wins ({len(w) / len(r):.0%}) · average {sum(r) / len(r):+.1%} per trade · "
                f"best {max(r):+.0%} · worst {min(r):+.0%} · total {sum(p['realized'] - p['cost'] for p in cl):+.2f} on {money(TRADE_USD)} trades")
    days = (now() - st["started"]) / 86400
    L = [f"# 🐸 Meme practice — day {days:.1f} of {TEST_DAYS}", f"*Updated {ts()} UTC · pretend money*", "",
         f"- **Practice account ($15 start):** {money(st['cash'])} cash + {len(st['open'])} open coin(s)",
         f"- **Practice trades:** {stats(st['closed'])}",
         f"- **Shadow log (every coin that passed, no limits):** {stats(st['shadow_closed'])}",
         f"- **Promising book ($20 start, $10 trades):** {money(st['prom_cash'])} cash + {len(st['prom_open'])} open · {stats(st['prom_closed'])}",
         f"- Scans: {st['scans']} · coins researched: {st['coins_checked']}", "", "## Same coins, different exit styles (shadow log)"] + \
        [f"- **{sty}:** {stats([p for p in st['shadow_closed'] if p.get('style', 'Ladder') == sty])}" for sty in ("Ladder", "EarlyBird", "Promising")] + \
        ["", "## Near-misses (safe, failed only one timing rule)"] + \
        [f"- **failed '{r}':** {stats([p for p in st['nm_closed'] if p['tag'] == r])}" for r in sorted({p['tag'] for p in st['nm_closed']})] + [
         "## Why coins were rejected"] + [f"- {k}: {v}" for k, v in sorted(st["rejects"].items(), key=lambda kv: -kv[1])]
    if st.get("gaps"): L += ["", "## Gaps (simulator was not running)"] + [f"- {g}" for g in st["gaps"]]
    (DATA / "report.md").write_text("\n".join(L))
    return "\n".join(L)

def run(seconds):
    st = load()
    if st.get("last_alive") and now() - st["last_alive"] > 15 * 60:
        st["gaps"].append(f"{ts(st['last_alive'])} → {ts()} UTC ({(now() - st['last_alive']) / 60:.0f} min)")
    end = min(now() + seconds, st["started"] + TEST_DAYS * 86400)
    last_scan = 0
    while now() < end:
        try:
            if now() - last_scan >= SCAN_EVERY_S: scan(st); last_scan = now()
            tick(st)
        except Exception as e:
            print("error:", repr(e), flush=True)
        st["last_alive"] = now(); save(st); report(st)
        time.sleep(PRICE_EVERY_S)
    save(st); print(report(st))
    if now() >= st["started"] + TEST_DAYS * 86400: print("WEEK DONE")

if __name__ == "__main__":
    if sys.argv[1] == "run": run(float(sys.argv[2]))
    elif sys.argv[1] == "report": print(report(load()))
