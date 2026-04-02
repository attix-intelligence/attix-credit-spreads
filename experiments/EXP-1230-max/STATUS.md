# Status: COMPLETE — MIXED RESULTS

| Criterion | Target | Actual | Met |
|-----------|--------|--------|-----|
| Vol prediction AUC > 0.55 | 0.55 | 0.490 | ✗ |
| EXP-880 overlay ≥ +1pp | +1pp | **+21.4pp** | ✓ |
| Standalone Sharpe > 0.5 | 0.5 | -0.03 | ✗ |

Liquidity regime distribution: normal 56%, tight 30%, wide 12%, crisis 2%.

Key finding: microstructure metrics have NO standalone predictive power (Sharpe ~0, AUC ~0.5) but are highly effective as an ENTRY FILTER — trading only in tight/normal liquidity adds 21pp to win rate. Use as overlay, not standalone signal.
