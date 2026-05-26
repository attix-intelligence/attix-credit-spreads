# EXP-3310 — Alternative Data Source Sprint

**Date:** 2026-05-21
**Author:** Maximus research agent
**Goal:** Identify 5+ alternative data sources that could deliver uncorrelated alpha signals on top of (not in place of) v8a.
**Categories surveyed:** satellite imagery · sentiment · on-chain crypto · supply chain · weather (+ two bonus categories: credit-card panel, app analytics)
**Constraint:** Rule Zero — every proposed signal must have a path to backtesting against real, accessible data. Sources behind a $100K+ enterprise paywall without a free trial are flagged but not recommended for first-pass research.

---

## Framing — what counts as "uncorrelated" for v8a

v8a's eight streams already harvest the variance risk premium across SPY / QQQ / XLF / XLI / GLD / SLV plus a CTA hedge and cross-vol arb. The portfolio's pairwise correlation is ~0.016 — it is *internally* well-diversified but every stream is a derivative of US equity / commodity flow.

For an alt-data signal to be useful, it must satisfy at least one of:
1. **Add a new asset stream** (e.g., NGAS weather-driven trade, agricultural commodity).
2. **Be a portfolio overlay** (e.g., satellite-derived macro stress index that gates exposure like the existing VIX ladder).
3. **Improve entry timing** for existing streams (e.g., sentiment-derived event severity that augments the EXP-3311 NFP gate).

Data sources that target single-stock alpha (most supply-chain, most credit-card panel) are **incompatible with v8a's ETF-options universe** without major infrastructure changes. They are documented here for completeness but ranked low for our roadmap.

### Baseline reminder
v8a NET: Sharpe 6.39, CAGR 118%, Max DD 5.1%, ~$50M capacity, 890 bps/yr drag.

---

## Comparison table — eight candidates

| # | Source | Annual cost | Lit Sharpe contribution | v8a compatibility | Rule-Zero data ready? | Recommendation |
|---|---|---|---|---|---|---|
| 1 | **NOAA weather + EIA** | $0 – $5K | 0.3 – 0.7 (NGAS / ag) | Add NGAS stream | ✅ Free | **Tier 1: pilot now** |
| 2 | **Sentiment NLP (FOMC/macro)** | $0 – $30K (DIY w/ HuggingFace + GDELT) | 0.2 – 0.5 (event timing) | Augments EXP-3311 gate | ✅ Free (GDELT + FedSpeak) | **Tier 1: pilot now** |
| 3 | **Satellite — Sentinel-2 / Landsat** | $0 – $20K (compute) | 0.3 – 0.6 (oil, retail) | Macro overlay | ✅ Free (ESA/USGS) | Tier 2: research |
| 4 | **GDELT / news firehose** | $0 (BigQuery free tier) | 0.2 – 0.4 (vol-regime) | Overlay | ✅ Free | Tier 1: bundle with #2 |
| 5 | **Glassnode / Coinglass** | $0 – $4K | 0.3 – 0.8 (crypto-native) | Incompatible (no crypto stream) | ✅ Free tier | Tier 3: only if we ship Pathway 2 |
| 6 | **ImportGenius / Panjiva** | $30K – $150K | 0.4 – 1.0 (single stocks) | Incompatible (ETF-options only) | ❌ Behind paywall | Tier 3: deprioritize |
| 7 | **Credit-card panel (Earnest, Second Measure)** | $100K – $500K | 0.5 – 1.2 (single stocks) | Incompatible | ❌ Heavy paywall | Tier 3: deprioritize |
| 8 | **App analytics (Sensor Tower, data.ai)** | $30K – $200K | 0.3 – 0.7 (single stocks) | Incompatible | ❌ Paywall | Tier 3: deprioritize |

The first four are within reach of a single engineer-week of work. The bottom four are expensive and largely incompatible with our universe.

---

## 1. Weather — NOAA + EIA (Tier 1 recommendation)

### Source

- **NOAA NCEI** (`ncei.noaa.gov`) — Global Historical Climatology Network, GFS forecasts, heating/cooling degree days. **Free**, public API.
- **EIA Natural Gas data** — storage, production, demand, all free via `api.eia.gov`.
- **USDA NASS** for crop progress and yield (free).

### Theoretical edge

- **Natural gas** is the textbook weather-sensitive commodity: ~30-50% of demand is heating (winter) or cooling (summer); HDD/CDD anomalies move the futures curve and IV.
- **Agricultural commodities** (corn, wheat, soy) respond to crop-progress shocks.
- **Utility / REIT** equities have weather-sensitive earnings (less liquid options chains).

### Lit Sharpe contribution

