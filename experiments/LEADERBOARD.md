# Experiment Leaderboard

Ranked by composite score: **(Sharpe × CAGR) / Max DD** (higher = better risk-adjusted returns).

## Top 10

| Rank | Experiment | CAGR | Sharpe | Max DD | Win Rate | Score | Status |
|------|-----------|------|--------|--------|----------|-------|--------|
| 🥇 1 | **EXP-910-max** | 80.0% | 8.46 | 2.8% | 85% | **241.7** | North Star Integration |
| 🥈 2 | **EXP-860-max** | ~25%* | 12.30 | 1.9% | 89.6% | **161.8** | Adaptive Retraining |
| 🥉 3 | **EXP-960-max** | 102% | 4.97† | 9.8% | — | **51.7** | 100% CAGR Path |
| 4 | **EXP-880-max** ⭐ | 76.9% | 4.97 | 10.2% | — | **37.5** | PRODUCTION CONFIG |
| 5 | **EXP-840-max** | 56.1% | 4.84 | 4.6% | — | **59.0** | Regime Leverage 2x |
| 6 | **EXP-810-max** | ~20%* | 10.49 | 3.6% | — | **58.3** | Model Ensemble |
| 7 | **EXP-970-max** (3.5x) | 45.8% | 4.5† | 7.8% | — | **26.4** | Walk-Forward Leverage |
| 8 | **EXP-950-max** | 45.2% | 4.5† | 10.2% | — | **19.9** | Leverage Frontier |
| 9 | **EXP-970-max** (2.5x) | 36.4% | 3.5† | 5.6% | — | **22.8** | Walk-Forward Conservative |
| 10 | **EXP-870-max** | ~15%* | 1.26 | 0.7% | — | **27.0** | Multi-Underlying |

*Estimated CAGR where not directly reported. †Estimated Sharpe from related experiments.

**Score = (Sharpe × CAGR) / Max DD** — rewards high returns at low risk.

## Paper Trading Recommendations

### Immediate (Week 1-4)
1. **EXP-880-max** — Production config: 76.9% CAGR, Sharpe 4.97, DD 10.2%
   - Best overall risk-adjusted returns at production-viable settings
   - Crisis hedge V2 validated through COVID + 2022
   - Full deployment blueprint ready (EXP-890)

### After Paper Validation (Month 2-3)
2. **EXP-910-max** — North Star integrated: 80% CAGR, Sharpe 8.46, DD 2.8%
   - Highest composite score but more complex (multi-underlying)
   - Requires multi-broker setup for full capacity
   - Paper trade on SPY first, add underlyings incrementally

### Research Priority
3. **EXP-860-max** — Adaptive retraining: Sharpe 12.30, DD 1.9%
   - Extraordinary Sharpe but needs live validation of retraining pipeline
   - Quarterly retraining must be automated and monitored
   - Key risk: model degradation between retrain cycles

## Key Insights

- **EXP-910** has the highest composite score (241.7) but is the most complex
- **EXP-880** is the safest path to production — simpler, proven, deployment-ready
- **EXP-860's** Sharpe of 12.30 is extraordinary but needs live retraining validation
- All top-5 experiments survive 2020 COVID and 2022 bear market
- **EXP-850** (execution analytics) is a prerequisite — $5+ spreads mandatory

## Disqualified / Lower Priority

| Experiment | Reason |
|-----------|--------|
| EXP-820-max | Infrastructure only (no tradeable strategy) |
| EXP-890-max | Infrastructure only (deployment blueprint) |
| EXP-940-max | Report only |
| EXP-990-max | Test infrastructure only |
| EXP-950-max | Superseded by EXP-960 (combined portfolio approach) |
