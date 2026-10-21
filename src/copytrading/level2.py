"""LEVEL 2 — trade-by-trade copy test with OUR exits, 3 time windows.
Safe Engine ($85): copy BTC/ETH/SOL trades opened AFTER copying starts, from traders that pass every rule.
Each trade risks 1% of the Safe Engine; take-profit 3R; stop to break-even at +1R; trailing stop after +2R.
Also: the Moonshot proxy ($15) on Hyperliquid meme coins with the moonshot rules."""
import pickle, json, sys
from collections import defaultdict
import numpy as np, pandas as pd
from filters import score_trader, RULES
from metrics import perp_fills, value_at

D = "/home/claude/copytest/"
fills = pickle.load(open(D + "fills.pkl", "rb"))
port = pickle.load(open(D + "portfolio.pkl", "rb"))
candles = {k[0]: v for k, v in pickle.load(open(D + "candles.pkl", "rb")).items() if k[1] == "1h"}
MAJORS = ["BTC", "ETH", "SOL"]
MEMES = [c for c in ["FARTCOIN", "kPEPE", "kBONK", "WIF", "POPCAT", "PNUT", "GOAT", "MOODENG", "PUMP", "kSHIB", "MEW",
                     "BRETT", "TRUMP", "SPX", "CHILLGUY", "TURBO", "MELANIA", "kFLOKI", "DOGE", "PENGU", "MOG", "kNEIRO",
                     "NEIRO", "BOME", "GIGA", "VINE", "USELESS", "TST"] if c in candles]
SLIP, FEE = 0.001, 0.00045
RISK, TP_R, BE_R, TRAIL_START_R, TRAIL_R = 0.01, 3.0, 1.0, 2.0, 1.0
MAX_OPEN, MAX_NOTIONAL_X, MAX_HOLD_H = 5, 3.0, 24 * 7
L2_RULES = dict(RULES, min_payoff=2.5, max_open_loss=0.15)
ms = lambda t: int(t.timestamp() * 1000)

# ---------------- extra report-card items for Level 2 ----------------
def payoff_ratio(fl):
    by = defaultdict(float)
    for f in fl:
        if float(f.get("closedPnl", 0)) != 0:
            by[f["oid"]] += float(f["closedPnl"]) - float(f["fee"])
    v = np.array(list(by.values()))
    w, l = v[v > 0], v[v < 0]
    if len(w) == 0 or len(l) == 0:
        return np.inf if len(w) else np.nan
    return w.mean() / -l.mean()

def open_loss_at(fl, end, av):
    """Unrealized loss on positions opened inside the window and still open at its end, vs account value."""
    lots = defaultdict(list)
    for f in sorted(fl, key=lambda x: x["time"]):
        c, sz, px = f["coin"], float(f["sz"]), float(f["px"])
        start = float(f["startPosition"]); delta = sz if f["side"] == "B" else -sz; new = start + delta
        if abs(new) < 1e-12 or (start != 0 and np.sign(new) != np.sign(start)):
            lots[c] = [] if abs(new) < 1e-12 else [(new, px)]
        elif np.sign(delta) == np.sign(new):
            lots[c].append((delta, px))
        else:  # partial reduce: shrink proportionally
            tot = sum(q for q, _ in lots[c]) or new
            lots[c] = [(q * new / tot, p) for q, p in lots[c]]
    upnl = 0.0
    for c, ls in lots.items():
        if not ls or c not in candles:
            continue
        mark = candles[c].close[candles[c].index <= end]
        if len(mark) == 0:
            continue
        upnl += sum(q * (mark.iloc[-1] - p) for q, p in ls)
    return (-upnl / av) if av and av > 0 and upnl < 0 else 0.0

def select(start, end, hot=False):
    rows = []
    for a, fl in fills.items():
        if a not in port:
            continue
        card = score_trader(fl, port[a], start, end)
        if "enough data" in card["failed"]:
            continue
        pf_ = perp_fills(fl, start, end)
        card["payoff"] = payoff_ratio(pf_)
        card["open_loss"] = open_loss_at(pf_, end, card["account_value"])
        if not (card["payoff"] >= L2_RULES["min_payoff"]):
            card["failed"] = card["failed"] + ["payoff ≥ 2.5"]
        if card["open_loss"] > L2_RULES["max_open_loss"]:
            card["failed"] = card["failed"] + ["open losses ≤ 15%"]
        card["passed"] = not card["failed"]
        card["trader"] = a
        rows.append(card)
    d = pd.DataFrame(rows)
    return d

