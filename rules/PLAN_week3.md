# Plan — making the meme system smarter (start Mon 2026-10-26 after school)
Practice money only. Every new rule runs **side by side** with the old one so the results prove it before it's kept.

## 0. Where we are (paused at ~day 1 of 7)
| Test | Trades | Result |
|---|---|---|
| Main (pickiest) | 2 | **+$3.95** |
| Early Bird | 1 | −$0.90 |
| v2 Early Pro | 5 | −$18.20 (STARBUCKS −100%: live-feed bug, fixed) |
| Snipe practice / sample / control | 5 / 60 / 30 | −$2.85 / −$14.04 / −$12.70 |
| Final Stretch practice / sample | 5 / 20 | −$2.09 / −$13.52 (won 50%, one −92% crash, best only +28%) |
Lessons: picky wins; winners are cut too early; crashes still too costly; sniping "anything clean" loses; insider exits (creator sold) were profitable.

## 1. Move the tests to GitHub (first)
So they run without using Claude usage and without restart gaps. State backups are in `results/backup/`.

## 2. Self-check + "call Claude" alarm
Detects crashes/errors, data feeds down or fake prices, stuck positions, a rule blocking every trade, unusual losing streaks, tests stopped → writes a plain-English GitHub issue + notification. Claude reviews daily (or every 2–3 days to save usage) and **fixes bugs**; **trading-rule changes always need your go-ahead**.

## 3. Stock → meme look-back (priority — can change earnings)
Match company-named meme coins we already saw (NVIDIA, SpaceX, OpenAI, Starbucks, Grok…) against real stock moves (Hyperliquid prices). Does the coin pump when the stock moves? How fast, how long? Build the "stock alarm" only if the link is real.
**Stock-meme "makes sense" check:** clear link to the company (name/ticker/description/socials), fits today's news, good narrative + real community, the original not a copycat, plus all safety checks.

## 4. pump.fun as an info source (read-only, no login)
Replies/likes and how fast they grow, unique posters, bot spam, King of the Hill, creator's past coins, top holders/traders. (Unofficial data — check it works first.)

## 5. Smarter buying
- **Buyer check:** real crowd vs bots, fresh throw-away wallets, bundles, pros in, known dumpers out, real-money buyers.
- **Hype + narrative rule:** must fit a hot narrative — start with **animals** and **GoFundMe-style/charity** coins; the narrative finder tracks launches, graduations, gains, likes per theme and finds new hot themes. No hype/narrative → no trade.
- **"Big boost" signal:** pump.fun promotion / King of the Hill / sudden jump in likes & replies.
- **SOL weather:** SOL trending up → normal; choppy → smaller; crashing → pause meme buys, tighten stops.
- **Time-of-day stats** (the SEALS trader got in at 6 AM).

## 6. Smarter selling (from the SEALS 16x trade)
- **No time limit for winners.** Sell a small piece on each big spike; **hold the rest while good traders hold and the narrative is hot**.
- **Dead-coin rule only for losers** (below entry, no activity).
- Final Stretch: don't sell everything at graduation; faster live insider exit to stop −92% crashes.
- Old timed rules kept as a shadow for comparison.

## 7. New snipe strategy: follow the smart snipers
Sniper scorebook from the live feed: big wallets buying in the first ~30 s; graded on whether their coins run, whether they hold (not dump within seconds), profit, bundling. ⭐ smart snipers vs ❌ dump bots/insiders (→ dumper list). Snipe only when **2+ smart snipers** buy with real money + insider checks + hot narrative + hype; exit when they sell. Needs a few days of watching before it trusts anyone.

## 8. The scoring brain
Every signal adds/removes points → **win chance + expected profit after ~6% costs**; trade only when clearly positive; bet size by confidence; re-scores held coins live to decide sell more / hold; learns weights slowly from results (needs hundreds of trades — no fooling itself on luck). Optional AI reader for "does this story make sense?" only on finalists.

## 9. Kept as-is / later
- Live feed ~1–5 s late is OK for now (Helius key optional later: faster feed + real holder data).
- Real money only after months of proof (go-live bar: 3+ months, 100+ trades, profit after costs, wins ≥ 3× losses, limited drawdown) — parent decides, trade-only keys, no bank access.

## Order tomorrow
1. GitHub move → 2. self-check alarm → 3. stock look-back → 4. pump.fun data check → 5–7. buyer/hype/narrative, smarter selling, smart-sniper snipe → 8. scoring brain → restart all tests side by side.
