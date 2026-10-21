"""LEVEL 3 — live PRACTICE copy-trading watcher (no real money, no keys).
Every cycle: look for new trades by our 10 skilled traders (+5 bench), run the trade check, open pretend positions
in 4 versions, manage exits on 5-minute candles, and write a plain-English trade card for every decision.
Run:  python l3_live.py live            (loops forever, every CYCLE_MIN minutes)
      python l3_live.py replay DAYS     (test: replays the last DAYS days as if live)"""
import os, sys, json, time, math
from pathlib import Path
import numpy as np, pandas as pd, requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules as R
import regime as RG

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("L3_DATA", HERE / "data")); DATA.mkdir(parents=True, exist_ok=True)
CARDS = DATA / "cards"; CARDS.mkdir(exist_ok=True)
API = "https://api.hyperliquid.xyz/info"
S = requests.Session()
MS = lambda t: int(pd.Timestamp(t).timestamp() * 1000)
TS = lambda m: pd.to_datetime(m, unit="ms")

def post(body):
    for k in range(6):
        try:
            r = S.post(API, json=body, timeout=30)
            if r.status_code == 429: time.sleep(4 * (k + 1)); continue
            r.raise_for_status(); return r.json()
        except Exception:
            time.sleep(3 * (k + 1))
    return None

# ============================ data ============================
class Market:
    """Candles + fills. In replay mode nothing after `now` is ever used (no peeking)."""
    def __init__(self): self.cache = {}
    def candles(self, coin, iv, start, now):
        key = (coin, iv); have = self.cache.get(key)
        need_from = MS(start)
        if have is None or have.index[0] > TS(need_from) + pd.Timedelta(hours=8) or have.index[-1] < pd.Timestamp(now) - pd.Timedelta(minutes=10):
            a = need_from if have is None or have.index[0] > TS(need_from) + pd.Timedelta(hours=8) else MS(have.index[-1])
            data = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": iv, "startTime": a, "endTime": MS(now) + 1}}) or []
            time.sleep(0.6)
            if data:
                df = pd.DataFrame(data)
                new = pd.DataFrame({"open": df.o.astype(float).values, "high": df.h.astype(float).values, "low": df.l.astype(float).values,
                                    "close": df.c.astype(float).values, "volume": df.v.astype(float).values}, index=TS(df.t).values)
                have = new if have is None else pd.concat([have, new]).groupby(level=0).last().sort_index()
                self.cache[key] = have
        if have is None: return pd.DataFrame()
        step = {"5m": "5min", "1h": "1h", "4h": "4h"}[iv]
        closed = have[have.index + pd.Timedelta(step) <= pd.Timestamp(now)]          # only finished bars
        return closed[closed.index >= pd.Timestamp(start)]
    def fills(self, trader, start, now):
        out, t0 = [], MS(start)
        for _ in range(10):
            page = post({"type": "userFillsByTime", "user": trader, "startTime": t0, "endTime": MS(now)}) or []
            time.sleep(0.6); out += page
            if len(page) < 2000: break
            t0 = max(f["time"] for f in page) + 1
        return sorted([f for f in out if f["time"] <= MS(now)], key=lambda f: f["time"])

class ReplayMarket(Market):
    """Downloads once, then serves data as if time were `now`."""
    def __init__(self): super().__init__(); self.fill_cache = {}
    def fills(self, trader, start, now):
        if trader not in self.fill_cache:
            self.fill_cache[trader] = Market.fills(self, trader, start, pd.Timestamp.utcnow().tz_localize(None))
        return [f for f in self.fill_cache[trader] if MS(start) <= f["time"] <= MS(now)]
    def candles(self, coin, iv, start, now):
        key = (coin, iv)
        if key not in self.cache or self.cache[key].index[0] > pd.Timestamp(start) + pd.Timedelta(hours=8):
            Market.candles(self, coin, iv, start, pd.Timestamp.utcnow().tz_localize(None))
        have = self.cache.get(key)
        if have is None: return pd.DataFrame()
        step = {"5m": "5min", "1h": "1h", "4h": "4h"}[iv]
        closed = have[have.index + pd.Timedelta(step) <= pd.Timestamp(now)]
        return closed[closed.index >= pd.Timestamp(start)]

