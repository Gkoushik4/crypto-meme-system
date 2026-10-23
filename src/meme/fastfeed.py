"""FAST FEED — sees pump.fun + PumpSwap trades about 1 second after they happen, using Solana's free public live feed.
Part of the INSIDER feature: watches trusted pro wallets, known dumpers and the coins we hold in real time.
- decode(logs): turns a transaction's logs into trades / launches (wallet, coin, buy/sell, amounts, price, pool money).
- Feed: a background thread with one live connection; subscriptions change as the watch list changes; auto-reconnects.
Practice only — this module never trades."""
import asyncio, base64, json, struct, threading, time, queue
import base58, websockets

WS = "wss://api.mainnet-beta.solana.com"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"           # pump.fun (launch curve)
PSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"          # PumpSwap (after graduation)
D_TRADE, D_CREATE = bytes.fromhex("bddb7fd34ee661ee"), bytes.fromhex("1b72a94ddeeb6376")
D_BUY, D_SELL = bytes.fromhex("67f4521f2cf57777"), bytes.fromhex("3e2f370aa503dc2a")
D_COMPLETE = bytes.fromhex("5f72619cd42e9808")
PUMP_SUPPLY = 1_000_000_000          # pump.fun coins: 1B tokens, 6 decimals

def _pk(b, o): return base58.b58encode(b[o:o + 32]).decode(), o + 32
def _u64(b, o): return struct.unpack_from("<Q", b, o)[0], o + 8
def _i64(b, o): return struct.unpack_from("<q", b, o)[0], o + 8
def _str(b, o):
    n = struct.unpack_from("<I", b, o)[0]; return b[o + 4:o + 4 + n].decode("utf-8", "replace"), o + 4 + n

def decode(logs, sig=None, slot=None):
    """Return a list of events from one transaction's logs."""
    out = []
    for line in logs:
        if not line.startswith("Program data: "): continue
        try: b = base64.b64decode(line[14:])
        except Exception: continue
        d, o = b[:8], 8
        try:
            if d == D_TRADE:                                   # pump.fun buy/sell on the launch curve
                mint, o = _pk(b, o); sol, o = _u64(b, o); tok, o = _u64(b, o); buy = b[o] == 1; o += 1
                user, o = _pk(b, o); ts, o = _i64(b, o); vsol, o = _u64(b, o); vtok, o = _u64(b, o); rsol, o = _u64(b, o)
                if not tok: continue
                out.append({"k": "trade", "venue": "pump.fun", "mint": mint, "pool": None, "w": user, "buy": buy,
                            "sol": sol / 1e9, "tok": tok / 1e6, "px_sol": (vsol / 1e9) / (vtok / 1e6) if vtok else 0,
                            "pool_sol": rsol / 1e9, "ts": ts, "sig": sig, "slot": slot})
            elif d == D_CREATE:                                # a brand-new coin launched
                name, o = _str(b, o); sym, o = _str(b, o); uri, o = _str(b, o)
                mint, o = _pk(b, o); curve, o = _pk(b, o); user, o = _pk(b, o)
                out.append({"k": "create", "mint": mint, "name": name, "sym": sym, "uri": uri, "w": user, "sig": sig, "slot": slot, "ts": time.time()})
            elif d in (D_BUY, D_SELL):                         # PumpSwap buy/sell (graduated coins)
                ts, o = _i64(b, o); amt, o = _u64(b, o); _, o = _u64(b, o)           # base amount, limit
                _, o = _u64(b, o); _, o = _u64(b, o)                                   # user reserves
                pbase, o = _u64(b, o); pquote, o = _u64(b, o); q, o = _u64(b, o)       # pool reserves, quote amount
                o += 8 * 6                                                            # fee fields + 2 quote totals
                pool, o = _pk(b, o); user, o = _pk(b, o)
                if not pbase or not amt: continue
                out.append({"k": "trade", "venue": "PumpSwap", "mint": None, "pool": pool, "w": user, "buy": d == D_BUY,
                            "sol": q / 1e9, "tok": amt / 1e6, "px_sol": (pquote / 1e9) / (pbase / 1e6), "pool_sol": pquote / 1e9,
                            "ts": ts, "sig": sig, "slot": slot})
            elif d == D_COMPLETE:                              # finished the launch curve (graduating)
                user, o = _pk(b, o); mint, o = _pk(b, o)
                out.append({"k": "complete", "mint": mint, "w": user, "sig": sig, "slot": slot, "ts": time.time()})
        except Exception:
            continue
    return out

