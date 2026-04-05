# EXP-1660: Volatility Risk Premium Harvesting

## Hypothesis

Systematically selling short-dated (7-14 DTE) SPY strangles during low-vol
regimes (VIX < 20) captures the volatility risk premium — implied vol
consistently exceeds realized vol. Adding a long-dated (60-90 DTE) OTM
put hedge limits tail risk to a known maximum, creating a defined-risk
premium harvesting strategy.

## Strategy

- **Entry**: VIX < 20 AND regime ≠ crash AND regime ≠ high_vol
- **Structure**: Sell 10-delta strangle (OTM put + OTM call) at 7-14 DTE
- **Hedge**: Buy 5-delta put at 60-90 DTE (tail protection)
- **Exit**: 50% profit target, 2× premium stop loss, or expiration
- **Sizing**: 2% of capital per trade
- **Spacing**: Minimum 7 days between entries

## Why This Works

1. **VRP is structural**: Option sellers earn a risk premium because hedgers
   (funds, institutions) systematically overpay for protection
2. **Short-dated amplifies theta**: 7-14 DTE options lose value fastest
3. **Low-vol filter**: VIX < 20 avoids entering when crashes are likely
4. **Hedge leg**: Long-dated put limits catastrophic loss scenarios
5. **Strangle**: Captures premium from both sides — works in range-bound markets

## Data Source
All option prices from IronVault (options_cache.db). Zero synthetic data.
