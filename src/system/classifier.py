"""COIN / MARKET TYPE DETECTOR — tells major crypto, altcoins, memes, commodities, stocks, forex apart.
Uses several clues together and always says WHY. Anything it can't identify confidently is UNKNOWN (never traded)."""
import time, json
import numpy as np, requests

MAJOR, ALT, MEME, NEW_MEME, COMMODITY, STOCK, FOREX, PREIPO, UNKNOWN = (
    "major", "altcoin", "established meme", "new meme", "commodity", "stock/index", "forex/bonds", "pre-IPO", "unknown")
ICON = {MAJOR: "🟦", ALT: "🟩", MEME: "🟨", NEW_MEME: "🟥", COMMODITY: "🛢️", STOCK: "📈", FOREX: "💱", PREIPO: "🚀", UNKNOWN: "❔"}

MAJORS = {"BTC", "ETH", "SOL"}
COMMODITIES = {"OIL", "USOIL", "WTI", "BRENT", "UKOIL", "GAS", "NATGAS", "GOLD", "XAU", "SILVER", "XAG", "COPPER", "PLATINUM",
               "PALLADIUM", "WHEAT", "SOY", "SOYBEAN", "CORN", "COFFEE", "SUGAR", "COCOA", "GOLDJM", "SILVERJM", "URANIUM", "PAXG", "XAUT"}
