# Rules (fixed before each test)
- Copy-trading Level 3: `../src/copytrading/l3/rules.py` (frozen 2026-10-18)
- Meme Main / Promising: top of `../src/meme/meme_live.py` (frozen 2026-10-19)
- Early Bird: top of `../src/meme/earlybird.py` (frozen 2026-10-19; bug-fixes logged below)
- v2: top of `../src/meme/v2.py` (frozen 2026-10-20, not yet tested)

## Change log
- 2026-10-19 Early Bird: fixed counting holders' sells from before our buy; biggest holders = big wallets ($50+ trades); live trade price instead of stale listed price.
- 2026-10-20 Both meme tests: rug guard (drained pool = coins worth $0); fake-price guard (>2x jump must hold 3 checks with a healthy pool). Corrected fake wins: CT (+1442% → −5%), STREAM (+5049% → −5%).
- 2026-10-20 Early Bird: account ran out of money (day 0.7) → tracking mode to keep collecting data.
- 2026-10-20 Main meme test: added the 7-of-20 biggest-holders exit as a 4th exit style (shadow log on every coin). Main's practice account rules unchanged.
- 2026-10-20 Crypto Level 3: added version 5 (scale out: half at +1R) and version 6 (stop-and-reverse, one flip). Versions 1-4 unchanged. Live run moved to GitHub Actions (every ~5 min), results in results/copytrading_live/.
- 2026-10-20 Market regime detector (src/copytrading/regime.py, frozen): TRENDING / CHOPPY / WILD from BTC 4h. Tested on 8.75 years of BTC+ETH: total +24R vs +1.1R base, worst drop -36% vs -52%; mixed on copy-trade periods. Added to the live run as version 7. Scale-out alone was the worst version over the years (-53.6R): kept in the live test for data, flagged.
- 2026-10-20 Combined system (src/system): coin/market type detector + per-type rules + Hyperliquid & Axiom sides + 85/15 money split + weekend rule for real-world markets. 7-day replay: 14 trades, $100 -> $97.89 (stocks break-even, crypto -$2.12). Live on GitHub (system-live).
