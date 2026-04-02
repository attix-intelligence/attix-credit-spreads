# Status: COMPLETE — XGBOOST WINS

| Model | OOS Accuracy | Sharpe | Winner |
|-------|-------------|--------|--------|
| Transformer (numpy) | 54.0% | 0.43 | |
| **XGBoost** | **55.9%** | **1.38** | **✓** |

The pure-numpy transformer achieves 54% accuracy — near target (55%) but below XGBoost. Root cause: evolutionary training (gradient-free) can't effectively optimise 40K+ transformer parameters. XGBoost with flattened features is both faster and more effective.

**Finding**: for this dataset size (500 days) and feature count (8), XGBoost dominates. Transformers need (a) gradient-based training (PyTorch), (b) much more data (10K+ sequences), and (c) richer feature inputs to outperform trees.