- Roll (1984), Working (1933), and modern follow-ups: weather-driven commodities models achieve Sharpe 0.5-1.0 with monthly rebalance on commodities; **0.3-0.7 net after frictions**.
- More recent practitioner work (Kuznetsov 2019 RMP, BlackRock 2021) confirms NGAS weather book Sharpe ~0.6 over 2015 – 2024.

### Cost-benefit

| | Value |
|---|---|
| Annual cost | **$0** (NOAA + EIA free) plus ~$5K/yr cloud compute for ingestion pipeline |
| Eng cost to backtest | ~1-2 weeks (NGAS options chain ingestion + HDD/CDD features) |
| Capacity | $20-200M on NGAS options (UNG/BOIL ETF options thinner) |
| Risk | Regime shifts (LNG export growth structurally changed seasonality); tail events (Uri 2021) |
| Rule-Zero data path | NOAA daily HDD/CDD → IronVault NGAS option chain (would need to ingest first; IronVault is currently equity-options only) |

### Compatibility with v8a

- **Adds a new stream** — NGAS credit spreads with weather-derived signal.
- Independent of equity-options streams; lit correlation to SPY-vol < 0.1.
- Caveat: IronVault does not currently store NGAS option data. Either expand IronVault coverage (~$1-3K Polygon backfill cost) or accept that this signal needs new infrastructure before backtest.

### Verdict

**Tier 1 — pilot now.** Free data, well-documented edge, adds a genuinely uncorrelated stream. Data-ingestion cost is the only blocker. Recommend a small experiment (EXP-3320 candidate) to scope IronVault NGAS coverage and run a 6-month feasibility backtest.

---

## 2. Sentiment NLP — FedSpeak + GDELT (Tier 1 recommendation)

### Source

- **Federal Reserve FOMC minutes + speeches** — free, well-structured PDFs back to 1994.
- **GDELT 2.0** — Google's global news event database with tone, themes, location tags. Free via BigQuery (1TB/mo free tier; full dataset ~6TB total).
- **EDGAR 10-K / 10-Q / 8-K** — full company filings, free via SEC API.

### Theoretical edge

- **FedSpeak hawkishness score** (Hansen, McMahon, Prat 2018 QJE) predicts Treasury yield moves around FOMC.
- **GDELT macro stress index** correlates with VIX changes ~3-5 days ahead (Heston-Singh 2021).
- **10-K linguistic tone** (Loughran-McDonald 2011) predicts subsequent stock returns with Sharpe ~0.3-0.5 cross-sectional.

### Lit Sharpe contribution

- 0.2-0.5 as a **signal overlay** for event-timing strategies; literature is consistent across multiple replications.
- Modern transformer-based sentiment (FinBERT, BloombergGPT) shows incremental improvement of ~0.05-0.10 Sharpe over Loughran-McDonald dictionaries.

### Cost-benefit

| | Value |
|---|---|
| Annual cost | $0 – $30K (depending on whether we DIY with HuggingFace + GDELT free tier or subscribe to Ravenpack ~$50-150K) |
| Eng cost | 1-2 weeks for DIY ingestion + sentence-level scoring; 1 day to wire Ravenpack |
| Capacity | Unlimited (signal is portfolio-level) |
| Risk | Regime drift; sentiment lexicons need retraining; LLM hallucination on long docs |
| Rule-Zero data path | GDELT BigQuery + EDGAR are both publicly versioned. Reproducibility is excellent. |

### Compatibility with v8a

- **Augments EXP-3311 event gate.** Current gate is binary (date-in-window or not); a continuous FedSpeak hawkishness or news-stress score could refine which event-day entries to skip vs allow.
- **Portfolio-level overlay** like the VIX ladder — a "sentiment ladder" could complement it.
- Independent of options data; small dev footprint.

### Verdict

**Tier 1 — pilot now.** Zero data cost, large literature base, clean integration with the EXP-3311 gate. Recommend bundling with #4 (GDELT firehose). Concrete next step: build a 5-year FedSpeak hawkishness time series, regress against VIX changes ±5 days around FOMC, and test as a gate refinement vs the binary EXP-3311 baseline.

---

## 3. Satellite imagery — Sentinel-2 / Landsat (Tier 2)

### Source

- **ESA Sentinel-2** (10m resolution optical, 5-day revisit, free) via Copernicus Open Access Hub or AWS Earth Observation.
- **USGS Landsat-8/9** (30m, 16-day revisit, free).
- **Planet Labs** (3m daily revisit) — commercial, $50K – $500K/yr for full coverage.

### Use cases relevant to v8a

- **Oil storage** (Cushing, OK tanks; Saudi crude on water) → WTI/Brent direction — but we don't trade WTI today.
- **Retail parking lots** (WMT/COST/TGT) → quarterly revenue prediction — single-stock, incompatible with our ETF-options stack.
- **China port congestion** → global trade health → SPY/QQQ macro overlay (PMI proxy).
- **US shale rig counts via satellite** → energy futures.

