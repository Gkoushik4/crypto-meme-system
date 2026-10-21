"""Level 3 rules, trade-by-trade backtest (START_DAYS env = days ago the 90-day period starts), copy the skilled veterans' REAL trades.
Variants: base | + trade check | + slow-down | + both. Same exits for all (1% risk, BE at 1R, trail after 2R, TP 3R)."""
import os, sys, time, pickle, requests
import numpy as np, pandas as pd
import level2b as B
import level2 as L
import level3_rules as R3

D = "/home/claude/copytest/"
S = requests.Session()
def post(body):
    for k in range(5):
        try:
            r = S.post("https://api.hyperliquid.xyz/info", json=body, timeout=30)
            if r.status_code == 429: time.sleep(5 * (k + 1)); continue
            return r.json()
        except Exception: time.sleep(3)

START_DAYS = int(os.environ.get("START_DAYS", "90"))
CUT = B.NOW - pd.Timedelta(days=START_DAYS); END = CUT + pd.Timedelta(days=90)
print(f"=== Copy period {CUT.date()} -> {END.date()} ===")
picks = B.pick(CUT, n=15)
MAIN, BENCH = list(picks.trader[:10]), list(picks.trader[10:])
print(f"Skilled veterans found (history up to {CUT.date()}): {len(picks)}  -> main team {len(MAIN)}, bench {len(BENCH)}")

# ---------- data: fills for picked traders, 1h + 4h candles for their coins ----------
fills = L.fills
for a in picks.trader:
    if a in fills and len(fills[a]) and min(f["time"] for f in fills[a]) <= int((CUT - pd.Timedelta(days=30)).timestamp() * 1000): continue
    out, t0 = [], int(CUT.timestamp() * 1000) - 30 * 86400000
    for _ in range(6):
        page = post({"type": "userFillsByTime", "user": a, "startTime": t0, "endTime": int(END.timestamp() * 1000)}) or []
        time.sleep(1.1); out += page
        if len(page) < 2000: break
        t0 = max(f["time"] for f in page) + 1
    fills[a] = out
cpk = pickle.load(open(D + "candles.pkl", "rb"))
coins = sorted({f["coin"] for a in picks.trader for f in fills[a] if not f["coin"].startswith("@") and ":" not in f["coin"] and "/" not in f["coin"]} | {"BTC"})
for c in coins:
    for iv, back in (("1h", START_DAYS + 5), ("4h", START_DAYS + 70)):
        if (c, iv) in cpk and cpk[(c, iv)].index[0] <= pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=back - 3): continue
        data = post({"type": "candleSnapshot", "req": {"coin": c, "interval": iv, "startTime": int(time.time() * 1000) - back * 86400000,
                                                       "endTime": int(time.time() * 1000)}}); time.sleep(1.1)
        if data:
            df = pd.DataFrame(data)
            cpk[(c, iv)] = pd.DataFrame({"open": df.o.astype(float).values, "high": df.h.astype(float).values, "low": df.l.astype(float).values,
                                         "close": df.c.astype(float).values, "volume": df.v.astype(float).values},
                                        index=pd.to_datetime(df.t, unit="ms"))
pickle.dump(cpk, open(D + "candles.pkl", "wb"))
L.candles = {k[0]: v for k, v in cpk.items() if k[1] == "1h"}
C4 = {k[0]: v for k, v in cpk.items() if k[1] == "4h"}
coins = [c for c in coins if c in L.candles and c in C4]

cov = {a: (pd.to_datetime(min(f["time"] for f in fills[a]), unit="ms") if fills[a] else None) for a in MAIN + BENCH}
gaps = [a[:8] for a, t0 in cov.items() if t0 is not None and t0 > CUT]
print(f"Fill history reaches the start of the period for {len(cov) - len(gaps)}/{len(cov)} traders" + (f" (missing early trades: {', '.join(gaps)})" if gaps else ""))
sig = L.signals(MAIN + BENCH, CUT, END, coins)
print(f"New trades opened by them in the copy period: {len(sig)}  (coins: {', '.join(sorted(sig.coin.unique())) if len(sig) else '-'})")

# ---------- trade check (all thresholds fixed in advance) ----------
def sma_up(df, t, n=300):          # 300 x 4h ≈ 50 days
    x = df.close[df.index <= t]
    return None if len(x) < n else bool(x.iloc[-1] > x.tail(n).mean())

