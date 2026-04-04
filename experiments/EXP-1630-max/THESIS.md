# EXP-1630: GLD/TLT Relative Value Spread Strategy

## Hypothesis

Gold (GLD) and long-term Treasuries (TLT) are both safe-haven assets that trade
in a relatively stable ratio. When the GLD/TLT price ratio deviates significantly
from its 20-day rolling mean (z-score > ±1.5), the relationship is stretched and
likely to mean-revert.

We exploit this by selling option spreads on both legs simultaneously:
- **z > +1.5** (GLD rich): Sell GLD call spreads + TLT put spreads
- **z < -1.5** (GLD cheap): Sell GLD put spreads + TLT call spreads

Both legs collect theta while waiting for mean reversion. The dual-asset structure
provides diversification — if one leg loses, the other may offset it.

## Method

- Signal: 20-day rolling z-score of GLD/TLT price ratio
- Entry: z exceeds ±1.5, minimum 14 days between trades
- Spread: $2 wide, 5% OTM, ~35 DTE
- Exit: 50% profit target, 3× stop loss, 7 DTE auto-close
- Sizing: 2% of $100K capital per trade, max 10 contracts
- Data: Real IronVault option prices only (GLD ends Mar 2024, TLT ends Jul 2024)
- Walk-forward: IS = 2020-2021, OOS = 2022-2024

## Data Constraints

- GLD option data in IronVault: 2020-01-02 to 2024-03-15
- TLT option data: 2020-01-02 to 2024-07-19
- Strategy can only trade when BOTH tickers have option data available