# ---------------- signals: NEW positions opened during the copy window ----------------
def signals(traders, start, end, coins, longs_only=False):
    out = []
    s, e = ms(start), ms(end)
    for a in traders:
        fl = sorted([f for f in fills[a] if f["coin"] in coins], key=lambda x: x["time"])
        for k, f in enumerate(fl):
            if not (s <= f["time"] < e) or abs(float(f["startPosition"])) > 1e-12:
                continue
            d = 1 if f["side"] == "B" else -1
            if longs_only and d < 0:
                continue
            close_t = None
            for g in fl[k + 1:]:
                st = float(g["startPosition"]); dl = float(g["sz"]) * (1 if g["side"] == "B" else -1)
                if abs(st + dl) < 1e-12 or np.sign(st + dl) != np.sign(st):
                    close_t = g["time"]; break
            out.append({"trader": a, "coin": f["coin"], "dir": d, "t": pd.to_datetime(f["time"], unit="ms"),
                        "px": float(f["px"]), "trader_close": pd.to_datetime(close_t, unit="ms") if close_t else None})
    return pd.DataFrame(out).sort_values("t").reset_index(drop=True) if out else pd.DataFrame()

def atr_pct(coin, t):
    c = candles[coin]; c = c[c.index < t].tail(15)
    if len(c) < 5:
        return np.nan
    tr = np.maximum(c.high - c.low, np.maximum((c.high - c.close.shift()).abs(), (c.low - c.close.shift()).abs()))
    return float(tr.iloc[1:].mean() / c.close.iloc[-1])

# ---------------- one copied trade, OUR exits ----------------
def simulate_trade(sig, mode="ours"):
    c = candles[sig.coin]; d = sig.dir
    entry = sig.px * (1 + d * SLIP)
    stop_dist = max(1.5 * atr_pct(sig.coin, sig.t), 0.004)
    if np.isnan(stop_dist):
        return None
    stop = entry * (1 - d * stop_dist); target = entry * (1 + d * TP_R * stop_dist)
    best = entry
    path = c[(c.index > sig.t.floor("h")) & (c.index <= sig.t + pd.Timedelta(hours=MAX_HOLD_H))]
    last_t, exit_px, why = sig.t, None, None
    for t, bar in path.iterrows():
        if mode == "trader" and sig.trader_close is not None and t >= sig.trader_close:
            exit_px, why, last_t = bar.open, "trader closed", t; break
        lo, hi = (bar.low, bar.high) if d == 1 else (bar.high, bar.low)
        if (d == 1 and bar.low <= stop) or (d == -1 and bar.high >= stop):
            exit_px = min(stop, bar.open) if d == 1 else max(stop, bar.open)
            why = "break-even/trailing stop" if (stop - entry) * d >= 0 else "stop-loss"; last_t = t; break
        if mode == "ours" and ((d == 1 and bar.high >= target) or (d == -1 and bar.low <= target)):
            exit_px, why, last_t = target, "take-profit 3R", t; break
        best = max(best, bar.high) if d == 1 else min(best, bar.low)
        gain_r = d * (best / entry - 1) / stop_dist
        if mode == "ours":
            if gain_r >= BE_R:
                stop = entry * (1 + d * 2 * FEE) if d == 1 else entry * (1 - 2 * FEE)
                stop = max(stop, entry * (1 + 2 * FEE)) if d == 1 else min(stop, entry * (1 - 2 * FEE))
            if gain_r >= TRAIL_START_R:
                trail = best * (1 - d * TRAIL_R * stop_dist)
                stop = max(stop, trail) if d == 1 else min(stop, trail)
        last_t = t
    if exit_px is None:
        if len(path) == 0:
            return None
        exit_px, why = path.close.iloc[-1], "time limit (7 days)"
    exit_px *= (1 - d * SLIP)
    ret = d * (exit_px / entry - 1) - 2 * FEE
    return {"exit_t": last_t, "ret": ret, "R": ret / stop_dist, "stop_dist": stop_dist, "why": why}

def run_book(sigs, start_cash, mode="ours", rng=None):
    """Shared Safe-Engine book: 1% risk per trade, max 5 open, no duplicate coin+direction."""
    cash, open_, log = start_cash, [], []
    for _, s in sigs.iterrows():
        if rng is not None:                         # random control: same time, random coin & direction
            s = s.copy(); s["coin"] = rng.choice(MAJORS); s["dir"] = rng.choice([1, -1])
            px = candles[s.coin].close[candles[s.coin].index <= s.t]
            if len(px) == 0: continue
            s["px"] = px.iloc[-1]
        still = []
        for o in open_:
            if o["exit_t"] <= s.t:
                cash += o["pnl"]; log.append(o)
            else:
                still.append(o)
        open_ = still
        if len(open_) >= MAX_OPEN or any(o["coin"] == s.coin and o["dir"] == s.dir for o in open_):
            continue
        r = simulate_trade(s, mode)
        if r is None:
            continue
        equity = cash
        notional = min(equity * RISK / r["stop_dist"], MAX_NOTIONAL_X * equity / MAX_OPEN)
        r.update(coin=s.coin, dir=s.dir, t=s.t, trader=s.trader, notional=notional, pnl=notional * r["ret"])
        open_.append(r)
    for o in open_:
        cash += o["pnl"]; log.append(o)
    return cash, pd.DataFrame(log)

