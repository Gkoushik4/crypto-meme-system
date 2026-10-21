"""Part B — last 90 days, copy the skilled veterans' REAL trades.
Variants: base | + trade check | + slow-down | + both. Same exits for all (1% risk, BE at 1R, trail after 2R, TP 3R)."""
import os, sys, time, pickle, requests
import numpy as np, pandas as pd
import level2b as B
import level2 as L

D = "/home/claude/copytest/"
S = requests.Session()
def post(body):
    for k in range(5):
        try:
            r = S.post("https://api.hyperliquid.xyz/info", json=body, timeout=30)
            if r.status_code == 429: time.sleep(5 * (k + 1)); continue
            return r.json()
        except Exception: time.sleep(3)

CUT = B.NOW - pd.Timedelta(days=90); END = B.NOW
picks = B.pick(CUT)
print(f"Skilled veterans picked (history up to {CUT.date()}): {len(picks)}")

# ---------- data: fills for picked traders, 1h + 4h candles for their coins ----------
fills = L.fills
for a in picks.trader:
    if a in fills and len(fills[a]): continue
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
    for iv, back in (("1h", 95), ("4h", 200)):
        if (c, iv) in cpk: continue
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

sig = L.signals(list(picks.trader), CUT, END, coins)
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

def trade_check(s, trader_fills):
    reasons = []
    up_c, up_b = sma_up(C4[s.coin], s.t), sma_up(C4["BTC"], s.t)
    if up_c is not None and up_b is not None:
        if s.dir == 1 and not (up_c or up_b): reasons.append("against the trend")
        if s.dir == -1 and (up_c and up_b): reasons.append("against the trend")
    h = L.candles[s.coin]; bar = h[h.index >= s.t.floor("h")]
    if len(bar) and s.dir * (bar.close.iloc[0] / s.px - 1) > 0.01: reasons.append("late entry (moved 1%+ already)")
    prior = [float(f["sz"]) * float(f["px"]) for f in trader_fills
             if abs(float(f["startPosition"])) < 1e-12 and s.t - pd.Timedelta(days=30) <= pd.to_datetime(f["time"], unit="ms") < s.t]
    this = [float(f["sz"]) * float(f["px"]) for f in trader_fills if pd.to_datetime(f["time"], unit="ms") == s.t and f["coin"] == s.coin]
    if len(prior) >= 5 and this and sum(this) < 0.3 * np.median(prior): reasons.append("small/low-conviction trade")
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
            if (s.dir == 1 and (m < 0 or agree < 0.5)) or (s.dir == -1 and (m > 0 or agree > 0.5)):
                reasons.append("Kronos disagrees")
    return reasons

checks = {}
if len(sig):
    t0 = time.time()
    for i, s in sig.iterrows():
        checks[i] = trade_check(s, fills[s.trader])
    print(f"Trade checks done in {time.time() - t0:.0f}s")

# ---------- copy book with optional check + slow-down ----------
def run(use_check, use_slow):
    cash, open_, log, health = 85.0, [], [], {}
    for i, s in sig.iterrows():
        still = []
        for o in open_:
            if o["exit_t"] <= s.t:
                cash += o["pnl"]; log.append(o)
                h = health.setdefault(o["trader"], {"eq": 1.0, "peak": 1.0, "streak": 0, "w": 1.0})
                h["eq"] *= (1 + o["pnl"] / 85.0); h["peak"] = max(h["peak"], h["eq"])
                h["streak"] = h["streak"] + 1 if o["pnl"] <= 0 else 0
                dd = h["eq"] / h["peak"] - 1
                if use_slow:
                    if dd <= -B.PAUSE_DD: h["w"] = 0.0
                    elif dd <= -B.HALF_DD or h["streak"] >= B.LOSS_STREAK: h["w"] = 0.5
                    elif h["w"] < 1.0 and dd > -0.02 and h["streak"] == 0: h["w"] = 1.0
            else:
                still.append(o)
        open_ = still
        if use_check and checks.get(i): continue
        w = health.get(s.trader, {}).get("w", 1.0)
        if w == 0.0:                         # paused: resume only if their own account makes 2% since pause
            continue
        if len(open_) >= L.MAX_OPEN or any(o["coin"] == s.coin and o["dir"] == s.dir for o in open_): continue
        r = L.simulate_trade(s, "ours")
        if r is None: continue
        notional = min(cash * L.RISK * w / r["stop_dist"], L.MAX_NOTIONAL_X * cash / L.MAX_OPEN)
        r.update(coin=s.coin, dir=s.dir, t=s.t, trader=s.trader, notional=notional, pnl=notional * r["ret"])
        open_.append(r)
    for o in open_: cash += o["pnl"]; log.append(o)
    return cash, pd.DataFrame(log)

if len(sig):
    rows = {}
    for name, uc, us in (("Base (copy every trade)", False, False), ("+ trade check", True, False),
                         ("+ slow-down", False, True), ("+ both", True, True)):
        end, lg = run(uc, us)
        w, l = (lg[lg.pnl > 0], lg[lg.pnl <= 0]) if len(lg) else (lg, lg)
        rows[name] = {"$85 →": f"${end:.2f}", "trades": len(lg), "wins": len(w), "losses": len(l),
                      "win %": f"{len(w)/len(lg):.0%}" if len(lg) else "-",
                      "avg win R": f"{w.R.mean():+.2f}" if len(w) else "-", "avg loss R": f"{l.R.mean():+.2f}" if len(l) else "-"}
    btc = L.candles["BTC"].close; b = btc[(btc.index >= CUT) & (btc.index <= END)]
    rows["Hold BTC"] = {"$85 →": f"${85 * b.iloc[-1] / b.iloc[0]:.2f}"}
    print(pd.DataFrame(rows).T.fillna("").to_string())
    skipped = pd.Series([r for v in checks.values() for r in v]).value_counts()
    print("\nTrades skipped by the check, and why:", ", ".join(f"{k} ({v})" for k, v in skipped.items()) or "none")
    # did the check skip worse trades? (score every signal with our exits, unconstrained)
    sc = []
    for i, s in sig.iterrows():
        r = L.simulate_trade(s, "ours")
        if r: sc.append({"skipped": bool(checks.get(i)), "R": r["R"]})
    sc = pd.DataFrame(sc)
    if len(sc):
        print("Average result of trades the check KEPT vs SKIPPED:",
              sc.groupby("skipped").R.agg(["count", "mean", lambda x: (x > 0).mean()]).set_axis(["trades", "avg R", "win %"], axis=1).round(2).to_dict("index"))
print("PART B DONE")
