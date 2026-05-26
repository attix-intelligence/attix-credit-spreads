#!/bin/bash
# Full system audit — 5 parallel CC sessions

echo "=== PILOTAI CREDIT SPREADS — FULL CODE AUDIT ==="
echo "Session cc1: Core strategy modules (exp1220, exp2160, exp2240, exp1770, exp2020, crisis_alpha_v5)"
echo "Session cc2: Execution & infrastructure (alpaca_connector, scanners, main.py, scheduler)"
echo "Session cc3: Risk management (portfolio_risk_manager, vix_ladder, reconciler, DD circuit breaker)"
echo "Session cc4: Data integrity (IronVault readers, Rule Zero compliance, data pipeline)"
echo "Session cc5: Test coverage & dead code (identify gaps, prune stale modules)"
echo ""
echo "Target: Find what's broken. Fix what matters. Remove what doesn't."
