# EXP-1330-max: Pairs Trading for Options

## Hypothesis

Cointegrated equity pairs produce mean-reverting spread signals that
can be monetized by selling credit spreads on the overextended leg.
When the spread exceeds 2σ, sell puts on the underperformer (expecting
reversion up) or sell calls on the outperformer (expecting reversion
down).

## Pairs Universe

| Pair | Sector | Rationale |
|------|--------|-----------|
| SPY/QQQ | Index | Large/tech divergence |
| XLF/JPM | Finance | Sector vs single-name |
| XLK/AAPL | Tech | Sector vs single-name |
| XLE/XOM | Energy | Sector vs single-name |
| GLD/GDX | Gold | Metal vs miners |
| TLT/IEF | Bonds | Duration spread |
| SPY/IWM | Index | Large vs small cap |
| QQQ/SMH | Tech | Broad vs semis |
| XLV/JNJ | Healthcare | Sector vs single-name |
| XLU/NEE | Utilities | Sector vs single-name |
| EEM/EFA | International | EM vs DM |

## Success Criteria

- ≥5 pairs cointegrated (p < 0.05)
- Mean-reversion win rate > 60%
- Annualised Sharpe > 1.0
- Uncorrelated with SPY credit spread alpha (corr < 0.3)