KR = None
def kronos_view(coin, t):
    global KR
    if KR is None:
        os.environ["HF_HUB_DISABLE_XET"] = "1"; sys.path.insert(0, "/root/Kronos")
        import torch; torch.set_num_threads(2); torch.manual_seed(0)
        from model import Kronos, KronosTokenizer, KronosPredictor
        KR = KronosPredictor(Kronos.from_pretrained("NeoQuasar/Kronos-small"),
                             KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base"), device="cpu", max_context=512)
    df = C4[coin][C4[coin].index <= t].tail(400)
    if len(df) < 200: return None
    x = df[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
    xs = pd.Series(df.index); ys = pd.Series(pd.date_range(df.index[-1] + pd.Timedelta(hours=4), periods=6, freq="4h"))
    out = KR.predict_batch([x] * 8, [xs] * 8, [ys] * 8, pred_len=6, T=1.0, top_p=0.9, sample_count=1, verbose=False)
    r = np.array([o.close.iloc[-1] / df.close.iloc[-1] - 1 for o in out])
    return float(r.mean()), float((r > 0).mean())

INFO = {}
def trade_check(s, trader_fills, key=None):
    reasons = []; info = {}
    up_c, up_b = sma_up(C4[s.coin], s.t), sma_up(C4["BTC"], s.t)
    if up_c is not None and up_b is not None:
        if s.dir == 1 and not (up_c or up_b): reasons.append("against the trend")
        if s.dir == -1 and (up_c and up_b): reasons.append("against the trend")
    h = L.candles[s.coin]; bar = h[h.index >= s.t.floor("h")]
    if len(bar) and s.dir * (bar.close.iloc[0] / s.px - 1) > 0.01: reasons.append("late entry (moved 1%+ already)")
    _g = {}
    for f in trader_fills:
        if s.t - pd.Timedelta(days=30) <= pd.to_datetime(f["time"], unit="ms") < s.t and (abs(float(f["startPosition"])) < 1e-12 or (f["coin"], f["time"]) in _g):
            _g[(f["coin"], f["time"])] = _g.get((f["coin"], f["time"]), 0) + float(f["sz"]) * float(f["px"])
    prior = list(_g.values())
    this = [float(f["sz"]) * float(f["px"]) for f in trader_fills if pd.to_datetime(f["time"], unit="ms") == s.t and f["coin"] == s.coin]
    if len(prior) >= 5 and this and sum(this) < 0.3 * np.median(prior): reasons.append("small/low-conviction trade")
    info["bigger_than_usual"] = bool(len(prior) >= 5 and this and sum(this) > np.median(prior))
    info["with_trend"] = bool(up_c is not None and up_b is not None and ((s.dir == 1 and up_c and up_b) or (s.dir == -1 and not up_c and not up_b)))
    a_now = L.atr_pct(s.coin, s.t)
    a_hist = [L.atr_pct(s.coin, s.t - pd.Timedelta(days=d)) for d in (7, 14, 21, 28)]
    a_hist = [x for x in a_hist if not np.isnan(x)]
    if a_hist and a_now > 3 * np.median(a_hist): reasons.append("unusually wild right now")
    vol = (h.close * h.volume)[(h.index < s.t) & (h.index >= s.t - pd.Timedelta(days=1))].sum()
    if vol < 5_000_000: reasons.append("too little trading volume")
    if not reasons:
        kv = kronos_view(s.coin, s.t)
        if kv is not None:
            m, agree = kv
            info["kronos_strong"] = (s.dir == 1 and agree >= 0.75) or (s.dir == -1 and agree <= 0.25)
            if (s.dir == 1 and (m < 0 or agree < 0.5)) or (s.dir == -1 and (m > 0 or agree > 0.5)):
                reasons.append("Kronos disagrees")
    INFO[key] = info
    return reasons

checks = {}
if len(sig):
    t0 = time.time()
    for i, s in sig.iterrows():
        checks[i] = trade_check(s, fills[s.trader], i)
    print(f"Trade checks done in {time.time() - t0:.0f}s")


def really_good(i):
    inf = INFO.get(i, {})
    return (not checks.get(i)) and inf.get("kronos_strong", False) and inf.get("with_trend", False) and inf.get("bigger_than_usual", False)

SHADOW = {i: L.simulate_trade(s, "ours") for i, s in sig.iterrows()}   # what each of their trades would have done (watch-only tracking)

def run(variant, use_check, allow_rg=True):
    """variant: base | old (trade smaller) | new (watch-only + stand-in)."""
    cash, open_, log = 85.0, [], []
    hp = {a: {"eq": 1.0, "peak": 1.0, "streak": 0, "bad": False, "bad_eq": None} for a in MAIN + BENCH}
    pending = []            # shadow results waiting to finish (used for every trader's health)
    sub = {}                # main trader in a bad period -> bench stand-in
    events = []
    def update_health(t):
        nonlocal pending
        done = [p for p in pending if p[0] <= t]; pending = [p for p in pending if p[0] > t]
        for _, a, R in sorted(done, key=lambda x: x[0]):
            h = hp[a]; h["eq"] *= 1 + 0.01 * R; h["peak"] = max(h["peak"], h["eq"])
            h["streak"] = h["streak"] + 1 if R <= 0 else 0
            dd = h["eq"] / h["peak"] - 1
            if not h["bad"] and dd <= -R3.EMERGENCY_PAUSE_DD:   # Level 3: emergency pause only
                h["bad"], h["bad_eq"] = True, h["eq"]; events.append(f"{a[:8]} bad period")
            elif h["bad"] and (h["eq"] >= h["bad_eq"] * 1.02 or h["eq"] >= h["peak"] and h["streak"] == 0 and dd == 0):
                h["bad"] = False; events.append(f"{a[:8]} recovered")
        if variant == "new":
            for a in MAIN:
                if hp[a]["bad"] and (a not in sub or hp[sub[a]]["bad"]):
                    used = set(sub.values())
                    free = [b for b in BENCH if b not in used and not hp[b]["bad"]
                            and ((sig.trader == b) & (sig.t < t) & (sig.t >= t - pd.Timedelta(days=30))).sum() >= R3.STANDIN_MIN_TRADES_30D]
                    if free: sub[a] = free[0]; events.append(f"{free[0][:8]} stands in for {a[:8]}")
                    else: sub.pop(a, None)
                elif not hp[a]["bad"] and a in sub:
                    sub.pop(a)
    for i, s in sig.iterrows():
        update_health(s.t)
        still = []
        for o in open_:
            if o["exit_t"] <= s.t: cash += o["pnl"]; log.append(o)
            else: still.append(o)
        open_ = still
        if SHADOW[i] is not None: pending.append((SHADOW[i]["exit_t"], s.trader, SHADOW[i]["R"]))
        a = s.trader; w = 1.0; kind = "normal"
        if variant in ("base", "old"):
            if a not in MAIN: continue
            if variant == "old" and hp[a]["bad"]: w = 0.5
        else:
            if a in MAIN:
                if hp[a]["bad"]:
                    if not (allow_rg and really_good(i)): continue
                    w, kind = 0.5, "really-good trade from a watched trader"
            elif a in sub.values():
                kind = "stand-in"
            else:
                continue
        if use_check and checks.get(i): continue
        if len(open_) >= L.MAX_OPEN or any(o["coin"] == s.coin and o["dir"] == s.dir for o in open_): continue
        r = SHADOW[i]
        if r is None: continue
        r = dict(r)
        notional = min(cash * L.RISK * w / r["stop_dist"], L.MAX_NOTIONAL_X * cash / L.MAX_OPEN)
        r.update(coin=s.coin, dir=s.dir, t=s.t, trader=a, notional=notional, pnl=notional * r["ret"], kind=kind)
        open_.append(r)
    for o in open_: cash += o["pnl"]; log.append(o)
    return cash, pd.DataFrame(log), events

if len(sig):
    rows, ev_new = {}, []
    for name, v, uc, rg in (("1. Copy every trade", "base", False, False),
                            ("2. + emergency pause & stand-in", "new", False, False),
                            ("3. + trade check", "new", True, False),
                            ("4. + really-good-only while paused", "new", True, True)):
        end, lg, ev = run(v, uc, rg)
        if v == "new" and not uc: ev_new = ev
        w, l = (lg[lg.pnl > 0], lg[lg.pnl <= 0]) if len(lg) else (lg, lg)
        rows[name] = {"$85 ->": f"${end:.2f}", "trades": len(lg), "wins": len(w), "losses": len(l),
                      "win %": f"{len(w)/len(lg):.0%}" if len(lg) else "-",
                      "avg win R": f"{w.R.mean():+.2f}" if len(w) else "-", "avg loss R": f"{l.R.mean():+.2f}" if len(l) else "-",
                      "stand-in trades": int((lg.kind == "stand-in").sum()) if len(lg) else 0,
                      "really-good (watched)": int((lg.kind != "normal").sum() - (lg.kind == "stand-in").sum()) if len(lg) else 0}
    btc = L.candles["BTC"].close; b = btc[(btc.index >= CUT) & (btc.index <= END)]
    rows["Hold BTC"] = {"$85 ->": f"${85 * b.iloc[-1] / b.iloc[0]:.2f}"}
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).T.fillna("").to_string())
    print("\nBad periods / stand-ins during the test:", "; ".join(ev_new) or "none")
    mains = sig[sig.trader.isin(MAIN)].index
    skipped = pd.Series([r for i in mains for r in checks.get(i, [])]).value_counts()
    print("Trades skipped by the check, and why:", ", ".join(f"{k} ({v})" for k, v in skipped.items()) or "none")
    sc = pd.DataFrame([{"skipped": bool(checks.get(i)), "R": SHADOW[i]["R"]} for i in mains if SHADOW[i]])
    if len(sc):
        print("Trades the check KEPT vs SKIPPED:",
              sc.groupby("skipped").R.agg(["count", "mean", lambda x: (x > 0).mean()]).set_axis(["trades", "avg R", "win %"], axis=1).round(2).to_dict("index"))
    rg = [SHADOW[i]["R"] for i in sig.index if really_good(i) and SHADOW[i]]
    print(f"'Really good' trades found: {len(rg)}, avg R {np.mean(rg):+.2f}, win {np.mean([x > 0 for x in rg]):.0%}" if rg else "'Really good' trades found: 0")
print("PART B DONE")
