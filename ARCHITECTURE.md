# Architecture

## File Structure

```
MonitorTheWhituation/
├── CLAUDE.md                  # Project overview for Claude sessions
├── ARCHITECTURE.md            # This file — detailed technical reference
├── server.py                  # Flask backend for local development
├── fetch_data.py              # Standalone data fetcher for GitHub Actions
├── requirements.txt           # Python dependencies (requests, yfinance)
├── .env                       # FRED_API_KEY (local only, git-ignored)
├── .gitignore                 # Ignores .env, data_cache/, __pycache__/, .claude/
├── .github/
│   └── workflows/
│       └── update-data.yml    # GitHub Action: fetch data every 6 hours
├── docs/                      # GitHub Pages root
│   ├── index.html             # Entire frontend (HTML + CSS + JS, single file)
│   └── data.json              # Latest metric data (generated, committed by Action)
└── data_cache/                # Local API response cache (git-ignored)
```

## Data Flow

### Production (GitHub Pages)
```
GitHub Action (every 6h)
  → fetch_data.py
    → FRED API (8 series) + Yahoo Finance (calendar spread)
    → compute derived metrics (crack spread, zones, overall assessment)
    → write docs/data.json
    → git commit & push
  → GitHub Pages rebuilds
  → User loads index.html → fetches data.json → renders dashboard
```

### Local Development
```
python3 server.py (Flask, port 5050)
  → User loads localhost:5050
  → index.html tries data.json (404) → falls back to /api/data
  → server.py fetches from FRED/Yahoo, caches in data_cache/
  → Returns JSON → renders dashboard
```

## The 9 Metrics

### Energy Markets (leading indicators — move within hours)

| Metric | FRED Series | Update Freq | Green | Yellow | Red |
|--------|------------|-------------|-------|--------|-----|
| Brent Crude Oil | DCOILBRENTEU | Daily | ≤$90 | $90–$120 | >$120 |
| Crack Spread (3-2-1) | Calculated from DCOILBRENTEU + DGASNYH + DHOILNYH | Daily | ≤$18 | $18–$30 | >$30 |
| Calendar Spread | Yahoo Finance (BZ contracts) | Daily | ≤$1.50 | $1.50–$3.00 | >$3.00 |

### Economic Stress (lagging indicators — move weeks to months later)

| Metric | FRED Series | Update Freq | Green | Yellow | Red |
|--------|------------|-------------|-------|--------|-----|
| Industrial Production | INDPRO | Monthly | ≥102 | 98–102 | <98 |
| EU Natural Gas | PNGASEUUSDM | Monthly | ≤$10 | $10–$20 | >$20 |
| Capacity Utilization | TCU | Monthly | ≥77% | 73–77% | <73% |

### Financial Contagion (mixed speed)

| Metric | FRED Series | Update Freq | Green | Yellow | Red |
|--------|------------|-------------|-------|--------|-----|
| HY Credit Spread | BAMLH0A0HYM2 | Daily | ≤400 bps | 400–600 bps | >600 bps |
| Jobless Claims | ICSA | Weekly | ≤250K | 250–350K | >350K |
| Inflation Expectations | MICH | Monthly | ≤3.0% | 3.0–4.5% | >4.5% |

## Threshold Rationale

Thresholds are based on historical levels during previous crises:

- **Brent $90/$120**: $90 is the upper end of "normal" post-2020. $120+ has only occurred during acute crises (2008, 2022).
- **Crack spread $18/$30**: Based on 20-year FRED data (2006–2026). Median is $12.54; $18 is ~80th percentile; $30 is ~95th percentile (only exceeded during acute crises like 2022). Hit $71 peak during the 2022 diesel crisis.
- **Calendar spread $1.50/$3.00**: Normal backwardation is $0–$1. Hit ~$5 during Ukraine invasion.
- **Industrial production 102/98**: 2017=100 baseline. Below 98 has historically coincided with recession.
- **EU gas $10/$20**: Pre-COVID normal was ~$5. Hit $70 during 2022 Russia crisis.
- **Capacity utilization 77%/73%**: Long-run average is ~77%. Below 73% correlates with recession.
- **HY credit spread 400/600 bps**: 400 is elevated but manageable. 600+ signals credit stress (hit 2,100 in 2008).
- **Jobless claims 250K/350K**: Pre-COVID normal was ~220K. Sustained 300K+ signals recession.
- **Inflation expectations 3%/4.5%**: Fed target implies ~2.5%. Hit 5.4% in 2022.

## Overall Assessment Logic

Based on zone counts across all 9 metrics:
- **Critical**: 3+ metrics in red
- **Elevated**: 1+ red OR 4+ yellow
- **Caution**: 2+ yellow
- **Stable**: everything else

## Display Transforms

Two FRED series need conversion before display:
- **HY Credit Spread**: FRED reports in percent (e.g., 3.19). Multiply by 100 to show basis points (319 bps).
- **Jobless Claims**: FRED reports raw number (e.g., 205000). Divide by 1000 to show thousands (205K).

These transforms are applied in `package_metric()` in both server.py and fetch_data.py.

## Calendar Spread Contract Logic

Brent futures use month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec.

The ticker format is `BZ{month_code}{2-digit year}.NYM` (e.g., BZK26.NYM = May 2026).

The code tries consecutive contract pairs starting from current month + 1, stepping forward until it finds two contracts that both return data from Yahoo Finance. This handles the monthly expiry roll automatically. If specific contracts fail, it falls back to `BZ=F` (continuous front month) paired with the next available specific contract.

## Adding a New Metric

1. Add to the `METRICS` dict in both `server.py` and `fetch_data.py` with: name, FRED series ID (or custom source), unit, category, description, thresholds, and history_notes.
2. In `fetch_data.py` `main()`: fetch the series and add to the `results` dict.
3. In `server.py` `get_data()`: same as above.
4. In `docs/index.html`:
   - Add to the appropriate `CATEGORIES` array entry
   - Add a `SOURCES` entry with label, url, freq, and optionally liveUrl/liveLabel
   - Add a `CARD_BACKS` entry with what/why/example_label/example
5. The card grid is 3 columns. Adding a 10th metric would leave one card alone in a row — consider adding in pairs or adjusting the grid.
