# Rules (fixed before each test)
- Copy-trading Level 3: `../src/copytrading/l3/rules.py` (frozen 2026-10-18)
- Meme Main / Promising: top of `../src/meme/meme_live.py` (frozen 2026-10-19)
- Early Bird: top of `../src/meme/earlybird.py` (frozen 2026-10-19; bug-fixes logged below)
- v2: top of `../src/meme/v2.py` (frozen 2026-10-20; week-2 fixes 2026-10-23)
- Lessons (shared by all meme tests): `../src/meme/lessons.py` + `../results/lessons/lessons.md`

## Change log
- 2026-10-19 Early Bird: fixed counting holders' sells from before our buy; biggest holders = big wallets ($50+ trades); live trade price instead of stale listed price.
- 2026-10-20 Both meme tests: rug guard (drained pool = coins worth $0); fake-price guard (>2x jump must hold 3 checks with a healthy pool). Corrected fake wins: CT (+1442% → −5%), STREAM (+5049% → −5%).
- 2026-10-20 Early Bird: account ran out of money (day 0.7) → tracking mode to keep collecting data.
- 2026-10-20 Main meme test: added the 7-of-20 biggest-holders exit as a 4th exit style (shadow log on every coin). Main's practice account rules unchanged.
- 2026-10-20 Crypto Level 3: added version 5 (scale out: half at +1R) and version 6 (stop-and-reverse, one flip). Versions 1-4 unchanged. Live run moved to GitHub Actions (every ~5 min), results in results/copytrading_live/.
- 2026-10-20 Market regime detector (src/copytrading/regime.py, frozen): TRENDING / CHOPPY / WILD from BTC 4h. Tested on 8.75 years of BTC+ETH: total +24R vs +1.1R base, worst drop -36% vs -52%; mixed on copy-trade periods. Added to the live run as version 7. Scale-out alone was the worst version over the years (-53.6R): kept in the live test for data, flagged.
- 2026-10-20 Combined system (src/system): coin/market type detector + per-type rules + Hyperliquid & Axiom sides + 85/15 money split + weekend rule for real-world markets. 7-day replay: 14 trades, $100 -> $97.89 (stocks break-even, crypto -$2.12). Live on GitHub (system-live).
- 2026-10-20 v2 meme test started (week): pro/early-wallet scorebook, profit lock, scam alarms, 5-second checks, two-source price check, and RUG-RISK MODE (user's idea): high rug-risk coins sell 75% at +150% and the rest at +200%; a safer blend (25% at +50%, 50% at +150%, rest at +200%) is tracked side by side.
- 2026-10-23 **Meme tests restarted from day 0 (week 2)** after week 1 lost money. Week-1 data is kept in `results/archive/week1_2026-10-23/` and taught `src/meme/lessons.py` (124 known dumper wallets to start; it learns more from every crash). Why week 1 lost: ~6% costs per buy+sell × far too many trades (Early Bird 207 in 3 days: costs ≈ $74 of its $92 loss), crashes to $0 in coins under 1 hour old (−$123 across Early Bird + v2), buying the top (half the trades never went +5%), and v2 counting holder sells from before we bought. Fixes (all 3 tests): real costs, max 5 trades/day. Early Bird + v2: coin must be 45 min–4 h old, buy ≥8% under the 15-min high and not after +15% in 5 min, skip coins with 2+ known dumpers among the biggest holders, pool-money −20% alarm, holder sells only after our buy, flippers (held < 3 min) aren't "biggest holders". v2 keeps its wallet scorebook (44,516 wallets). Main's entry/exit rules unchanged (it lost least). Still missing: real holder data (needs a free Helius key in GitHub Secrets).