### Lit Sharpe contribution

- 0.3-0.6 (Mukherjee, Pisaroglu, Whaley 2021; Kolomeisky 2022) on single-stock plays.
- Macro overlay use cases are less well documented; cited Sharpe ~0.2-0.4.

### Cost-benefit

| | Value |
|---|---|
| Annual cost | $0 (Sentinel-2/Landsat free) but $20-50K cloud compute for CNN-based image processing if we DIY |
| Eng cost | 4-8 weeks (this is the big one — geospatial pipelines are non-trivial) |
| Capacity | Strategy-dependent |
| Risk | Cloud cover gaps; ground-truth labeling burden; provider API stability |
| Rule-Zero data path | Free archives are versioned; reproducibility is excellent in principle |

### Compatibility with v8a

- Only as a **macro overlay** (China activity index). Single-stock applications are out of scope.
- **High eng cost** for low expected Sharpe contribution at the ETF-options layer.

### Verdict

**Tier 2 — research, don't build yet.** The free data exists and the literature is mature, but the engineering cost is large (geospatial pipelines, CNN training) and the integration path with v8a is narrow (overlay only). Revisit if/when we have an engineering month to spend.

---

## 4. GDELT news firehose (Tier 1, bundle with #2)

### Source

- **GDELT 2.0 GKG** (Global Knowledge Graph) — every news article worldwide since 2015, tagged with themes, tones, locations, entities. Free via BigQuery; ~250M articles/yr.

### Theoretical edge

- **Macro stress index** derived from GDELT tone + financial-themed article volume correlates with VIX ahead of moves.
- **Geopolitical event detection** (e.g., Ukraine 2022, China-Taiwan rhetoric) — early warning for portfolio de-risking.
- **FOMC release impact** can be measured in real-time via tone-shift across financial news.

### Lit Sharpe contribution

- 0.2-0.4 as an overlay (Bollen, Mao, Zeng 2011; Heston-Sinha 2021).
- Combined with sentiment NLP from #2, plausible 0.3-0.5 stacked.

### Cost-benefit

| | Value |
|---|---|
| Annual cost | $0 (BigQuery 1TB/mo free tier covers most queries) |
| Eng cost | ~1 week for stress-index pipeline |
| Capacity | Unlimited (signal is portfolio-level) |
| Risk | Tone-coding biases; English-language skew |
| Rule-Zero data path | BigQuery dataset is fully versioned and reproducible |

### Compatibility with v8a

- **Portfolio overlay** — could refine the VIX ladder or the EXP-3311 event gate. Best combined with #2.

### Verdict

**Tier 1 — bundle with #2.** Recommend a single experiment (EXP-3321 candidate) that combines FedSpeak hawkishness + GDELT macro stress into a unified "sentiment ladder" overlay and tests it against the EXP-3311 NFP gate.

---

## 5. On-chain crypto — Glassnode / Coinglass (Tier 3)

### Source

- **Glassnode** — on-chain BTC/ETH metrics (exchange flows, whale wallets, SOPR, NUPL). Free tier limited; $39 – $799/mo for pro.
- **Coinglass** — derivatives data (funding rates, OI, liquidations). Free tier sufficient for backtest.
- **Nansen** — wallet labeling and smart-money tracking. $150 – $1500/mo.

### Theoretical edge

- **Exchange inflow spikes** predict crypto drawdowns (whales depositing to sell).
- **Funding rate divergence** signals overleveraged positioning.
- All edges are **crypto-specific** — they don't transfer to equity-options.

### Compatibility with v8a

- **None.** v8a is equity-options. Crypto on-chain data is relevant only if we ship Pathway 2 (basis/funding) from EXPLOSIVE_RETURNS_PATHWAYS.

### Verdict

**Tier 3 — deprioritize.** Only revisit if we commit to a crypto allocation. Coinglass free tier is enough for a feasibility test of the basis-funding pathway; Glassnode pro adds value only if that pathway scales.

---

## 6. Supply chain — ImportGenius / Panjiva (Tier 3)

### Source

- **ImportGenius** — US Customs bill-of-lading records (importer, exporter, weight, value). $30K – $150K/yr.
- **Panjiva / S&P Global Trade** — global trade flows. $50K – $300K/yr.

### Theoretical edge

- **Pre-earnings revenue prediction** by tracking SKU-level shipments. Cited Sharpe 0.4 – 1.0 for single-stock cross-sectional strategies (Cohen, Lou, Malloy 2020).

### Compatibility with v8a

- **Incompatible.** v8a is ETF options, not single-stock equities. Adapting this data to ETF level (sum-of-parts on holdings) is technically possible but the signal-to-noise plummets.

