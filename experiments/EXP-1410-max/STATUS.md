# Status: COMPLETE

**Started:** 2026-04-02

## Results
- Multi-window rolling correlations (20/60/120d) + DCC-GARCH estimation
- 3 correlation regimes: normal (<0.30), elevated (0.30-0.50), crisis (>0.50)
- Auto-delevering: linear scale 1.0→0.3 as correlation rises
- Alert system: flags pairwise correlations exceeding threshold
- 25 tests passing

## Value: Insurance-like — rarely triggers, critical when it does
