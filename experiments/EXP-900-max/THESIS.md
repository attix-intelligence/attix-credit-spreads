# EXP-900-max: Regime Detection Model V2

## Hypothesis

Better regime detection = better leverage timing = higher returns at same
risk.  The rule-based detector (compass/regime.py) is stateless and prone
to whipsaw.  An HMM with lead indicators should detect regime transitions
EARLIER, reducing the lag between reality changing and our positioning
adapting.

## What We're Building

1. HMM with learned emission parameters (not hand-tuned)
2. Lead indicators: yield curve, credit spreads, put/call ratio, breadth
3. Transition probability estimation and change-point prediction
4. Calibrated confidence scores
5. Head-to-head comparison: rules vs HMM vs ensemble on 2020-2025

## Success Criteria

- HMM detects regime transitions ≥3 days earlier than rules
- Whipsaw reduction ≥50% (fewer false regime changes)
- Correct identification of 2020 crash onset and 2022 bear start
- Confidence score calibrated: high confidence = high accuracy
