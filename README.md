# Crypto & Meme Coin System (practice / pretend money)
Part of a 3-system setup (crypto+meme · day trading · stocks) that will later share one "home" app. **No real money. No API keys in this repo.**

## 🧭 The combined system (`src/system/`) — runs live on GitHub every ~5 min
One system, two trading places:
- **Hyperliquid side:** copies the 10 skilled traders' new trades in **major crypto, altcoins, established memes, commodities (oil, gold…), stocks/indexes and forex** — each with its own rules.
- **Axiom side (Solana):** finds brand-new meme coins with the meme safety + timing checks.
- **Detector** (`classifier.py`) labels every coin/market first: 🟦 major · 🟩 altcoin · 🟨 established meme · 🟥 new meme · 🛢️ commodity · 📈 stock/index · 💱 forex/bonds · 🚀 pre-IPO (not traded) · ❔ unknown (not traded).
- **Money:** 85% Safe side (crypto + max 3 macro trades) · 15% Moonshot side (memes).
- Results: `results/system/report.md` (by type) and `results/system/cards/` (every trade explained).

## What's inside
| Folder | What it is |
|---|---|
| `src/copytrading/` | Crypto copy-trading: finds experienced, skilled Hyperliquid traders (12+ months, consistent, statistically strong) and copies their trades with our exits. `l3/l3_live.py` = Level 3 live practice watcher with trade-explanation cards. |
| `src/meme/` | Meme coin practice simulators on live Solana data: `meme_live.py` (Main + Promising book + exit-style comparison + near-misses), `earlybird.py` (brand-new coins, crowd + rug checks, 7-of-20 big-holder exit), `v2.py` (pro/early-wallet scorebook, profit lock, scam alarms — not yet tested), `meme_replay.py` (look-back test). |
| `rules/` | The fixed rules for each test. Rules change only with proof from two separate periods. |
| `data/` | Trader histories (4,177 traders), leaderboard, price candles. (Raw fills, 726 MB, not included — re-downloadable.) |
| `results/` | Snapshots of the live tests (trades, cards, reports), look-back results, copy-trading test logs. |

## Results so far (honest)
- **Crypto copy-trading (skilled veterans):** 90-day tests −2% to +6%, wins ≈ 2.3× the size of losses, worst drop small. Holding BTC beat it in up-markets. Not proven yet.
- **Meme look-back (2 days, 59 coins):** Early Bird +17% avg/trade on paper (+8% without its 3 best) — optimistic (no holder data).
- **Live meme week (in progress):** Main $15→$18.56 · Promising $20→$25.31 · Early Bird ran out of money on day 0.7 (rug pulls), continuing in tracking mode. Two fake wins (pool-drain price glitches) were found and corrected.

## Proven features (kept)
7-of-20 big-holders exit · "not late" rule · take profit at +100% · rug guard (drained pool = $0) · fake-price guard · Early Bird exits. **Dropped:** crypto slow-down rule.
