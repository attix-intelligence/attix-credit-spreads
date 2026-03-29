# Pruned Features Benchmark

**Date:** 2026-03-29
**Dataset:** `compass/training_data_combined.csv` (428 trades, 2020-2025)
**Validation:** 5-fold walk-forward (year-based expanding window)

## Feature Pruning Summary

- Original pipeline features: 31
- Pruned pipeline features: 21
- Features removed: 10

### Removed (present in pipeline):

- `contracts_log` (harmful — hurts AUC)
- `regime_bear` (noise — zero importance)
- `regime_bull` (noise — zero importance)
- `regime_crash` (noise — zero importance)
- `regime_high_vol` (noise — zero importance)
- `regime_low_vol` (noise — zero importance)
- `strategy_type_IC` (noise — zero importance)
- `strategy_type_SS` (noise — zero importance)
- `spread_type_bear_call` (noise — zero importance)
- `spread_type_unknown` (noise — zero importance)

### Already absent from pipeline (pruned by FeaturePipeline):

- `vix_percentile_20d`
- `otm_pct`
- `ma20_slope_ann_pct`
- `spread_width`
- `day_of_week`

## XGBoost: Full vs Pruned

| Metric | Full (31 feat) | Pruned (21 feat) | Delta |
|--------|---------------|-----------------|-------|
| AUC | 0.8025 +/- 0.0751 | 0.8077 +/- 0.0629 | +0.0052 |
| Accuracy | 0.7645 +/- 0.0781 | 0.7680 +/- 0.0742 | +0.0035 |
| Precision | 0.8024 +/- 0.1215 | 0.7932 +/- 0.1230 | -0.0092 |
| Recall | 0.6966 +/- 0.2473 | 0.7367 +/- 0.1966 | +0.0401 |
| Brier Score | 0.1682 +/- 0.0374 | 0.1666 +/- 0.0320 | -0.0016 |
| Signal Sharpe | 3.3211 +/- 3.6684 | 2.9671 +/- 3.9104 | -0.3540 |

### Per-Fold AUC

| Fold | Test Year | Full AUC | Pruned AUC | Delta |
|------|-----------|----------|------------|-------|
| 0 | 2021-01-11 → 2021-12-27 | 0.8149 | 0.8089 | -0.0060 |
| 1 | 2022-01-05 → 2022-12-21 | 0.6733 | 0.6987 | +0.0254 |
| 2 | 2023-01-04 → 2023-12-27 | 0.8519 | 0.8493 | -0.0026 |
| 3 | 2024-01-03 → 2024-12-23 | 0.8140 | 0.8408 | +0.0268 |
| 4 | 2025-01-02 → 2025-12-26 | 0.8583 | 0.8408 | -0.0175 |

## Ensemble: Full vs Pruned

| Metric | Full (31 feat) | Pruned (21 feat) | Delta |
|--------|---------------|-----------------|-------|
| AUC | 0.8277 +/- 0.0708 | 0.8318 +/- 0.0717 | +0.0041 |
| Accuracy | 0.7924 +/- 0.0575 | 0.7890 +/- 0.0636 | -0.0034 |
| Precision | 0.8146 +/- 0.1203 | 0.8117 +/- 0.1266 | -0.0029 |
| Recall | 0.8072 +/- 0.0539 | 0.7985 +/- 0.0690 | -0.0087 |
| Brier Score | 0.1753 +/- 0.0395 | 0.1751 +/- 0.0416 | -0.0002 |
| Signal Sharpe | 2.8862 +/- 4.1876 | 2.8558 +/- 4.2299 | -0.0304 |

## Verdict

- XGBoost AUC delta: **+0.0052** (IMPROVED)
- Ensemble AUC delta: **+0.0041** (IMPROVED)
- Feature reduction: 31 → 21 (10 features removed, 32% reduction)
