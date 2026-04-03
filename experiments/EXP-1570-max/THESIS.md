# EXP-1570-max: Paper Trading Deployment Package

## Purpose

Production-ready deployment script for EXP-880 paper trading with automated
pre-flight validation.

## Pre-Flight Checks (6 categories)

1. **Config validation**: paper_exp880.yaml structure, crisis hedge params, ML ensemble, leverage
2. **Alpaca API**: connectivity, account status
3. **ML models**: file existence, loadability
4. **Signal generation**: dry-run scoring cycle, crisis hedge init
5. **Crisis hedge params**: cross-check vs EXP-880 + EXP-1520 validation
6. **Infrastructure**: options cache, data dirs, env file

## GO/NO-GO Decision

GO only if ALL required checks pass. Optional/recommended failures are logged but don't block.
