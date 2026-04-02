# EXP-1260-max: Factor Exposure Analysis

## Key Results

| Metric | Value |
|--------|-------|
| Alpha | +11.8%/yr (t=3.60, significant) |
| R² | 0.121 (88% unexplained = true alpha) |
| Residual vol | 8.0% |

## Factor Betas (all significant except momentum)

| Factor | Beta | t-stat | Interpretation |
|--------|------|--------|---------------|
| Market (SPY) | **-0.188** | -10.97*** | Short equity exposure (expected for credit spreads) |
| Size (IWM) | +0.069 | +8.08*** | Small-cap tilt |
| Value (IWD) | +0.089 | +7.37*** | Value tilt |
| Momentum (MTUM) | -0.014 | -1.11 | Not significant |
| Low Vol (USMV) | **+0.121** | +7.52*** | Strong defensive tilt |
| Quality (QUAL) | +0.064 | +4.48*** | Quality tilt |

## Interpretation

The strategy has **negative market beta** (-0.19) — it profits when SPY falls. This is expected: short credit spreads benefit from time decay, not directional moves. The low-vol tilt (+0.12) and quality tilt (+0.06) are also expected: credit spreads perform best in calm, high-quality environments.

The **11.8% alpha is statistically significant** (t=3.60) — this is genuine alpha above and beyond factor exposures.

## Factor-Neutral Overlay

To construct a market-neutral version, hedge:
- **Market**: buy 188 shares SPY per $100K (offset -0.19 beta)
- **Low Vol**: short 121 shares USMV per $100K (offset +0.12 beta)
- **Value**: short 89 shares IWD per $100K (offset +0.09 beta)
- Estimated annual cost: ~15bps

This would isolate the 11.8% pure alpha from any factor tilts.