FX_BONDS = {"EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "CNY", "CNH", "MXN", "DXY", "USBOND", "BOND", "US10Y", "US30Y", "TLT"}
INDEXES = {"JPN225", "JP225", "USA100", "NAS100", "UK100", "GER40", "US500", "USA500", "SPX500", "USTECH", "NAS100", "XYZ100", "US30", "SMALL2000", "RUSSELL", "MAG7", "SEMIS", "SEMI", "ROBOT",
           "INFOTECH", "NUCLEAR", "DEFENSE", "ENERGY", "BIOTECH", "USENERGY", "GLDMINE", "DAX", "JP225", "HK50"}
STOCKS = {"TSLA", "NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AMD", "INTC", "ORCL", "PLTR", "HOOD", "COIN", "CRCL", "BABA",
          "NFLX", "MSTR", "AVGO", "TSM", "UBER", "DIS", "JPM", "V", "MA", "WMT", "COST", "SMCI", "ARM", "SNOW", "SHOP", "PYPL", "SQ", "RDDT", "GME", "AMC",
          "MU", "SNDK", "LLY", "SKHX", "TENCENT", "XIAOMI", "BMNR", "RTX", "NKE", "BA", "IBM", "QCOM", "TXN", "PEP", "KO", "XOM", "CVX"}
STABLES = {"USDE", "USDC", "USDT", "DAI", "USDH", "FDUSD", "PYUSD"}
STOCK_DEXES = {"xyz", "flx", "km", "vntl", "abcd", "cash"}     # side markets that list stocks / commodities / forex
PRE_IPO = {"SPACEX", "OPENAI", "ANTHROPIC", "STRIPE", "XAI", "DATABRICKS", "PERPLEXITY"}
CRYPTO_ON_BUILDER = {"BTC", "ETH", "SOL", "HYPE", "XRP", "BNB", "DOGE", "SUI", "ZEC", "XMR", "ENA", "LIT", "LIGHTER", "PUMP", "FARTCOIN", "USDE"}

_CG = {"t": 0, "memes": set(), "known": set()}
def coingecko_lists(cache_file=None):
    """Meme symbols (CoinGecko 'meme-token' category, top 1000) + known coins (top 1000 by market cap). Refreshed daily."""
    if cache_file:
        try:
            c = json.load(open(cache_file))
            if time.time() - c["t"] < 86400: _CG.update(t=c["t"], memes=set(c["memes"]), known=set(c["known"])); return _CG
        except Exception: pass
    if time.time() - _CG["t"] < 86400 and _CG["memes"]: return _CG
    S = requests.Session(); memes, known = set(), set()
    def page(params):
        for k in range(4):
            try:
                r = S.get("https://api.coingecko.com/api/v3/coins/markets", params=params, timeout=25)
                if r.status_code == 429: time.sleep(30 * (k + 1)); continue
                if r.ok: return r.json()
            except Exception: time.sleep(5)
        return []
    for pg in (1, 2, 3, 4):
        memes |= {x["symbol"].upper() for x in page({"vs_currency": "usd", "category": "meme-token", "per_page": 250, "page": pg})}; time.sleep(6)
    for pg in (1, 2):    # top 500 coins by value; keep those worth $500M+
        known |= {x["symbol"].upper() for x in page({"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": pg})
                  if (x.get("market_cap") or 0) >= 500e6}; time.sleep(6)
    if memes and known:
        _CG.update(t=time.time(), memes=memes, known=known)
        if cache_file: json.dump({"t": _CG["t"], "memes": sorted(memes), "known": sorted(known)}, open(cache_file, "w"))
    return _CG

def daily_vol(closes):
    r = np.diff(np.log(np.asarray(closes, dtype=float)))
    return float(np.std(r)) if len(r) >= 10 else None

def classify(name, venue="hyperliquid", vol=None, btc_vol=None, age_h=None, launchpad=None, cg=None):
    """Returns (type, reason). name = Hyperliquid market name (e.g. 'BTC', 'kPEPE', 'flx:OIL') or a Solana token symbol."""
    cg = cg or _CG
    if venue == "solana":
        if launchpad or (age_h is not None and age_h <= 7 * 24):
            return NEW_MEME, f"new Solana coin ({'launched on ' + launchpad if launchpad else f'{age_h:.0f} hours old'})"
        if name.upper() in cg["memes"]: return MEME, "Solana coin in CoinGecko's meme list"
        return UNKNOWN, "Solana coin, not new and not a known meme"
    dex, base = (name.split(":", 1) if ":" in name else (None, name))
    b = base.upper()
    if dex:   # builder-deployed markets: commodities, stocks, indexes, forex live here
        if b in COMMODITIES: return COMMODITY, f"'{b}' is a commodity (market {name})"
        if b in FX_BONDS: return FOREX, f"'{b}' is a currency/bond market"
        if b in INDEXES: return STOCK, f"'{b}' is a stock index / sector basket"
        if b in STOCKS: return STOCK, f"'{b}' is a company stock"
        if b in PRE_IPO: return PREIPO, f"'{b}' is a pre-IPO company (very thin, not traded)"
        bb = b[4:] if b.startswith("1000") else b
        if b in STABLES: return UNKNOWN, f"{b} is a stablecoin (worth $1) — nothing to trade"
        if b in CRYPTO_ON_BUILDER or bb in cg["memes"] or bb in cg["known"]: base = bb   # crypto on a side market -> judge as crypto below
        elif dex in STOCK_DEXES: return STOCK, f"'{b}' isn't a crypto coin and is listed on a stocks/commodities market ({dex}) — treated as a stock"
        else: return UNKNOWN, f"'{name}' isn't recognised"
    raw = base[1:] if base.startswith("k") and base[1:].isupper() else base   # kPEPE = 1000 PEPE
    r = raw.upper()
    if r in MAJORS: return MAJOR, f"{r} is one of the biggest coins"
    if r in COMMODITIES and r in {"PAXG", "XAUT"}: return COMMODITY, f"{r} is a gold-backed token"
    if r in STABLES: return UNKNOWN, f"{r} is a stablecoin (worth $1) — nothing to trade"
    if r in cg["memes"]: return MEME, f"{r} is in CoinGecko's meme-coin list" + (" (k = 1000 units)" if raw != base else "")
    if r in cg["known"]: return ALT, f"{r} is an established coin (worth $500M+ on CoinGecko)"
    if vol and btc_vol and vol >= 3 * btc_vol:       # only for coins CoinGecko doesn't list as established
        return MEME, f"{r} isn't an established coin and swings {vol / btc_vol:.1f}x as much as BTC — behaves like a meme coin"
    if vol and btc_vol: return ALT, f"{r} is a crypto coin (swings {vol / btc_vol:.1f}x BTC)"
    return UNKNOWN, f"not enough information about '{name}'"
