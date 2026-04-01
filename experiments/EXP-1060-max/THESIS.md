# EXP-1060-max: Earnings Event Alpha

## Hypothesis

IV crush after earnings creates predictable credit spread opportunities.
Pre-earnings IV expansion inflates option prices; post-earnings IV
collapse creates a systematic edge for premium sellers who enter 1 day
after the announcement.

## Key Features

1. **Earnings calendar** with IV rank signal (strong_sell_vol / sell_vol / skip)
2. **Pre-earnings IV expansion detector** — flags stocks with IV rank > 50
3. **Post-earnings IV crush entry** — credit spreads entered after crush
4. **Historical backtest** on high-IV stocks (IV rank > 50, crush > 10%)
5. **Sector clustering** — analyse earnings waves by sector

## Why This Is Uncorrelated

Earnings alpha is driven by idiosyncratic IV dynamics, not market direction.
Expected correlation to SPY: ~0.15. This makes it a diversifying alpha
source alongside the core credit spread strategy.

## Status: COMPLETE
- compass/earnings_alpha.py: 380+ lines
- tests/test_earnings_alpha.py: 33 tests, all passing
