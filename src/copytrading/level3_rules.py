"""Level 3 rules — FROZEN on 2026-10-18 before any live data. Do not change during the 4–8 week practice test.
Practice only: no real money."""

# Who we copy
TEAM_SIZE = 10            # top 10 skilled veterans (veterans.py skill test, ranked by t-stat)
BENCH_SIZE = 5            # next 5 skilled veterans
RESELECT_EVERY_DAYS = 30  # re-run the skill test monthly

# Slow-down: REMOVED (it lowered results in all 3 test periods).
# Only an emergency pause remains:
EMERGENCY_PAUSE_DD = 0.10  # trader down 10% from their best (on our copy) -> watch-only, stand-in takes the spot
RESUME_GAIN = 0.02         # watched trades recover +2% (or new high) -> back on the team

# Stand-in rule (fixed): a bench trader can only stand in if they are actually trading
STANDIN_MIN_TRADES_30D = 5
STANDIN_MUST_NOT_BE_PAUSED = True

# Trade exits (same as tested)
RISK_PER_TRADE = 0.01      # 1% of the Safe Engine per trade
STOP_ATR_MULT = 1.5
BREAK_EVEN_AT_R = 1
TRAIL_START_R, TRAIL_R = 2, 1
TAKE_PROFIT_R = 3
MAX_OPEN = 5
MAX_HOLD_DAYS = 7

# Versions tracked side by side in the practice test
VERSIONS = ["copy every trade", "copy every trade + emergency pause",
            "emergency pause + trade check", "emergency pause + trade check + really-good-only while paused"]
