"""COMBINED SYSTEM RULES — fixed 2026-10-20. Practice money only. Every number here was decided before testing."""
# ---- money split (your original plan) ----
SAFE_START, MOON_START = 85.0, 15.0          # 85% Safe (crypto + macro), 15% Moonshot (memes)
MACRO_MAX_OPEN = 3                           # commodities / stocks / forex: max 3 open (≈ a quarter of the Safe side's risk)
SAFE_MAX_OPEN, MOON_MAX_OPEN = 5, 3          # crypto positions on the Safe side; meme positions on the Moonshot side
NEW_MEME_MAX_OPEN, NEW_MEME_USD = 2, 5.0     # Axiom side: brand-new Solana memes, $5 each

# ---- rules per type ----
TYPE_RULES = {
    # risk = fraction of its money bucket risked per trade; stop = x normal hourly swing; hold in hours
    "major":            {"bucket": "safe", "risk": 0.010, "stop": 1.5, "hold_h": 168, "scale": None,    "regime": "btc",  "weekend": False},
    "altcoin":          {"bucket": "safe", "risk": 0.010, "stop": 1.5, "hold_h": 168, "scale": None,    "regime": "btc",  "weekend": False},
    "established meme": {"bucket": "moon", "risk": 0.030, "stop": 2.5, "hold_h": 48,  "scale": "always", "regime": "btc_wild_only", "weekend": False},
    "commodity":        {"bucket": "safe", "risk": 0.005, "stop": 1.5, "hold_h": 120, "scale": None,    "regime": "own",  "weekend": True},
    "stock/index":      {"bucket": "safe", "risk": 0.005, "stop": 1.5, "hold_h": 120, "scale": None,    "regime": "own",  "weekend": True},
    "forex/bonds":      {"bucket": "safe", "risk": 0.005, "stop": 1.5, "hold_h": 120, "scale": None,    "regime": "own",  "weekend": True},
}
NOT_TRADED = {"pre-IPO", "unknown"}
MACRO = {"commodity", "stock/index", "forex/bonds"}

# ---- shared exits (same as tested) ----
BREAK_EVEN_R, TRAIL_START_R, TRAIL_R, TAKE_PROFIT_R = 1, 2, 1, 3
SLIPPAGE, FEE, MAX_NOTIONAL_X = 0.001, 0.00045, 3.0

# ---- weekend rule for real-world markets (oil, gold, stocks, forex close on weekends -> price gaps) ----
NO_ENTRY_FROM = (4, 18)      # Friday 18:00 UTC
CLOSE_ALL_AT = (4, 19)       # Friday 19:30 UTC -> close macro positions (minute 30)
REOPEN_AT = (6, 22)          # Sunday 22:00 UTC

# ---- timing ----
HL_EVERY_S, SCAN_EVERY_S, TICK_EVERY_S = 300, 300, 30
