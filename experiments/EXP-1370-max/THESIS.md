# EXP-1370-max: Momentum Crash Protection

## Hypothesis

Momentum strategies suffer catastrophic drawdowns during sudden reversals. These crashes are predictable via crowding indicators (high dispersion + decaying autocorrelation + accelerating winner-loser spread). Detecting elevated crash risk 1-3 days early → reduce exposure or flip to contrarian.

## Crash Indicators (6)

1. **Momentum dispersion**: cross-sectional std of momentum — high = crowded
2. **Return autocorrelation**: rolling lag-1 autocorrelation — decay signals reversal
3. **Winner-loser spread acceleration**: d/dt of W-L spread — peaking = about to crash
4. **Momentum crowding score**: composite of above three
5. **Short interest proxy**: vol of losers / vol of winners — crowded shorts unwinding
6. **Mean reversion trigger**: winners underperforming losers over 3d = crash starting

## Key Crash Episodes (2020-2025)

- March 2020: COVID crash — momentum crushed as safe-havens reversed
- Nov 2020: vaccine rotation — tech momentum crashed, value surged
- Jan 2021: meme stock short squeeze — momentum shorted stocks exploded
- H1 2022: rate hike regime change — growth/momentum slaughtered
- July 2024: yen carry unwind — momentum crash across global equities

## Success Criteria

- Detect ≥3 of 5 crash episodes 1-3 days early
- Crash-protected portfolio DD < 60% of unprotected
- Return preservation > 80%
