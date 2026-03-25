# Monitor the Whituation

An economic impact dashboard tracking the Strait of Hormuz crisis. Designed to answer one question: is this crisis an "annoyance" (higher prices, forgotten in a year) or "COVID-level" (systemic disruption that reshapes daily life)?

## Quick Reference

- **Live site**: https://doit2whit.github.io/MonitorTheWhituation/
- **Local dev**: `python3 server.py` → http://localhost:5050
- **Frontend**: `docs/index.html` (single file, no framework)
- **Backend (local)**: `server.py` (Flask, port 5050)
- **Backend (production)**: `fetch_data.py` → `docs/data.json` → GitHub Pages (static)
- **Data refresh**: GitHub Action runs every 6 hours, commits updated `data.json`
- **FRED API key**: stored in `.env` locally, GitHub Secret in production

## Key Decisions

- **No framework** — single HTML file with vanilla JS and Chart.js. The dashboard is one page with no routing or state management. Keep it this way.
- **Dual data path** — frontend tries `data.json` first (GitHub Pages), falls back to `/api/data` (local Flask). This lets the same HTML work in both contexts.
- **docs/ not static/** — GitHub Pages only serves from `/` or `/docs/`. We chose `/docs/`. All frontend files live there.
- **server.py is local-only** — it's not deployed anywhere. It exists so Ian can run the dashboard locally with live API calls. `fetch_data.py` is the production equivalent.
- **Free tier only** — no paid APIs, no paid hosting. FRED API (free), Yahoo Finance via yfinance (free), GitHub Pages (free), GitHub Actions (free for public repos).
- **Daily resolution is intentional** — several metrics trade minute-by-minute, but we show daily closes. The dashboard tracks sustained directional moves, not intraday volatility. Live trading links are provided for users who want real-time data.
- **Thresholds are opinionated** — green/yellow/red zones are defined in both `server.py` and `fetch_data.py`. They're based on historical precedent but may need tuning as Ian builds intuition. See ARCHITECTURE.md for threshold rationale.
- **Card flip content is static** — the "What This Measures" / "Why We're Watching It" / historical example text on card backs is hardcoded in the HTML. If metrics change, update this content manually.

## Adding a New Metric

See ARCHITECTURE.md for the full walkthrough. Short version: add it to the METRICS dict in both `server.py` and `fetch_data.py`, add SOURCES/CARD_BACKS entries in `docs/index.html`, and add the key to the appropriate CATEGORIES array.

## Things to Watch Out For

- **Calendar spread contract roll** — `fetch_data.py` tries consecutive month offsets to find active Brent futures contracts. Near expiry dates, the front-month contract may 404 from Yahoo Finance. The fallback logic handles this, but if calendar spread shows "NO DATA", the April→May (or similar) roll is likely the cause.
- **FRED data lag** — some FRED series update with a delay (e.g., capacity utilization is released ~2 weeks after month-end). The "Latest" date on each card shows when the data was actually published, not when we fetched it.
- **GitHub Actions and git conflicts** — the Action commits `data.json` directly to main. If you push code changes at the same moment, you may need `git pull --rebase` before pushing. This has already happened once during development.
