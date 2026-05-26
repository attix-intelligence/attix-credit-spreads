# EXP-3500: SPX 0DTE Baseline (30Δ)

**Strategy:** Conservative 30Δ iron condor baseline
**Ticker:** SPX (0DTE Mon/Wed/Fri)
**Period:** 2023-2024 (2 years)
**Data Source:** CBOE Athena (REAL DATA - Rule Zero Compliant)

## Parameters

- **Short strikes:** 30Δ (both put and call side)
- **Wing width:** $50 (SPX scale)
- **Entry time:** 9:45 AM ET
- **Exit rules:**
  - 50% profit target
  - Hold to expiration if not hit
- **Position sizing:** Fixed 10 contracts (no compounding)
- **Days traded:** Mon/Wed/Fri (SPX 0DTE availability)

## Validation

- ✅ Uses real CBOE bid/ask for fills
- ✅ Uses real CBOE delta for strike selection
- ✅ Uses real CBOE Greeks for analysis
- ✅ Logs data source for audit trail

## Success Criteria

- Win rate: >85%
- Sharpe ratio: >2.0
- Max drawdown: <25%
- Avg daily profit: >$1,000