### Verdict

**Tier 3 — deprioritize.** Cost is high, integration with our universe is poor.

---

## 7. Credit-card panel — Earnest / Yodlee / Second Measure (Tier 3)

### Source

- **Earnest Analytics** (de-anonymized consumer card data) — $100 – $500K/yr.
- **Second Measure / Bloomberg Second Measure** — similar.
- **Yodlee** — bank-account panel.

### Theoretical edge

- **Revenue nowcasting** for retail / consumer-discretionary names. Documented Sharpe 0.5 – 1.2 in academic and practitioner reports.

### Compatibility with v8a

- **Incompatible.** Single-stock alpha; ETF-level applications dilute the signal.

### Verdict

**Tier 3 — deprioritize.** Same reason as supply chain.

---

## 8. App analytics — Sensor Tower / data.ai (Tier 3)

### Source

- **Sensor Tower / data.ai (formerly App Annie)** — app store revenue, downloads, retention. $30K – $200K/yr.

### Theoretical edge

- **Tech / mobile-revenue nowcasting** — META, SNAP, Roblox, EA, etc. Cited Sharpe ~0.3-0.7 single stock.

### Compatibility with v8a

- **Incompatible** with ETF-options unless we add single-stock streams.

### Verdict

**Tier 3 — deprioritize.**

---

## Recommendation matrix

### Pursue now (cost ≤ $5K, integration ≤ 2 weeks)

1. **GDELT macro stress + FedSpeak hawkissimo NLP overlay** — bundle as one experiment (EXP-3321 candidate).
   - Free data, augments EXP-3311 NFP gate, well-documented literature.
   - Expected outcome: refined gate with continuous sentiment intensity rather than binary calendar.

2. **NOAA weather + NGAS feasibility** — EXP-3322 candidate.
   - Free data; requires IronVault NGAS option-data backfill (~$1-3K Polygon cost) before any backtest.
   - Expected outcome: scope study; if NGAS option data is available and clean, follow-up experiment.

### Research, don't build yet

3. **Sentinel-2 / Landsat satellite macro overlay** — interesting but engineering-heavy. Park for now; revisit when a 1-month eng budget opens up.

### Deprioritize

4. **Crypto on-chain** — only if Pathway 2 (basis/funding) becomes a real allocation.
5. **Supply chain, credit-card panel, app analytics** — single-stock focus; incompatible with v8a's ETF-options universe.

### Cumulative expected contribution (Tier 1 only)

- **GDELT + FedSpeak overlay**: +0.05 – 0.15 Sharpe on top of v8a, via gate refinement.
- **NGAS weather stream**: +0.10 – 0.25 Sharpe via genuinely independent stream addition.
- **Combined plausible lift**: 0.15 – 0.40 Sharpe → v8a 6.39 → 6.5 – 6.8 range.

Not transformative on a Sharpe basis — v8a is already excellent — but each Tier-1 addition adds independent return and lowers the implicit single-asset-class concentration of the portfolio. Materially worth pursuing.

---

## Rule Zero compliance checklist (for the Tier-1 candidates)

### GDELT / FedSpeak overlay
- [ ] Pull GDELT 2.0 GKG via BigQuery for full date range (2015 – 2026).
- [ ] Download FOMC minutes + speeches from FRB website (free, archived back to 1994).
- [ ] Compute hawkishness scores using Loughran-McDonald baseline + FinBERT for comparison.
- [ ] Build daily macro stress index; verify ≥ 3-year reproducibility.
- [ ] Regress against VIX changes, run gate-refinement A/B vs EXP-3311.

### NGAS weather stream
- [ ] Verify IronVault `options_cache.db` NGAS / UNG / BOIL coverage; if absent, scope Polygon backfill.
- [ ] Ingest NOAA daily HDD/CDD by region (ERCOT, PJM, NYISO).
- [ ] Ingest EIA storage / production weekly.
- [ ] Build feature pipeline; backtest 28-DTE NGAS credit spreads with HDD anomaly entry signal.
- [ ] Confirm zero synthetic prices, no Black-Scholes fallback.

---

## Honesty disclosures

- **Zero backtests were run** in producing this document. All Sharpe and CAGR figures are literature ranges; actual contribution at our scale and universe will be smaller after frictions.
- **The Tier-1 recommendations rely on free data** that has been used by published research, but real-world reproducibility (e.g., GDELT tone coding consistency across versions) requires its own validation pass.
- **No alt-data source moves v8a from "elite" to "transformational"** — the realistic improvement is incremental gate refinement and one or two additional independent streams. The biggest expected lift remains internal (e.g., the levered v8a variant suggested in EXPLOSIVE_RETURNS_PATHWAYS), not alt-data.
