# 📚 Meme lessons (learned from past trades)
*Built 2026-10-23 03:08 UTC from week1_2026-10-23*

- **Known dumper wallets:** 124 (coins with 2+ of them among the biggest holders are skipped)

## What happened, by exit reason (practice trades)
- data_earlybird: **crash (rug)** — 19 trades, -70.15
- data_v2: **crash (rug)** — 16 trades, -52.87
- data_earlybird: **hard stop** — 19 trades, -45.73
- data_earlybird: **break-even stop** — 9 trades, -17.73
- data_v2: **biggest holders sold (7-of-20 rule)** — 34 trades, -14.04
- data_v2: **hard stop** — 3 trades, -9.26
- data: **hard stop** — 4 trades, -5.30
- data: **not up 15% in 30 min** — 3 trades, -0.76
- data_v2: **more sellers than buyers for 30 seconds ** — 2 trades, -0.09
- data_earlybird: **more sellers than buyers 3 checks in a r** — 2 trades, +2.22
- data_earlybird: **trailing stop** — 7 trades, +3.67
- data: **trailing stop (20% below peak)** — 1 trades, +4.51
- data_earlybird: **other** — 1 trades, +6.45
- data_earlybird: **biggest holders sold (7-of-20 rule)** — 151 trades, +27.96

## Rules changed because of these lessons (week 2, 2026-10-23)
1. **Costs are real (~6% per buy+sell on new coins)** → max 5 trades a day per system; costs set from Axiom (~1%) + PumpSwap (~1–1.25%) fees.
2. **Half the trades never went up 5% (we bought the top)** → only buy at least 8% below the last 15-minute high, and not after +15% in 5 minutes.
3. **Crashes happened in coins under 1 hour old** → coin must have survived 45 minutes (max 4 hours old).
4. **Crash insiders repeat** → skip coins where 2+ known dumper wallets are among the biggest holders (list grows every crash).
5. **Early Bird had no pool-money alarm** → sell everything when pool money drops 20% from its peak (v2's alarm saved trades).
6. **v2 sold within seconds on old sells** → holder sells from before we bought no longer count; quick flippers (held < 3 min) don't count as 'biggest holders'.