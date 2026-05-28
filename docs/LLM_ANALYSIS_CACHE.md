# `data/llm_analysis/` — daily LLM theme cache

This directory is the historical theme cache consumed by the MSR theme
rotation backtest (`backtest/equity_backtester.py`) and the live runner.
It is written by `compass.analysis.llm_categorizer.CategoryAnalyzer` and
read by `strategies.msr_theme_loader.load_themes`.

## File layout (per trade date)

| File | Purpose |
|---|---|
| `{YYYY-MM-DD}.json` | Parsed `CategoryAnalysis` payload — the day's themes |
| `{YYYY-MM-DD}.meta.json` | `{prompt_hash, model, generated_at_utc}` — cache key |
| `raw/{YYYY-MM-DD}_{prompt_hash[:8]}.json` | Full prompt + raw response (audit) |

A directory is **valid** for backtest replay iff for every trade date a
matching pair `{date}.json` + `{date}.meta.json` exists. The `raw/` audit
file is optional for replay but required for reproducibility audits.

## Schema — `{date}.json`

```jsonc
{
  "asof_date":       "2026-05-27",          // ISO date
  "generated_at_utc":"2026-05-28T01:54:28+00:00",
  "model":           "claude-opus-4-7",
  "n_input_tickers": 20,
  "prompt_hash":     "5aebb506...",          // SHA-1 of the prompt
  "raw_response_path":"data/llm_analysis/raw/2026-05-27_5aebb506.json",
  "categories": [
    {
      "name":               "AI Infrastructure Capex",
      "direction":          "bull",          // bull | bear | neutral
      "confidence":         0.88,            // 0.0-1.0
      "tickers":            ["NVDA","AVGO","AMD"],
      "signal_summary":     "...",
      "narrative":          "...",
      "supporting_signals": ["momentum","flow","sentiment","dark_flow"]
    }
  ]
}
```

## Rule Zero — no look-ahead leakage

Backtest replay loads the cache **as if it had been generated on
`asof_date`**. The runtime check is:

```
load_themes(asof_date).generated_at_utc.date() <= asof_date + 1
```

i.e. the LLM analysis must have been produced no later than the trading
day following `asof_date`. This catches accidental regenerations where a
later prompt re-wrote an earlier date's file. The loader raises
`LookaheadError` on violation.

## Coverage status

Phase 1 / 2 (MSR-101 → MSR-203) populate this directory by historical
backfill — see `reports/MULTI_SIGNAL_STRATEGY.md` §10 (Roadmap). At commit
time only the live `2026-05-27` snapshot exists; back-dated files arrive
once the MSR-201 regeneration pass completes.

## Demo directory

`data/llm_analysis_demo/` mirrors this schema for the
`scripts/tradealgo_daily_demo.py` walk-through. Do not mix the two — the
backtest reads only `data/llm_analysis/`.
