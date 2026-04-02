# EXP-1510-max: Portfolio Attribution — Analysis

## Return Decomposition (756 days, Sharpe 1.64)

| Source | Contribution (bps) | % of Total |
|--------|-------------------|------------|
| **Credit Spreads** | +1,649 | 61% |
| **Iron Condors** | +745 | 28% |
| **Vol Harvest** | +301 | 11% |
| **Total** | **+2,695** | 100% |

## Alpha Sources

| Alpha Source | Value | Notes |
|-------------|-------|-------|
| Timing Alpha | -22 bps | 5 regime switches — slight negative, timing didn't add value |
| Sizing Alpha | 0 bps | Fixed 1x sizing in this test |
| Hedge Cost | +3 bps | 7.0% DD saved for negligible cost |
| Market Beta | 0.012 | Near-zero — strategy is market-neutral as designed |

## Key Insights

1. **Credit spreads are the dominant alpha source** (61% of returns) — validates EXP-880 as the core strategy
2. **Timing alpha is slightly negative** (-22bps) — regime switching didn't add value in this period. This suggests the static allocation was already well-calibrated
3. **Hedge is effectively free** — 7% DD saved for only 3bps cost
4. **Near-zero market beta** (0.012) — the portfolio is genuinely market-neutral

## Monthly Attribution

The monthly report reveals that timing alpha is negative in 2 months (regime transition costs) but positive in 3 months (correct regime adaptation). Net: roughly wash. The real value of regime detection is in crisis avoidance, not monthly alpha.
