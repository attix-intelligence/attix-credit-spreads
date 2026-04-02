# EXP-1230-max: Microstructure Alpha Scanner

## Hypothesis

Market microstructure metrics (Amihud illiquidity, Roll spread, Kyle lambda, Corwin-Schultz estimator) detect liquidity regime shifts 1-2 days before price moves. When liquidity dries up (high Amihud, wide Roll) a breakout is imminent — avoid selling credit spreads. When liquidity floods in (low Amihud, tight Roll) mean-reversion dominates — ideal for credit spreads.

## Metrics (8)

1. **Amihud illiquidity**: |return| / dollar volume — higher = less liquid
2. **Roll spread estimator**: -2√(-cov(Δp_t, Δp_{t-1})) — effective spread proxy
3. **Kyle lambda proxy**: |Δprice| / volume — price impact per unit flow
4. **Corwin-Schultz spread**: from daily high-low — bid-ask proxy
5. **Volume-return correlation**: signed volume × return — order flow toxicity
6. **Liquidity ratio**: volume / |return| — inverse Amihud
7. **Spread z-score**: current spread estimate vs 20d average
8. **Liquidity regime**: categorical (tight/normal/wide/crisis)

## Success Criteria

- Liquidity regime predicts next-5-day volatility direction (AUC > 0.55)
- EXP-880 overlay: filtering out wide-spread days improves WR by ≥1pp
- Standalone signal Sharpe > 0.5
