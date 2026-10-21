"""Safe Engine rules. Each rule returns (passed, reason). Thresholds live here in one place."""
import numpy as np
from metrics import (perp_fills, profit_factor, avg_hold_minutes, worst_order_loss,
                     major_share, period_return, max_drawdown, value_at)

RULES = dict(
    max_drawdown=0.15,        # hidden-loss / martingale filter (live: unrealized loss > 15% of balance)
    min_profit_factor=1.5,
    min_hold_minutes=15,
    max_risk_per_trade=0.02,  # worst single losing order vs account value
    max_month_return=2.0,     # "no flashy traders": skip if +200% or more in the scoring window
    min_month_return=0.0,     # must have made money in the scoring window
    min_major_share=0.70,     # Safe Engine: mostly BTC / ETH / SOL
    min_closed_volume=1000,   # need enough closed trades to judge
)


def score_trader(fills, port, start, end, rules=RULES):
    """Report card + pass/fail for one trader, using ONLY data inside [start, end)."""
    fl = perp_fills(fills, start, end)
    card = {"fills": len(fl)}
    card["profit_factor"] = profit_factor(fl)
    card["hold_min"], card["closed_vol"] = avg_hold_minutes(fl)
    av = value_at(port["av"], start) if port else np.nan
    card["account_value"] = av
    card["risk_per_trade"] = worst_order_loss(fl) / av if av and av > 0 else np.nan
    card["major_share"] = major_share(fl)
    card["month_return"] = period_return(port, start, end) if port else np.nan
    card["drawdown"] = max_drawdown(port, start, end) if port else np.nan

    checks = [
        ("enough data", card["fills"] >= 10 and card["closed_vol"] >= rules["min_closed_volume"]
         and not np.isnan(card["month_return"])),
        ("hidden losses / drawdown ≤ 15%", not np.isnan(card["drawdown"]) and card["drawdown"] > -rules["max_drawdown"]),
        ("profit factor ≥ 1.5", not np.isnan(card["profit_factor"]) and card["profit_factor"] >= rules["min_profit_factor"]),
        ("avg hold ≥ 15 min", not np.isnan(card["hold_min"]) and card["hold_min"] >= rules["min_hold_minutes"]),
        ("risk per trade ≤ 2%", not np.isnan(card["risk_per_trade"]) and card["risk_per_trade"] <= rules["max_risk_per_trade"]),
        ("not flashy (< +200%)", not np.isnan(card["month_return"]) and card["month_return"] < rules["max_month_return"]),
        ("made money", not np.isnan(card["month_return"]) and card["month_return"] > rules["min_month_return"]),
        ("mostly BTC/ETH/SOL", not np.isnan(card["major_share"]) and card["major_share"] >= rules["min_major_share"]),
    ]
    card["failed"] = [name for name, ok in checks if not ok]
    card["passed"] = not card["failed"]
    return card
