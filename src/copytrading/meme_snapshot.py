"""Live Meme Radar snapshot (paper only): today's trending Solana meme coins through the safety checks.
Saves the list so we can check prices again later (forward test)."""
import json, time, requests, sys, os
import pandas as pd

S = requests.Session()
RPC = "https://api.mainnet-beta.solana.com"
def rpc(method, params):
    for k in range(4):
        try:
            r = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
            if r.status_code == 429: time.sleep(3 * (k + 1)); continue
            return r.json().get("result")
        except Exception: time.sleep(2)
    return None

boosts = S.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=20).json()
latest = S.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=20).json()
mints = []
for b in boosts + latest:
    if b.get("chainId") == "solana" and b["tokenAddress"] not in mints:
        mints.append(b["tokenAddress"])
mints = mints[:30]
rows = []
for m in mints:
    pairs = S.get(f"https://api.dexscreener.com/latest/dex/tokens/{m}", timeout=20).json().get("pairs") or []
    pairs = [p for p in pairs if p.get("chainId") == "solana"]
    if not pairs:
        continue
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0))
    liq = (p.get("liquidity") or {}).get("usd", 0) or 0
    tx = p.get("txns", {}).get("h1", {})
    g = (S.get(f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={m}", timeout=30).json().get("result") or {})
    g = list(g.values())[0] if g else {}
    st = lambda k: str((g.get(k) or {}).get("status", "1")) if isinstance(g.get(k), dict) else str(g.get(k, "1"))
    holders = [h for h in (g.get("holders") or []) if not h.get("tag") and not h.get("is_locked")]
    pcts = sorted([float(h.get("percent", 0)) for h in holders], reverse=True)
    creators = {c.get("address") for c in (g.get("creators") or [])}
    creator_pct = sum(float(h.get("percent", 0)) for h in (g.get("holders") or []) if h.get("account") in creators)
    top10 = sum(pcts[:10]) if g else None
    biggest_wallet = pcts[0] if pcts else None
    age_h = (time.time() * 1000 - (p.get("pairCreatedAt") or time.time() * 1000)) / 3.6e6
    checks = {
        "safety data found": bool(g),
        "creator holds ≤ 5%": bool(g) and creator_pct <= 0.05,
        "can't print more coins": bool(g) and st("mintable") == "0",
        "can't freeze wallets": bool(g) and st("freezable") == "0",
        "can't change balances / block selling": bool(g) and st("balance_mutable_authority") == "0" and str(g.get("non_transferable", "1")) == "0" and not g.get("transfer_hook"),
        "biggest other wallet ≤ 10%": biggest_wallet is not None and biggest_wallet <= 0.10,
        "top 10 wallets ≤ 30%": top10 is not None and top10 <= 0.30,
        "liquidity ≥ $50k (can sell $7)": liq >= 50_000,
        "not up 30%+ in last hour (late)": (p.get("priceChange", {}).get("h1") or 0) < 30,
        "more buyers than sellers (1h)": tx.get("buys", 0) > tx.get("sells", 0),
    }
    rows.append({"coin": p["baseToken"]["symbol"], "mint": m, "price": float(p.get("priceUsd") or 0),
                 "liquidity_$": round(liq), "age_h": round(age_h, 1), "chg_1h_%": p.get("priceChange", {}).get("h1"),
                 "chg_24h_%": p.get("priceChange", {}).get("h24"), "top10_%": round(100 * top10, 1) if top10 is not None else None,
                 "passed": all(checks.values()), "failed": [k for k, v in checks.items() if not v],
                 "time": pd.Timestamp.utcnow().isoformat()})
    time.sleep(1.0)
df = pd.DataFrame(rows)
df.to_csv("meme_snapshot.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
print(f"Trending Solana coins checked: {len(df)}   passed every safety check: {df.passed.sum()}")
print(df[["coin", "liquidity_$", "age_h", "chg_1h_%", "chg_24h_%", "top10_%", "passed"]].to_string(index=False))
fails = pd.Series([f for fl in df.failed for f in fl]).value_counts()
print("\nWhy coins failed:", ", ".join(f"{k} ({v})" for k, v in fails.items()))