def stats(log, start_cash, end_cash):
    if len(log) == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "win %": "-", "avg win (R)": "-", "avg loss (R)": "-", "$ end": f"${end_cash:.2f}"}
    w, l = log[log.pnl > 0], log[log.pnl <= 0]
    return {"trades": len(log), "wins": len(w), "losses": len(l), "win %": f"{len(w) / len(log):.0%}",
            "avg win (R)": f"{w.R.mean():+.2f}" if len(w) else "-", "avg loss (R)": f"{l.R.mean():+.2f}" if len(l) else "-",
            "$ end": f"${end_cash:.2f}"}

if __name__ == '__main__':
    # ---------------- run the 3 windows ----------------
    all_t = [f["time"] for fl in fills.values() for f in fl]
    END = pd.to_datetime(max(all_t), unit="ms"); T0 = END - pd.Timedelta(days=90)
    summary, all_logs = [], []
    for w in (0, 15, 30):
        s0, s1 = T0 + pd.Timedelta(days=w), T0 + pd.Timedelta(days=w + 30)
        t1 = min(s1 + pd.Timedelta(days=30), END)
        d = select(s0, s1)
        passed = d[d.passed].nlargest(10, "profit_factor")
        hot = d.nlargest(10, "month_return")
        sig = signals(list(passed.trader), s1, t1, MAJORS)
        sig_hot = signals(list(hot.trader), s1, t1, MAJORS)
        print(f"\n===== WINDOW {w // 15 + 1}: pick traders {s0.date()}→{s1.date()}, copy {s1.date()}→{t1.date()} =====")
        print(f"Scored {len(d)} traders; passed every rule: {(d.passed).sum()}; copying top {len(passed)}")
        fails = pd.Series([f for fl in d.failed for f in fl]).value_counts()
        print("Rejections:", ", ".join(f"{k} ({v})" for k, v in fails.items()))
        rows = {}
        end_cash, log = run_book(sig, 85.0, "ours") if len(sig) else (85.0, pd.DataFrame())
        rows["SAFE ENGINE (our exits)"] = stats(log, 85, end_cash)
        if len(log): all_logs.append(log.assign(window=w // 15 + 1))
        end2, log2 = run_book(sig, 85.0, "trader") if len(sig) else (85.0, pd.DataFrame())
        rows["Same traders, THEIR exits"] = stats(log2, 85, end2)
        end3, log3 = run_book(sig_hot, 85.0, "ours") if len(sig_hot) else (85.0, pd.DataFrame())
        rows["Hottest 10 (no rules), our exits"] = stats(log3, 85, end3)
        rnd = [run_book(sig, 85.0, "ours", rng=np.random.default_rng(k))[0] for k in range(30)] if len(sig) else [85.0]
        rows["Random coin+direction, same times (median of 30)"] = {"$ end": f"${np.median(rnd):.2f}"}
        b = candles["BTC"].close; b = b[(b.index >= s1) & (b.index <= t1)]
        rows["Hold BTC"] = {"$ end": f"${85 * b.iloc[-1] / b.iloc[0]:.2f}"}
        tab = pd.DataFrame(rows).T.fillna("")
        print(tab.to_string())
        summary.append({"window": w // 15 + 1, "safe_end": end_cash, "their_exits": end2, "hot_end": end3,
                        "random_median": np.median(rnd), "btc_end": 85 * b.iloc[-1] / b.iloc[0], "trades": len(log),
                        "beat_random": float(np.mean(np.array(rnd) < end_cash)) if len(sig) else np.nan})

    S = pd.DataFrame(summary)
    print("\n===== SAFE ENGINE ACROSS ALL 3 WINDOWS =====")
    print(S.round(2).to_string(index=False))
    if all_logs:
        L = pd.concat(all_logs)
        w, l = L[L.pnl > 0], L[L.pnl <= 0]
        print(f"\nAll copied trades: {len(L)}   wins {len(w)}   losses {len(l)}   win rate {len(w)/len(L):.0%}")
        print(f"Average win {w.R.mean():+.2f}R   average loss {l.R.mean():+.2f}R   → 1 average win pays for {w.R.mean() / -l.R.mean():.1f} average losses")
        print("How trades ended:"); print(L.groupby("why").agg(trades=("R", "size"), avg_R=("R", "mean")).round(2).to_string())
        L.to_csv("level2_safe_trades.csv", index=False)

    # ---------------- MOONSHOT PROXY: Hyperliquid meme coins ----------------
    print("\n\n===== MOONSHOT PROXY — meme coins on Hyperliquid:", ", ".join(MEMES), "=====")
    def moonshot_trade(s):
        c = candles[s.coin]
        prior = c[(c.index <= s.t) & (c.index > s.t - pd.Timedelta(hours=24))]
        if len(prior) and s.px / prior.open.iloc[0] - 1 > 0.30:
            return {"why": "SKIPPED: already up 30%+ in 24h (late entry)", "ret": None}
        entry = s.px * (1 + 0.003)                           # meme slippage 0.3%
        path = c[(c.index > s.t.floor("h")) & (c.index <= s.t + pd.Timedelta(days=14))]
        half_sold, realized, why = False, 0.0, None
        for t, bar in path.iterrows():
            if not half_sold and bar.high >= entry * 2:
                realized += 0.5 * 1.0; half_sold = True          # sold half at +100%
            age = (t - s.t).total_seconds() / 3600
            if age >= 24:
                rng_ = path[path.index <= t]
                if not half_sold and rng_.high.max() / entry - 1 <= 0.05 and rng_.low.min() / entry - 1 >= -0.05:
                    ret = bar.close / entry - 1; return {"why": "dead after 24h → closed", "ret": ret - 0.006}
            if s.trader_close is not None and t >= s.trader_close:
                rest = (bar.open / entry - 1)
                ret = (realized + 0.5 * rest) if half_sold else rest
                return {"why": "smart trader exited → we exit", "ret": ret - 0.006}
        if len(path) == 0:
            return {"why": "no data", "ret": None}
        rest = path.close.iloc[-1] / entry - 1
        return {"why": "14-day limit", "ret": ((realized + 0.5 * rest) if half_sold else rest) - 0.006}

    meme_rows = []
    for w in (0, 15, 30):
        s0, s1 = T0 + pd.Timedelta(days=w), T0 + pd.Timedelta(days=w + 30)
        t1 = min(s1 + pd.Timedelta(days=30), END)
        smart = []
        for a, fl in fills.items():                     # "smart wallets": profitable across 3+ coins, PF ≥ 1.5, risk ≤ 2%
            pf_ = perp_fills(fl, s0, s1)
            if len(pf_) < 10: continue
            by_coin = defaultdict(float)
            for f in pf_: by_coin[f["coin"]] += float(f["closedPnl"]) - float(f["fee"])
            gp = sum(v for v in by_coin.values() if v > 0); gl = -sum(v for v in by_coin.values() if v < 0)
            if sum(v > 0 for v in by_coin.values()) >= 3 and (gl == 0 or gp / gl >= 1.5):
                smart.append(a)
        sig = signals(smart, s1, t1, MEMES, longs_only=True)
        for _, s in sig.iterrows():
            r = moonshot_trade(s); r.update(window=w // 15 + 1, coin=s.coin, t=s.t); meme_rows.append(r)
    M = pd.DataFrame(meme_rows)
    if len(M):
        took = M[M.ret.notna()]
        print(f"Smart-wallet meme buy signals: {len(M)}   skipped as late entries: {(M.why.str.startswith('SKIPPED')).sum()}   taken: {len(took)}")
        print(f"ALL taken signals: wins {(took.ret > 0).sum()}  losses {(took.ret <= 0).sum()}  win rate {(took.ret > 0).mean():.0%}  "
              f"avg {took.ret.mean():+.1%}  best {took.ret.max():+.0%}  worst {took.ret.min():+.0%}  doubled+: {(took.ret >= 0.5).sum()}")
        print(took.groupby("why").ret.agg(["count", "mean"]).round(3).to_string())
        # the actual moonshot budget: $15, max 2 bets per 30 days, $7.50 each
        cash, n_bets, bets = 15.0, 0, []
        for w_ in (1, 2, 3):
            month = took[took.window == w_].sort_values("t").head(2)
            for _, r in month.iterrows():
                stake = min(7.5, cash)
                if stake <= 0: break
                cash += stake * r.ret; bets.append(f"{r.coin} {r.ret:+.0%}")
        print(f"\nMoonshot budget ($15, max 2 bets/month, $7.50 each) → ${cash:.2f}   bets: {', '.join(bets) if bets else 'none'}")
    else:
        print("No smart-wallet meme coin buys found in the windows.")
    print("\nLEVEL 2 DONE")
