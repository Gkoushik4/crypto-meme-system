import sys, os, requests, zipfile, io, pandas as pd
out = sys.argv[1]; S = requests.Session(); frames = {}
for sym in ("BTCUSDT", "ETHUSDT"):
    rows = []
    for y in range(2018, 2027):
        for m in range(1, 13):
            if (y, m) > (2026, 9): break
            u = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/4h/{sym}-4h-{y}-{m:02d}.zip"
            r = S.get(u, timeout=60)
            if r.status_code != 200: print("missing", sym, y, m, r.status_code); continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=[0, 1, 2, 3, 4, 5])
            rows.append(df)
    df = pd.concat(rows); df.columns = ["t", "open", "high", "low", "close", "volume"]
    df = df[pd.to_numeric(df.t, errors="coerce").notna()].astype(float)
    df["t"] = df.t.where(df.t < 1e14, df.t / 1000)          # 2025+ files use microseconds
    df.index = pd.to_datetime(df.t, unit="ms"); df = df.drop(columns="t").sort_index()
    df = df[~df.index.duplicated()]
    df.to_pickle(os.path.join(out, f"{sym}_4h.pkl")); print(sym, len(df), df.index[0], df.index[-1])