# ============================ the trade check ============================
KR = None
def kronos(c4):
    """8 Kronos forecasts, 24h ahead (6 x 4h). Returns (avg move, share pointing up)."""
    global KR
    if len(c4) < 200: return None
    try:
        if KR is None:
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1"); sys.path.insert(0, os.environ.get("KRONOS_DIR", "/root/Kronos"))
            import torch; torch.set_num_threads(2); torch.manual_seed(0)
            from model import Kronos, KronosTokenizer, KronosPredictor
            W = os.environ.get("KRONOS_WEIGHTS")          # local backup (kronos-core/weights) if set, else Hugging Face
            KR = KronosPredictor(Kronos.from_pretrained(f"{W}/Kronos-small" if W else "NeoQuasar/Kronos-small"),
                                 KronosTokenizer.from_pretrained(f"{W}/Kronos-Tokenizer-base" if W else "NeoQuasar/Kronos-Tokenizer-base"),
                                 device="cpu", max_context=512)
        df = c4.tail(400)
        x = df[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
        xs = pd.Series(df.index); ys = pd.Series(pd.date_range(df.index[-1] + pd.Timedelta(hours=4), periods=6, freq="4h"))
        out = KR.predict_batch([x] * R.KRONOS_SAMPLES, [xs] * R.KRONOS_SAMPLES, [ys] * R.KRONOS_SAMPLES, pred_len=6,
                               T=1.0, top_p=0.9, sample_count=1, verbose=False)
        r = np.array([o.close.iloc[-1] / df.close.iloc[-1] - 1 for o in out])
        return float(r.mean()), float((r > 0).mean())
    except Exception as e:
        print("Kronos unavailable:", e); return None

def atr_pct(c1, t):
    c = c1[c1.index < t].tail(15)
    if len(c) < 5: return float("nan")
    tr = np.maximum(c.high - c.low, np.maximum((c.high - c.close.shift()).abs(), (c.low - c.close.shift()).abs()))
    return float(tr.iloc[1:].mean() / c.close.iloc[-1])

def check_trade(mk, sig, now, trader_fills):
    """Returns list of checks: (name, passed, plain-English explanation) and info for 'really good'."""
    coin, d, t = sig["coin"], sig["dir"], sig["t"]
    c4 = mk.candles(coin, "4h", now - pd.Timedelta(days=80), now); b4 = mk.candles("BTC", "4h", now - pd.Timedelta(days=80), now)
    c1 = mk.candles(coin, "1h", now - pd.Timedelta(days=30), now)
    px_now = sig["px_now"]; word = "long (betting up)" if d == 1 else "short (betting down)"
    out, info = [], {}
    def up(df): return None if len(df) < R.TREND_BARS_4H else bool(df.close.iloc[-1] > df.close.tail(R.TREND_BARS_4H).mean())
    uc, ub = up(c4), up(b4)
    if uc is None or ub is None:
        out.append(("Trend", True, "Not enough price history to judge the trend, so this check was skipped."))
    else:
        ok = (uc or ub) if d == 1 else not (uc and ub)
        desc = (f"BTC is {'above' if ub else 'below'} its 50-day average" if coin == "BTC" else
                f"{coin} is {'above' if uc else 'below'} its 50-day average and BTC is {'above' if ub else 'below'} its 50-day average")
        out.append(("Trend", ok, f"{desc}. A {word} trade {'goes with' if ok else 'fights'} the market."))
        info["with_trend"] = (d == 1 and uc and ub) or (d == -1 and not uc and not ub)
    moved = d * (px_now / sig["px"] - 1)
    out.append(("Not late", moved <= R.LATE_ENTRY,
                f"Price moved {moved:+.2%} in the trader's favor before we could copy" +
                (" — small enough, we are not chasing." if moved <= R.LATE_ENTRY else " — too much, we'd be buying after the move (chasing).")))
    grp = {}
    for f in trader_fills:   # one entry per new position (partial fills at the same moment added together)
        if t - pd.Timedelta(days=30) <= TS(f["time"]) < t and (abs(float(f["startPosition"])) < 1e-12 or (f["coin"], f["time"]) in grp):
            grp[(f["coin"], f["time"])] = grp.get((f["coin"], f["time"]), 0) + float(f["sz"]) * float(f["px"])
    prior = list(grp.values())
    size = sig["notional"]
    if len(prior) >= 5:
        med = float(np.median(prior)); ratio = size / med if med else 1
        ok = ratio >= R.LOW_CONVICTION_X
        out.append(("Conviction", ok, f"Trader put in ${size:,.0f}, {ratio:.1f}× their usual new-trade size" +
                    (" — a real bet." if ratio >= 1 else " — a normal-ish bet." if ok else " — a tiny test bet, not real conviction.")))
        info["bigger_than_usual"] = ratio > 1
    else:
        out.append(("Conviction", True, "Not enough recent trades to compare size, so this check was skipped."))
    a_now = atr_pct(c1, t); hist = [atr_pct(c1, t - pd.Timedelta(days=k)) for k in (7, 14, 21, 28)]
    hist = [x for x in hist if not math.isnan(x)]
    if hist and not math.isnan(a_now):
        x = a_now / float(np.median(hist)); ok = x <= R.WILD_X
        out.append(("Calm enough", ok, f"Price swings are {x:.1f}× normal for {coin}" + (" — fine." if ok else " — unusually wild, stops get hit randomly.")))
    vol = float((c1.close * c1.volume)[c1.index >= t - pd.Timedelta(days=1)].sum()) if len(c1) else 0
    ok = vol >= R.MIN_VOLUME_24H
    out.append(("Enough trading", ok, f"${vol/1e6:,.1f}M traded in the last day" + (" — easy to get in and out." if ok else " — too thin, prices can jump.")))
    if all(p for _, p, _ in out):
        kv = kronos(c4)
        if kv is None:
            out.append(("Kronos", True, "Kronos forecast not available, so this check was skipped."))
        else:
            m, upshare = kv; agree = upshare if d == 1 else 1 - upshare
            ok = (m >= 0) if d == 1 else (m <= 0)
            ok = ok and agree >= 0.5
            n = round(agree * R.KRONOS_SAMPLES)
            out.append(("Kronos", ok, f"{n} of {R.KRONOS_SAMPLES} Kronos forecasts agree with the trade (average move next 24h {m:+.2%})" +
                        (" — Kronos agrees." if ok else " — Kronos disagrees.")))
            info["kronos_strong"] = agree >= R.KRONOS_STRONG
    info["passed"] = all(p for _, p, _ in out)
    info["really_good"] = info["passed"] and info.get("with_trend", False) and info.get("kronos_strong", False) and info.get("bigger_than_usual", False)
    return out, info

# ============================ positions ============================
def open_position(sig, px_now, c1, now, cash, weight):
    d = sig["dir"]
    stop_dist = max(R.STOP_ATR_MULT * atr_pct(c1, now), 0.004)
    if math.isnan(stop_dist): return None
    entry = px_now * (1 + d * R.SLIPPAGE)
    notional = min(cash * R.RISK_PER_TRADE * weight / stop_dist, R.MAX_NOTIONAL_X * cash / R.MAX_OPEN)
    return {"coin": sig["coin"], "dir": d, "trader": sig["trader"], "sig_id": sig["id"], "opened": str(now), "entry": entry,
            "stop": entry * (1 - d * stop_dist), "first_stop": entry * (1 - d * stop_dist),
            "target": entry * (1 + d * R.TAKE_PROFIT_R * stop_dist), "stop_dist": stop_dist, "best": entry,
            "notional": notional, "risk_usd": notional * stop_dist, "last_bar": str(now), "weight": weight}

def step_position(p, bars):
    """Walk new 5-minute bars. Returns closed dict or None."""
    d, entry, sd = p["dir"], p["entry"], p["stop_dist"]
    for t, b in bars[bars.index > pd.Timestamp(p["last_bar"])].iterrows():
        exit_px = why = None
        if (d == 1 and b.low <= p["stop"]) or (d == -1 and b.high >= p["stop"]):
            exit_px = min(p["stop"], b.open) if d == 1 else max(p["stop"], b.open)
            why = "stop-loss" if (p["stop"] - entry) * d < 0 else ("break-even stop" if abs(p["stop"] / entry - 1) < 0.002 else "trailing stop")
        elif (d == 1 and b.high >= p["target"]) or (d == -1 and b.low <= p["target"]):
            exit_px, why = p["target"], "take-profit (3× risk)"
        elif t >= pd.Timestamp(p["opened"]) + pd.Timedelta(days=R.MAX_HOLD_DAYS):
            exit_px, why = b.close, "time limit (7 days)"
        p["last_bar"] = str(t)
        if exit_px is not None:
            exit_px *= (1 - d * R.SLIPPAGE)
            ret = d * (exit_px / entry - 1) - 2 * R.FEE
            pnl = p.get("part_pnl", 0.0) + p["notional"] * p.get("frac", 1.0) * ret
            return {**p, "closed": str(t), "exit": exit_px, "ret": pnl / p["notional"], "R": pnl / (p["notional"] * sd), "pnl": pnl, "why": why}
        p["best"] = max(p["best"], b.high) if d == 1 else min(p["best"], b.low)
        gain_r = d * (p["best"] / entry - 1) / sd
        if p.get("scale") and not p.get("scaled") and gain_r >= 1:          # version 5: sell half at +1R
            lvl = entry * (1 + d * sd) * (1 - d * R.SLIPPAGE)
            p["part_pnl"] = p["notional"] * 0.5 * (d * (lvl / entry - 1) - 2 * R.FEE); p["frac"] = 0.5; p["scaled"] = True
        if gain_r >= R.BREAK_EVEN_AT_R:
            be = entry * (1 + d * 2 * R.FEE)
            p["stop"] = max(p["stop"], be) if d == 1 else min(p["stop"], be)
        if gain_r >= R.TRAIL_START_R:
            tr = p["best"] * (1 - d * R.TRAIL_R * sd)
            p["stop"] = max(p["stop"], tr) if d == 1 else min(p["stop"], tr)
    return None

# ============================ trade cards ============================
def fmt(x): return f"${x:,.4f}" if x < 1 else f"${x:,.2f}"
def tname(a, team): return f"{a[:6]}…{a[-4:]}" + ("" if a in team["main"] else " (bench)")

def entry_card(sig, checks, info, decisions, plan, team, now):
    prof = team["profiles"].get(sig["trader"], {})
    side = "LONG (bet price goes up)" if sig["dir"] == 1 else "SHORT (bet price goes down)"
    L = [f"## 📘 {sig['coin']} {side} — signal #{sig['id']}", f"*{now:%Y-%m-%d %H:%M} UTC · practice money only*", "",
         "### Who and what",
         f"- **Trader:** {tname(sig['trader'], team)} — {prof.get('months', '?')} months of history, profitable in "
         f"{prof.get('profitable_months', 0):.0%} of months, worst drop {prof.get('max_drawdown', 0):.0%}, skill score {prof.get('t_stat', 0):.1f}.",
         f"- **They opened** a new {sig['coin']} {'long' if sig['dir'] == 1 else 'short'} at {fmt(sig['px'])} "
         f"(${sig['notional']:,.0f}) at {sig['t']:%H:%M} UTC. Price when we saw it: {fmt(sig['px_now'])}.", "",
         "### The checks (the thinking)"]
    for name, ok, why in checks: L.append(f"- {'✅' if ok else '❌'} **{name}:** {why}")
    if info.get("really_good"): L.append("- ⭐ **Really good trade:** passed everything, with the trend, Kronos strongly agrees, and the trader bet big.")
    L += ["", "### What each practice version did"]
    for v, (took, why) in decisions.items(): L.append(f"- **{v}:** {'TOOK IT' if took else 'skipped'} — {why}")
    if plan:
        L += ["", "### The plan (set before entering)",
              f"- Entry ≈ {fmt(plan['entry'])}. Risk: ${plan['risk_usd']:.2f} (1% of the $85 account).",
              f"- **Stop-loss {fmt(plan['stop'])}** ({plan['stop_dist']:.1%} away = 1.5× the usual hourly swing). If hit, the idea was wrong — we're out.",
              f"- At +1× risk ({fmt(plan['entry'] * (1 + sig['dir'] * plan['stop_dist']))}) the stop moves to break-even.",
              f"- After +2× risk the stop trails 1× risk behind the best price.",
              f"- **Take-profit {fmt(plan['target'])}** (3× the risk). One win like this pays for three losses."]
    fails = [n for n, ok, _ in checks if not ok]
    L += ["", "### How to spot this yourself"]
    if not fails:
        L.append("> A proven trader opened a fresh position **with the trend**, price hadn't run yet, and the market was calm and busy. "
                 "That's the setup. Put your stop first (1.5× the hourly swing), then a target 3× further away.")
    else:
        L.append("> Warning signs here: **" + ", ".join(fails) + "**. Even good traders take trades like this — "
                 "the lesson is to notice these signs *before* you click buy, and pass.")
    return "\n".join(L)

def close_card(cs, checks_ok, fails, team):
    c = cs[0]
    res = "WIN" if c["R"] > 0.05 else ("LOSS" if c["R"] < -0.05 else "BREAK-EVEN")
    L = [f"## 📗 Closed {c['coin']} {'long' if c['dir'] == 1 else 'short'} (signal #{c['sig_id']}) — {res}",
         f"- Opened {c['opened'][:16]} at {fmt(c['entry'])}, closed {c['closed'][:16]} at {fmt(c['exit'])} by **{c['why']}**.",
         f"- Result: **{c['R']:+.2f}× the risk.** " + " · ".join(f"v{x['version'][0]}: ${x['pnl']:+.2f}" for x in cs)]
    if res == "WIN" and checks_ok:
        les = "Textbook: skilled trader + every check passed. This is the pattern to repeat."
    elif res == "WIN":
        les = f"It worked even though {', '.join(fails)} failed — don't count on that; one win doesn't make a bad sign good."
    elif res == "BREAK-EVEN":
        les = "Moving the stop to break-even at +1× risk protected us — a trade that went our way can't turn into a loss."
    elif checks_ok:
        les = "A good setup that still lost. That's normal — it's why we only risk 1%. Losses of about −1× are the cost of trading."
    else:
        les = f"The check warned us ({', '.join(fails)}). Lessons like this are why we skip those signs."
    L.append(f"- **Lesson:** {les}")
    return "\n".join(L)

# ============================ the engine ============================
VERSIONS = ["1 Copy every trade", "2 + emergency pause & stand-in", "3 + trade check", "4 + really-good while paused",
            "5 Copy every trade + scale out", "6 Copy every trade + stop-and-reverse", "7 REGIME (adapts to the market)"]   # 5 & 6 added 2026-10-20 (winners of the flip test)

class Engine:
    def __init__(self, mk, team, state_file):
        self.mk, self.team, self.sf = mk, team, state_file
        if state_file.exists():
            self.st = json.loads(state_file.read_text())
        else:
            self.st = {"last_ms": None, "next_id": 1, "signals": {},
                       "books": {v: {"cash": R.START_CASH, "open": [], "closed": []} for v in VERSIONS},
                       "shadow": [], "health": {}, "opens_log": {}, "subs": {}, "events": [], "card_log": []}
    def save(self): self.sf.write_text(json.dumps(self.st, default=str))
    def card(self, text, now, kind):
        self.st["card_log"].append({"t": str(now), "kind": kind, "text": text})
        with open(CARDS / f"{pd.Timestamp(now):%Y-%m-%d}.md", "a") as f: f.write(text + "\n\n---\n\n")
        notify(text, kind)
    def health(self, a): return self.st["health"].setdefault(a, {"eq": 1.0, "peak": 1.0, "paused": False, "pause_eq": None})
    def active_recent(self, a, now):
        return sum(1 for t in self.st["opens_log"].get(a, []) if pd.Timestamp(t) >= now - pd.Timedelta(days=30) and pd.Timestamp(t) < now)

    def refresh_subs(self, now):
        subs = self.st["subs"]
        for a in self.team["main"]:
            h = self.health(a)
            if h["paused"]:
                cur = subs.get(a)
                if cur is None or self.health(cur)["paused"] or self.active_recent(cur, now) < R.STANDIN_MIN_TRADES_30D:
                    used = set(subs.values()) - {cur}
                    free = [b for b in self.team["bench"] if b not in used and not self.health(b)["paused"]
                            and self.active_recent(b, now) >= R.STANDIN_MIN_TRADES_30D]
                    if free:
                        subs[a] = free[0]; self.event(now, f"{tname(free[0], self.team)} stands in for {tname(a, self.team)}")
                    elif cur is not None:
                        subs.pop(a); self.event(now, f"No active bench trader to stand in for {tname(a, self.team)}")
            elif a in subs:
                b = subs.pop(a); self.event(now, f"{tname(a, self.team)} is back; {tname(b, self.team)} returns to the bench")
    def event(self, now, msg):
        self.st["events"].append({"t": str(now), "msg": msg}); print(f"[{now:%m-%d %H:%M}] {msg}")

    def cycle(self, now):
        now = pd.Timestamp(now)
        since = TS(self.st["last_ms"]) if self.st["last_ms"] else now - pd.Timedelta(minutes=R.CYCLE_MIN)
        everyone = self.team["main"] + self.team["bench"]
        # 1) manage open positions + shadow positions on 5-minute bars
        closes = {}
        for book_name, book in self.st["books"].items():
            still = []
            for p in book["open"]:
                bars = self.mk.candles(p["coin"], "5m", pd.Timestamp(p["last_bar"]) - pd.Timedelta(minutes=10), now)
                c = step_position(p, bars)
                if c:
                    c["version"] = book_name; book["cash"] += c["pnl"]; book["closed"].append(c)
                    closes.setdefault(c["sig_id"], []).append(c)
                    if (book_name.startswith("6") or (book_name.startswith("7") and c.get("rev_ok"))) and c["why"] == "stop-loss" and not c.get("reversed"):
                        c1 = self.mk.candles(c["coin"], "1h", now - pd.Timedelta(days=30), now)
                        rs = {"id": c["sig_id"], "trader": c["trader"], "coin": c["coin"], "dir": -c["dir"]}
                        if len(still) < R.MAX_OPEN and len(c1) >= 50:
                            rp = open_position(rs, c["exit"], c1, pd.Timestamp(c["closed"]), book["cash"], 1.0)
                            if rp:
                                rp["reversed"] = True; still.append(rp)
                                self.card(f"### ↩️ v{book_name[0]} stop-and-reverse: {c['coin']} {'long' if c['dir'] == 1 else 'short'} was stopped out — flipped to "
                                          f"{'short' if c['dir'] == 1 else 'long'} at {fmt(c['exit'])} (one flip only)", now, "entry")
                else: still.append(p)
            book["open"] = still
        still = []
        for p in self.st["shadow"]:
            bars = self.mk.candles(p["coin"], "5m", pd.Timestamp(p["last_bar"]) - pd.Timedelta(minutes=10), now)
            c = step_position(p, bars)
            if c: self.trader_result(c["trader"], c["R"], now)
            else: still.append(p)
        self.st["shadow"] = still
        for sid, cs in closes.items():
            sg = self.st["signals"].get(str(sid), {})
            self.card(close_card(cs, sg.get("passed", True), sg.get("fails", []), self.team), now, "close")
        self.refresh_subs(now)
        # 2) new trades
        new = []
        for a in everyone:
            fl = self.mk.fills(a, now - pd.Timedelta(days=31), now)
            self.st["opens_log"][a] = sorted({str(TS(f["time"])) for f in fl if abs(float(f["startPosition"])) < 1e-12})
            for f in fl:
                if f["time"] <= MS(since) or abs(float(f["startPosition"])) > 1e-12: continue
                if f["coin"].startswith("@") or ":" in f["coin"] or "/" in f["coin"]: continue
                new.append((a, f, fl))
        seen = set()
        for a, f, fl in sorted(new, key=lambda x: x[1]["time"]):
            key = (a, f["coin"], f["time"])
            if key in seen: continue
            seen.add(key)
            same = [g for g in fl if g["coin"] == f["coin"] and g["time"] == f["time"] and g["side"] == f["side"]]
            self.handle_signal(a, f, sum(float(g["sz"]) * float(g["px"]) for g in same), fl, now)
        self.st["last_ms"] = MS(now); self.save()

    def trader_result(self, a, r, now):
        h = self.health(a); h["eq"] *= 1 + R.RISK_PER_TRADE * r; h["peak"] = max(h["peak"], h["eq"])
        dd = h["eq"] / h["peak"] - 1
        if not h["paused"] and dd <= -R.EMERGENCY_PAUSE_DD:
            h["paused"], h["pause_eq"] = True, h["eq"]
            self.event(now, f"{tname(a, self.team)} is in a bad period (down {dd:.0%} on copied trades) → watch-only")
        elif h["paused"] and (h["eq"] >= h["pause_eq"] * (1 + R.RESUME_GAIN) or h["eq"] >= h["peak"]):
            h["paused"] = False; self.event(now, f"{tname(a, self.team)} recovered → back on the team")

    def handle_signal(self, a, f, notional, fl, now):
        coin, d = f["coin"], 1 if f["side"] == "B" else -1
        c1 = self.mk.candles(coin, "1h", now - pd.Timedelta(days=30), now)
        c5 = self.mk.candles(coin, "5m", now - pd.Timedelta(hours=2), now)
        if len(c1) < 50 or len(c5) == 0: return
        px_now = float(c5.close.iloc[-1])
        sid = self.st["next_id"]; self.st["next_id"] += 1
        sig = {"id": sid, "trader": a, "coin": coin, "dir": d, "t": TS(f["time"]), "px": float(f["px"]), "px_now": px_now, "notional": notional}
        checks, info = check_trade(self.mk, sig, now, fl)
        fails = [n for n, ok, _ in checks if not ok]
        self.st["signals"][str(sid)] = {"trader": a, "coin": coin, "dir": d, "t": str(sig["t"]), "passed": info["passed"],
                                         "fails": fails, "really_good": info["really_good"]}
        shadow = open_position(sig, px_now, c1, now, 1.0, 1.0)
        if shadow: self.st["shadow"].append(shadow)
        is_main = a in self.team["main"]; paused = self.health(a)["paused"]
        b4 = self.mk.candles("BTC", "4h", now - pd.Timedelta(days=160), now)
        reg, side = RG.regime_at(RG.label_series(b4), now) if len(b4) > 400 else (None, 0)
        r_take, r_size, r_exits, r_rev, r_why = RG.decide(reg, side, d)
        is_sub = a in self.st["subs"].values()
        decisions, plan = {}, None
        for v in VERSIONS:
            book = self.st["books"][v]; w = 1.0
            if v.startswith("7"):
                take, why = (is_main and r_take), (r_why if is_main else "bench traders only trade as stand-ins")
            elif v[0] in "156":
                take, why = is_main, "copies every main-team trade" if is_main else "bench traders only trade as stand-ins"
            else:
                if is_main and not paused: take, why = True, "trader is in good form"
                elif is_main and paused:
                    take, why = False, "trader is on watch-only (bad period)"
                    if v.startswith("4") and info["really_good"]: take, why, w = True, "watch-only trader, but this is a really good trade (half size)", 0.5
                elif is_sub: take, why = True, "standing in for a paused trader"
                else: take, why = False, "bench trader, not needed right now"
                if take and not v.startswith("2") and not info["passed"]:
                    take, why = False, "failed the trade check: " + ", ".join(fails)
            if take and len(book["open"]) >= R.MAX_OPEN: take, why = False, f"already {R.MAX_OPEN} trades open"
            if take and any(p["coin"] == coin and p["dir"] == d for p in book["open"]): take, why = False, "already in this trade"
            if take:
                p = open_position(sig, px_now, c1, now, book["cash"], r_size if v.startswith("7") else w)
                if p and (v.startswith("5") or (v.startswith("7") and r_exits == "scale_out")): p["scale"] = True
                if p and v.startswith("7"): p["rev_ok"] = r_rev; p["regime"] = reg
                if p: book["open"].append(p); plan = plan or p
                else: take, why = False, "not enough price data for a stop"
            decisions[v] = (take, why)
        self.card(entry_card(sig, checks, info, decisions, plan, self.team, now), now, "entry")

    # ---------- reports ----------
    def summary(self, since=None):
        rows = []
        for v, b in self.st["books"].items():
            cl = [c for c in b["closed"] if since is None or pd.Timestamp(c["closed"]) >= since]
            w = [c for c in cl if c["pnl"] > 0]; l = [c for c in cl if c["pnl"] <= 0]
            openpnl = 0.0
            rows.append({"version": v, "account": round(b["cash"], 2), "closed trades": len(cl), "wins": len(w), "losses": len(l),
                         "win %": f"{len(w) / len(cl):.0%}" if cl else "-", "avg win": f"{np.mean([c['R'] for c in w]):+.2f}R" if w else "-",
                         "avg loss": f"{np.mean([c['R'] for c in l]):+.2f}R" if l else "-", "open now": len(b["open"])})
        return pd.DataFrame(rows)

    def weekly_lesson(self, now, start_btc=None):
        wk = now - pd.Timedelta(days=7)
        L = [f"# 📒 Weekly lesson — week ending {now:%Y-%m-%d}", "*Practice money only.*", "", "## Scoreboard (this week)",
             md_table(self.summary(wk)), ""]
        allc = [c for c in self.st["books"][VERSIONS[0]]["closed"] if pd.Timestamp(c["closed"]) >= wk]
        if allc:
            best = max(allc, key=lambda c: c["R"]); worst = min(allc, key=lambda c: c["R"])
            L += [f"- **Best trade:** {best['coin']} {best['R']:+.2f}R ({best['why']}).", f"- **Worst trade:** {worst['coin']} {worst['R']:+.2f}R ({worst['why']})."]
        sig = self.st["signals"]; res = {}
        for c in self.st["books"][VERSIONS[0]]["closed"]:
            s = sig.get(str(c["sig_id"]), {})
            for k in (s.get("fails") or ["(passed every check)"]): res.setdefault(k, []).append(c["R"])
        if res:
            L += ["", "## Which warning signs mattered (all trades so far, version 1)"]
            for k, v in sorted(res.items(), key=lambda kv: -len(kv[1])):
                L.append(f"- **{'Passed every check' if k.startswith('(') else 'Failed ' + k}:** {len(v)} trades, won {np.mean([x > 0 for x in v]):.0%}, average {np.mean(v):+.2f}R")
        ev = [e["msg"] for e in self.st["events"] if pd.Timestamp(e["t"]) >= wk]
        L += ["", "## Team changes this week"] + ([f"- {m}" for m in ev] or ["- none"])
        L += ["", "## Watch for next week", "- Do trades that pass every check keep beating the ones that fail? That's what decides if the check is real.",
              "- Remember: 4–8 weeks of results are needed before trusting any version."]
        return "\n".join(L)

def md_table(df):
    cols = list(df.columns)
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] +
                     ["| " + " | ".join(str(v) for v in r) + " |" for r in df.values])

