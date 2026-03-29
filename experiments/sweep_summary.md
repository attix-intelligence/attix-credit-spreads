# Hedge Parameter Sweep Results

Generated: 2026-03-29 08:38 UTC
Total combos evaluated: 1000

## EXP-400

- Combos tested: 500
- Passing (MC P5 DD <= 30%): 500/500
- Best MC P5 DD: -7.2%
- Best config: floor=12.0, ceiling=35.0, stop=1.5, hv_scale=0.1

### Top 10 Configs

| VIX Floor | VIX Ceiling | Base Stop | HV Scale | MC P5 DD | Sharpe | Ann. Return | Pass |
|-----------|-------------|-----------|----------|----------|--------|-------------|------|
| 12 | 35 | 1.5 | 0.10 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 1.5 | 0.15 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 1.5 | 0.25 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 2.0 | 0.10 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 2.0 | 0.15 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 2.0 | 0.25 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 2.5 | 0.10 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 2.5 | 0.15 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 2.5 | 0.25 | -7.2% | 3.247 | 22.5% | PASS |
| 12 | 35 | 3.0 | 0.10 | -7.2% | 3.247 | 22.5% | PASS |

### Parameter Sensitivity

**vix_floor:**
  - 12.0: avg P5 DD=-11.1%, avg Sharpe=2.963, pass rate=100%
  - 14.0: avg P5 DD=-12.5%, avg Sharpe=2.937, pass rate=100%
  - 16.0: avg P5 DD=-14.2%, avg Sharpe=2.890, pass rate=100%
  - 18.0: avg P5 DD=-16.1%, avg Sharpe=2.801, pass rate=100%
  - 20.0: avg P5 DD=-18.3%, avg Sharpe=2.660, pass rate=100%

**vix_ceiling:**
  - 35.0: avg P5 DD=-10.5%, avg Sharpe=3.129, pass rate=100%
  - 38.0: avg P5 DD=-12.5%, avg Sharpe=2.989, pass rate=100%
  - 42.0: avg P5 DD=-14.7%, avg Sharpe=2.826, pass rate=100%
  - 46.0: avg P5 DD=-16.5%, avg Sharpe=2.701, pass rate=100%
  - 50.0: avg P5 DD=-17.8%, avg Sharpe=2.607, pass rate=100%

**base_stop:**
  - 1.5: avg P5 DD=-14.4%, avg Sharpe=2.850, pass rate=100%
  - 2.0: avg P5 DD=-14.4%, avg Sharpe=2.850, pass rate=100%
  - 2.5: avg P5 DD=-14.4%, avg Sharpe=2.850, pass rate=100%
  - 3.0: avg P5 DD=-14.4%, avg Sharpe=2.850, pass rate=100%
  - 3.5: avg P5 DD=-14.4%, avg Sharpe=2.850, pass rate=100%

**hv_scale:**
  - 0.05: avg P5 DD=-14.3%, avg Sharpe=2.874, pass rate=100%
  - 0.1: avg P5 DD=-14.4%, avg Sharpe=2.860, pass rate=100%
  - 0.15: avg P5 DD=-14.5%, avg Sharpe=2.847, pass rate=100%
  - 0.25: avg P5 DD=-14.5%, avg Sharpe=2.820, pass rate=100%

## EXP-401

- Combos tested: 500
- Passing (MC P5 DD <= 30%): 100/500
- Best MC P5 DD: -24.4%
- Best config: floor=12.0, ceiling=35.0, stop=1.5, hv_scale=0.05

### Top 10 Configs

| VIX Floor | VIX Ceiling | Base Stop | HV Scale | MC P5 DD | Sharpe | Ann. Return | Pass |
|-----------|-------------|-----------|----------|----------|--------|-------------|------|
| 12 | 35 | 1.5 | 0.05 | -24.4% | 0.911 | 7.4% | PASS |
| 12 | 35 | 1.5 | 0.10 | -24.4% | 0.910 | 7.4% | PASS |
| 12 | 35 | 1.5 | 0.15 | -24.4% | 0.910 | 7.4% | PASS |
| 12 | 35 | 1.5 | 0.25 | -24.4% | 0.910 | 7.4% | PASS |
| 12 | 35 | 2.0 | 0.05 | -24.4% | 0.911 | 7.4% | PASS |
| 12 | 35 | 2.0 | 0.10 | -24.4% | 0.910 | 7.4% | PASS |
| 12 | 35 | 2.0 | 0.15 | -24.4% | 0.910 | 7.4% | PASS |
| 12 | 35 | 2.0 | 0.25 | -24.4% | 0.910 | 7.4% | PASS |
| 12 | 35 | 2.5 | 0.05 | -24.4% | 0.911 | 7.4% | PASS |
| 12 | 35 | 2.5 | 0.10 | -24.4% | 0.910 | 7.4% | PASS |

### Parameter Sensitivity

**vix_floor:**
  - 12.0: avg P5 DD=-28.6%, avg Sharpe=0.801, pass rate=60%
  - 14.0: avg P5 DD=-31.6%, avg Sharpe=0.782, pass rate=40%
  - 16.0: avg P5 DD=-34.6%, avg Sharpe=0.771, pass rate=0%
  - 18.0: avg P5 DD=-37.8%, avg Sharpe=0.714, pass rate=0%
  - 20.0: avg P5 DD=-40.5%, avg Sharpe=0.646, pass rate=0%

**vix_ceiling:**
  - 35.0: avg P5 DD=-31.3%, avg Sharpe=0.844, pass rate=40%
  - 38.0: avg P5 DD=-33.0%, avg Sharpe=0.789, pass rate=40%
  - 42.0: avg P5 DD=-34.8%, avg Sharpe=0.734, pass rate=20%
  - 46.0: avg P5 DD=-36.4%, avg Sharpe=0.689, pass rate=0%
  - 50.0: avg P5 DD=-37.7%, avg Sharpe=0.656, pass rate=0%

**base_stop:**
  - 1.5: avg P5 DD=-34.6%, avg Sharpe=0.743, pass rate=20%
  - 2.0: avg P5 DD=-34.6%, avg Sharpe=0.743, pass rate=20%
  - 2.5: avg P5 DD=-34.6%, avg Sharpe=0.743, pass rate=20%
  - 3.0: avg P5 DD=-34.6%, avg Sharpe=0.743, pass rate=20%
  - 3.5: avg P5 DD=-34.6%, avg Sharpe=0.743, pass rate=20%

**hv_scale:**
  - 0.05: avg P5 DD=-34.5%, avg Sharpe=0.747, pass rate=20%
  - 0.1: avg P5 DD=-34.6%, avg Sharpe=0.743, pass rate=20%
  - 0.15: avg P5 DD=-34.7%, avg Sharpe=0.742, pass rate=20%
  - 0.25: avg P5 DD=-34.8%, avg Sharpe=0.738, pass rate=20%