class Feed:
    """Background live connection. Call want(set_of_addresses) any time; read events with drain()."""
    def __init__(self, programs=(), maxq=200_000):
        self.q = queue.Queue(maxq); self.programs = list(programs); self._want = set(); self._lock = threading.Lock()
        self.stats = {"events": 0, "reconnects": 0, "subs": 0, "lag": [], "connected": False, "err": ""}
        threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True).start()
    def want(self, addrs):
        with self._lock: self._want = set(a for a in addrs if a)
    def drain(self, n=100_000):
        out = []
        try:
            while len(out) < n: out.append(self.q.get_nowait())
        except queue.Empty: pass
        return out
    def lag(self):
        l = self.stats["lag"][-500:]; return sorted(l)[len(l) // 2] if l else None
    async def _run(self):
        while True:
            try:
                async with websockets.connect(WS, proxy=True, max_size=2 ** 25, ping_interval=20, ping_timeout=30) as ws:
                    self.stats["connected"] = True; subs, pending, rid = {}, {}, 100
                    for p in self.programs:
                        rid += 1; pending[rid] = p
                        await ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": "logsSubscribe", "params": [{"mentions": [p]}, {"commitment": "processed"}]}))
                    last_sync = 0
                    while True:
                        if time.time() - last_sync > 2:                       # keep subscriptions = watch list
                            with self._lock: want = set(self._want)
                            have = set(subs.values()) | set(pending.values())
                            for a in list(want - have)[:50]:
                                rid += 1; pending[rid] = a
                                await ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": "logsSubscribe", "params": [{"mentions": [a]}, {"commitment": "processed"}]}))
                            for sid, a in list(subs.items()):
                                if a not in want and a not in self.programs:
                                    rid += 1; subs.pop(sid)
                                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": "logsUnsubscribe", "params": [sid]}))
                            self.stats["subs"] = len(subs); last_sync = time.time()
                        try: m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                        except asyncio.TimeoutError: continue
                        if "id" in m and m.get("id") in pending:
                            a = pending.pop(m["id"])
                            if "result" in m: subs[m["result"]] = a
                            else: self.stats["err"] = str(m.get("error"))[:200]
                            continue
                        prm = m.get("params") or {}
                        v = (prm.get("result") or {}).get("value")
                        if not v or v.get("err"): continue
                        got = time.time(); src = subs.get(prm.get("subscription"))
                        for e in decode(v["logs"], v.get("signature"), (prm.get("result") or {}).get("context", {}).get("slot")):
                            e["got"], e["src"] = got, src
                            if e["k"] == "trade" and e.get("ts"): self.stats["lag"].append(got - e["ts"]); self.stats["lag"] = self.stats["lag"][-2000:]
                            self.stats["events"] += 1
                            try: self.q.put_nowait(e)
                            except queue.Full: pass
            except Exception as ex:
                self.stats["err"] = repr(ex)[:200]
            self.stats["connected"] = False; self.stats["reconnects"] += 1
            await asyncio.sleep(3)

if __name__ == "__main__":       # quick self-test: 15 seconds of live launches/trades
    f = Feed(programs=[PUMP, PSWAP]); time.sleep(15); ev = f.drain()
    from collections import Counter
    print(Counter((e["k"], e.get("venue")) for e in ev), "median delay (s):", f.lag(), f.stats["err"])
    for k in ("create",):
        x = next((e for e in ev if e["k"] == k), None); print(k, x)
    for v in ("pump.fun", "PumpSwap"):
        x = next((e for e in ev if e.get("venue") == v), None); print(v, x)
