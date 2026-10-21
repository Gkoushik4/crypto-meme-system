"""LOOK-BACK TEST: present-day Solana meme coins (last ~2 days), minute-by-minute prices from GeckoTerminal.
Entry rules = the price/volume parts of our 3 strategies (holder/rug checks can't be replayed -> results are OPTIMISTIC).
Each entry is played out with all 3 exit styles.  Rules are the same numbers as the live tests (fixed 2026-10-19)."""
import json, time, pickle, sys
from collections import deque
from pathlib import Path
import numpy as np, pandas as pd, requests

API = "https://api.geckoterminal.com/api/v2/networks/solana"
OUT = Path(__file__).resolve().parent / "replay"; OUT.mkdir(exist_ok=True)
S = requests.Session(); CALLS = deque(); RATE = 6          # calls/min (the live Early Bird uses the rest of the free limit)
def get(path, params=None):
    for k in range(4):
        while True:
            while CALLS and time.time() - CALLS[0] >= 60: CALLS.popleft()
            if len(CALLS) < RATE: break
            time.sleep(1)
        CALLS.append(time.time())
        try:
            r = S.get(API + path, params=params, timeout=25)
            if r.status_code == 429: time.sleep(15 * (k + 1)); continue
            if r.status_code == 404: return None
            r.raise_for_status(); return r.json()
        except Exception: time.sleep(5)
    return None
f0 = lambda x: float(x or 0)
NOW = time.time(); HOURS = 48

# ---------------- 1) which coins ----------------
def pool_list():
    cache = OUT / "pools.json"
    if cache.exists(): return json.loads(cache.read_text())
    seen, pools = set(), []
    srcs = [("/trending_pools", {"duration": d, "page": pg, "include": "base_token,dex"}) for d in ("24h", "6h", "1h") for pg in (1, 2, 3, 4, 5)]
    srcs += [("/dexes/pumpswap/pools", {"sort": "h24_volume_usd_desc", "page": pg}) for pg in range(1, 11)]
    srcs += [("/dexes/pump-fun/pools", {"sort": "h24_volume_usd_desc", "page": pg}) for pg in range(1, 6)]
    srcs += [("/new_pools", {"page": pg}) for pg in range(1, 6)]
    for path, prm in srcs:
        for p in (get(path, prm) or {}).get("data") or []:
            a = p["attributes"]; base = p["relationships"]["base_token"]["data"]["id"]
            quote = p["relationships"]["quote_token"]["data"]["id"] if "quote_token" in p["relationships"] else ""
            dex = p["relationships"]["dex"]["data"]["id"]
            age_h = (NOW - pd.Timestamp(a["pool_created_at"]).timestamp()) / 3600
            if base in seen or dex not in ("pumpswap", "pump-fun", "raydium", "meteora", "raydium-cpmm", "meteora-damm-v2"): continue
            if age_h > 7 * 24 or f0(a.get("fdv_usd")) <= 0 or f0(a.get("base_token_price_usd")) <= 0: continue
            if not quote.endswith("So11111111111111111111111111111111111111112"): continue      # coin/SOL pools only
            seen.add(base)
            pools.append({"pool": a["address"], "name": a["name"], "dex": dex, "created": pd.Timestamp(a["pool_created_at"]).timestamp(),
                          "supply": f0(a["fdv_usd"]) / f0(a["base_token_price_usd"]), "vol24": f0((a.get("volume_usd") or {}).get("h24"))})
    cache.write_text(json.dumps(pools)); return pools

def clean(df):
    """Remove bad ticks: any price more than 3x away from the 15-minute median is replaced by that median.
    Real pumps survive (the median catches up within minutes); one-minute glitches don't."""
    df = df.copy()
    thin = df.v < 20                                   # under $20 traded that minute: price isn't real/sellable -> keep last real price
    df.loc[thin, ["o", "h", "l", "c"]] = np.nan
    df["c"] = df["c"].ffill().bfill()
    for k in ("o", "h", "l"): df[k] = df[k].fillna(df["c"])
    jump = (df.c / df.c.shift(1)).fillna(1)
    df = df[~((jump > 10) | (jump < 0.1)) | (df.v > 1000)]   # 10x one-minute jumps on thin volume = broken data
    med = df.c.rolling(15, center=True, min_periods=3).median().bfill().ffill()
    for k in ("o", "h", "l", "c"):
        bad = (df[k] > 3 * med) | (df[k] < med / 3)
        df.loc[bad, k] = med[bad]
    df["h"] = df[["o", "h", "l", "c"]].max(axis=1); df["l"] = df[["o", "h", "l", "c"]].min(axis=1)
    return df

def sane(df, p):
    """A brand-new meme coin 'worth' over $500M is broken pool data (drained pool) -> cut the data there."""
    bad = (df.h * p["supply"] > 5e8)
    if bad.any(): df = df.loc[:bad.idxmax()].iloc[:-1]
    return df

