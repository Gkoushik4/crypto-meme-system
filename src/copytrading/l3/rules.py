"""Level 3 rules — FROZEN 2026-10-18 before any live data. Practice only, no real money."""
START_CASH = 85.0            # Safe Engine practice account (per version)
CYCLE_MIN = 10               # check for new trades every 10 minutes
TEAM_SIZE, BENCH_SIZE, RESELECT_EVERY_DAYS = 10, 5, 30
# emergency pause (slow-down removed)
EMERGENCY_PAUSE_DD = 0.10    # down 10% on copied trades -> watch-only + stand-in
RESUME_GAIN = 0.02           # watched trades +2% or a new high -> back
STANDIN_MIN_TRADES_30D = 5   # stand-ins must actually be trading
# trade check
TREND_BARS_4H = 300          # 300 x 4h ≈ 50 days
LATE_ENTRY = 0.01            # price already moved 1%+ our way -> skip
LOW_CONVICTION_X = 0.3       # trade < 0.3x trader's usual size -> skip
WILD_X = 3.0                 # swings > 3x normal -> skip
MIN_VOLUME_24H = 5_000_000   # $ traded in last day
KRONOS_SAMPLES, KRONOS_STRONG = 8, 0.75
# exits (same as tested)
RISK_PER_TRADE, STOP_ATR_MULT = 0.01, 1.5
BREAK_EVEN_AT_R, TRAIL_START_R, TRAIL_R, TAKE_PROFIT_R = 1, 2, 1, 3
MAX_OPEN, MAX_NOTIONAL_X, MAX_HOLD_DAYS = 5, 3.0, 7
SLIPPAGE, FEE = 0.001, 0.00045