def notify(text, kind):
    """Optional email via Resend (set RESEND_API_KEY and EMAIL_TO). Entry/close cards are batched into a digest by default."""
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("EMAIL_TO")
    if not key or not to: return
    if kind in ("entry", "close") and os.environ.get("EMAIL_EVERY_CARD", "0") != "1":
        with open(DATA / "digest.md", "a") as f: f.write(text + "\n\n---\n\n")
        return
    send_email(f"Kronos practice — {kind}", text)

def send_email(subject, md):
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("EMAIL_TO")
    if not key or not to: return
    try:
        import markdown
        html = markdown.markdown(md, extensions=["tables"])
    except Exception:
        html = "<pre>" + md + "</pre>"
    requests.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {key}"},
                  json={"from": os.environ.get("EMAIL_FROM", "Kronos Practice <onboarding@resend.dev>"), "to": [to],
                        "subject": subject, "html": html}, timeout=30)

def load_team():
    return json.loads((HERE / os.environ.get("TEAM_FILE", "team.json")).read_text())

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    team = load_team()
    if mode == "replay":
        days = float(sys.argv[2]) if len(sys.argv) > 2 else 7
        mk = ReplayMarket(); sf = DATA / "replay_state.json"
        if sf.exists(): sf.unlink()
        for f in CARDS.glob("*.md"): f.unlink()
        end = pd.Timestamp.utcnow().tz_localize(None).floor("5min"); t = end - pd.Timedelta(days=days)
        eng = Engine(mk, team, sf); eng.st["last_ms"] = MS(t)
        while t < end:
            t += pd.Timedelta(minutes=R.CYCLE_MIN)
            eng.cycle(t)
        print(eng.summary().to_string(index=False))
        (DATA / "weekly_lesson.md").write_text(eng.weekly_lesson(end))
        print("REPLAY DONE")
    elif mode == "once":                      # one cycle (used by the GitHub schedule every ~5 min)
        mk = Market(); eng = Engine(mk, team, DATA / "state.json"); now = pd.Timestamp.utcnow().tz_localize(None)
        if not eng.st.get("started"): eng.st["started"] = str(now)
        eng.cycle(now)
        (DATA / "report.md").write_text(f"# Crypto copy-trading — LIVE practice (pretend money)\n*Started {eng.st['started'][:16]} UTC · updated {now:%Y-%m-%d %H:%M} UTC*\n\n"
                                        + md_table(eng.summary()) + "\n\n## Team changes\n" + "\n".join(f"- {e['t'][:16]} {e['msg']}" for e in eng.st["events"][-20:]))
        wk = now.strftime("%G-%V")
        if now.weekday() == 6 and now.hour >= 18 and eng.st.get("lesson_week") != wk:
            (DATA / f"lesson_{wk}.md").write_text(eng.weekly_lesson(now)); eng.st["lesson_week"] = wk; eng.save()
        print(eng.summary().to_string(index=False))
    else:
        mk = Market(); eng = Engine(mk, team, DATA / "state.json")
        last_week = None
        while True:
            now = pd.Timestamp.utcnow().tz_localize(None)
            try:
                eng.cycle(now)
                wk = now.strftime("%G-%V")
                if now.weekday() == 6 and now.hour >= 18 and last_week != wk:
                    txt = eng.weekly_lesson(now); (DATA / f"lesson_{wk}.md").write_text(txt)
                    dg = DATA / "digest.md"
                    send_email("Kronos practice — weekly lesson", txt + ("\n\n# This week's trade cards\n\n" + dg.read_text() if dg.exists() else ""))
                    if dg.exists(): dg.unlink()
                    last_week = wk
            except Exception as e:
                print("cycle error:", repr(e))
            time.sleep(R.CYCLE_MIN * 60)