def candles(p):
    f = OUT / f"c_{p['pool']}.pkl"
    if f.exists(): return sane(clean(pickle.load(open(f, "rb"))), p)
    rows, before = [], None
    start = max(p["created"], NOW - HOURS * 3600)
    for _ in range(4):
        prm = {"aggregate": 1, "limit": 1000, "currency": "usd"}
        if before: prm["before_timestamp"] = int(before)
        j = get(f"/pools/{p['pool']}/ohlcv/minute", prm)
        l = ((j or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
        if not l: break
        rows += l; before = min(x[0] for x in l)
        if before <= start or len(l) < 1000: break
    if not rows: return None
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"]).drop_duplicates("t").sort_values("t")
    df = df[df.t >= start - 3600].set_index("t")
    idx = np.arange(int(df.index.min()), int(df.index.max()) + 60, 60)
    df = df.reindex(idx); df["c"] = df["c"].ffill()
    for k in ("o", "h", "l"): df[k] = df[k].fillna(df["c"])
    df["v"] = df["v"].fillna(0)
    pickle.dump(df, open(f, "wb")); return sane(clean(df), p)

# ---------------- 2) entry rules (price/volume parts only) ----------------
def signals(p, df):
    c, v = df.c.values, df.v.values; t = df.index.values
    out = {}
    v5 = pd.Series(v).rolling(5).sum().values; v60 = pd.Series(v).rolling(60, min_periods=10).sum().values
    up5 = c / np.roll(c, 5) - 1; up60 = c / np.roll(c, 60) - 1
    mcap = c * p["supply"]
    for i in range(65, len(c) - 2):
        if t[i] < NOW - HOURS * 3600: continue
        age_min = (t[i] - p["created"]) / 60
        crowd = c[i] > c[i - 5]                                  # proxy for "more buyers than sellers"
        main = (p["dex"] != "pump-fun" and age_min <= 7 * 1440 and v60[i] >= 50_000 and 100_000 <= mcap[i] <= 50e6
                and v5[i] * 12 >= v60[i] and up5[i] < 0.15 and up60[i] < 0.50 and crowd)
        early = (p["dex"] in ("pump-fun", "pumpswap") and age_min <= 120 and v5[i] >= 10_000 and v60[i] >= 25_000
                 and 30_000 <= mcap[i] <= 2e6 and up5[i] <= 0.40 and crowd)
        growing = i >= 15 and v5[i] > v5[i - 5] > v5[i - 10] > 0 and up5[i] > 0
        for name, ok in (("Main", main), ("Early Bird", early), ("Promising", (main or early) and growing)):
            if ok and name not in out: out[name] = i + 1             # enter at next minute's open
    return out

# ---------------- 3) exit styles ----------------
def play(df, i0, style, slip, fee):
    o, h, l, c = df.o.values, df.h.values, df.l.values, df.c.values
    e = o[i0] * (1 + slip); left, got = 1.0, 0.0; peak = e; peak_i = i0; flags = set()
    stop = e * (1 - {"Ladder": 0.20, "EarlyBird": 0.25, "Promising": 0.30}[style])
    maxlen = {"Ladder": 24 * 60, "EarlyBird": 6 * 60, "Promising": 24 * 60}[style]
    def sell(share, price):
        nonlocal left, got
        s = min(left, share); left -= s; got += s * price * (1 - slip) * (1 - fee) / e
    steps = 0
    for i in range(i0, min(i0 + maxlen, len(c))):
        if l[i] <= stop:                                           # stop first (worst case inside the minute)
            sell(left, min(stop, o[i])); break
        hi = h[i]
        if hi > peak: peak, peak_i = hi, i
        gp = peak / e - 1
        if style == "Ladder":
            for lvl in (0.25, 0.50, 1.00)[steps:]:
                if hi >= e * (1 + lvl): sell(0.25, e * (1 + lvl)); steps += 1
            if steps == 3: stop = max(stop, peak * 0.80)
            if steps == 0 and i - i0 >= 30 and gp < 0.15: sell(left, c[i]); break
        elif style == "EarlyBird":
            if gp >= 0.5: stop = max(stop, e * 1.03)
            if hi >= e * 2 and "free" not in flags: flags.add("free"); sell(0.5, e * 2)
            if i - i0 >= 2 and hi >= c[i - 2] * 1.5 and "spike" not in flags: flags.add("spike"); sell(0.25, c[i - 2] * 1.5)
            if i - peak_i >= 30 and gp > 0 and "stall" not in flags: flags.add("stall"); sell(0.5, c[i])
            trail = 0.30 if gp < 1 else 0.25 if gp < 3 else 0.20
            if gp > 0.2: stop = max(stop, peak * (1 - trail))
        else:  # Promising: $10 -> $20-30
            if hi >= e * 2 and "half" not in flags: flags.add("half"); sell(0.5, e * 2); stop = max(stop, e * 1.03)
            if hi >= e * 3 and "three" not in flags: flags.add("three"); sell(0.4, e * 3)
            if "three" in flags: stop = max(stop, peak * 0.75)
        if left <= 1e-9: break
    if left > 1e-9: sell(left, c[min(i, len(c) - 1)])
    return got - 1, peak / e - 1

# ---------------- run ----------------
if __name__ == "__main__":
    pools = pool_list(); print(f"coins found: {len(pools)}", flush=True)
    res = []
    for k, p in enumerate(pools):
        df = candles(p)
        if df is None or len(df) < 80: continue
        for strat, i0 in signals(p, df).items():
            slip, fee = (0.01, 0.0025) if strat == "Main" else (0.02, 0.0125)
            for style in ("Ladder", "EarlyBird", "Promising"):
                r, pk = play(df, i0, style, slip, fee)
                res.append({"coin": p["name"].split(" / ")[0], "pool": p["pool"], "entry_rule": strat, "exit": style, "ret": r, "peak": pk,
                            "entry_t": pd.to_datetime(df.index[i0], unit="s")})
        if k % 20 == 0:
            print(f"  {k}/{len(pools)} coins, {len(res)} results", flush=True); pd.DataFrame(res).to_csv(OUT / "results.csv", index=False)
    R = pd.DataFrame(res); R.to_csv(OUT / "results.csv", index=False)
    print("REPLAY DONE", len(R))
