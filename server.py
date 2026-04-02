import os
import json
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv
import requests
import yfinance as yf

load_dotenv()

app = Flask(__name__, static_folder="docs")
FRED_API_KEY = os.getenv("FRED_API_KEY")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
CACHE_MAX_AGE = 3600 * 6  # 6 hours

os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------
METRICS = {
    "brent_crude": {
        "name": "Brent Crude Oil",
        "fred_id": "DCOILBRENTEU",
        "unit": "$/barrel",
        "category": "Energy Markets",
        "description": "Price of Brent crude oil, the global benchmark.",
        "thresholds": {"green_max": 90, "yellow_max": 120, "direction": "up_is_bad"},
        "history_notes": {
            "2008-07": "2008 peak: $144/bbl before financial crisis",
            "2020-04": "COVID crash: $19/bbl",
            "2022-03": "Ukraine invasion: $128/bbl",
        },
    },
    "crack_spread": {
        "name": "Crack Spread (3-2-1)",
        "fred_ids": ["DCOILBRENTEU", "DGASNYH", "DHOILNYH"],
        "unit": "$/barrel",
        "category": "Energy Markets",
        "description": "Refining margin: cost to turn crude into gasoline & diesel. Measures refinery stress.",
        "thresholds": {"green_max": 18, "yellow_max": 30, "direction": "up_is_bad"},
        "history_notes": {
            "2022-06": "2022 peak: ~$60/bbl during diesel crisis",
            "2019-12": "Pre-COVID normal: ~$15/bbl",
        },
    },
    "calendar_spread": {
        "name": "Brent Calendar Spread",
        "source": "yfinance",
        "unit": "$/barrel",
        "category": "Energy Markets",
        "description": "Front-month minus second-month Brent futures. Positive = backwardation (tight supply).",
        "thresholds": {"green_max": 1.5, "yellow_max": 3.0, "direction": "up_is_bad"},
        "history_notes": {
            "2022-03": "Ukraine invasion: ~$5/bbl backwardation",
            "2020-04": "COVID: -$10/bbl contango (oversupply)",
        },
    },
    "industrial_production": {
        "name": "Industrial Production Index",
        "fred_id": "INDPRO",
        "unit": "Index (2017=100)",
        "category": "Economic Stress",
        "description": "Measures real output of US factories, mines, and utilities. Proxy for manufacturing health.",
        "thresholds": {"green_min": 102, "yellow_min": 98, "direction": "down_is_bad"},
        "history_notes": {
            "2008-12": "Financial crisis trough: 87.0",
            "2020-04": "COVID trough: 86.9",
            "2019-12": "Pre-COVID: 103.7",
        },
    },
    "eu_natural_gas": {
        "name": "EU Natural Gas Price",
        "fred_id": "PNGASEUUSDM",
        "unit": "$/MMBtu",
        "category": "Economic Stress",
        "description": "European natural gas price. When high, fertilizer & chemical plants shut down.",
        "thresholds": {"green_max": 10, "yellow_max": 20, "direction": "up_is_bad"},
        "history_notes": {
            "2022-08": "Ukraine/Russia crisis peak: ~$70/MMBtu",
            "2019-12": "Pre-COVID normal: ~$5/MMBtu",
        },
    },
    "capacity_utilization": {
        "name": "Industrial Capacity Utilization",
        "fred_id": "TCU",
        "unit": "%",
        "category": "Economic Stress",
        "description": "Percent of industrial capacity in use. Drops when plants shut down.",
        "thresholds": {"green_min": 77, "yellow_min": 73, "direction": "down_is_bad"},
        "history_notes": {
            "2009-06": "Financial crisis low: 66.7%",
            "2020-04": "COVID low: 64.2%",
            "2019-12": "Pre-COVID normal: 77.0%",
        },
    },
    "hy_credit_spread": {
        "name": "High-Yield Credit Spread",
        "fred_id": "BAMLH0A0HYM2",
        "unit": "basis points",
        "category": "Financial Contagion",
        "description": "Extra interest risky companies pay to borrow. Widens when lenders get scared.",
        "thresholds": {"green_max": 400, "yellow_max": 600, "direction": "up_is_bad"},
        "display_multiplier": 100,  # FRED gives percent, we show basis points
        "history_notes": {
            "2008-12": "Financial crisis: 2,100 bps",
            "2020-03": "COVID panic: 1,100 bps",
            "2022-07": "Ukraine/inflation fears: 600 bps",
        },
    },
    "jobless_claims": {
        "name": "Initial Jobless Claims",
        "fred_id": "ICSA",
        "unit": "thousands",
        "category": "Financial Contagion",
        "description": "Weekly new unemployment filings. Spikes when companies start laying off.",
        "thresholds": {"green_max": 250, "yellow_max": 350, "direction": "up_is_bad"},
        "display_divisor": 1000,  # FRED gives raw number, we show thousands
        "history_notes": {
            "2009-03": "Financial crisis peak: 665K",
            "2020-03": "COVID peak: 6,867K",
            "2019-12": "Pre-COVID normal: ~220K",
        },
    },
    "inflation_expectations": {
        "name": "Consumer Inflation Expectations",
        "fred_id": "MICH",
        "unit": "%",
        "category": "Financial Contagion",
        "description": "University of Michigan survey: what consumers expect inflation to be next year.",
        "thresholds": {"green_max": 3.0, "yellow_max": 4.5, "direction": "up_is_bad"},
        "history_notes": {
            "2008-06": "Oil shock fears: 5.1%",
            "2022-04": "Post-Ukraine: 5.4%",
            "2019-12": "Pre-COVID normal: 2.3%",
        },
    },
    "bizd_etf": {
        "name": "BDC Income ETF (BIZD)",
        "source": "yfinance",
        "ticker": "BIZD",
        "unit": "$/share",
        "category": "Private Credit",
        "description": "ETF tracking ~25 publicly traded BDCs that make private loans to mid-market companies.",
        "thresholds": {"green_min": 13.50, "yellow_min": 11.00, "direction": "down_is_bad"},
        "history_notes": {
            "2020-03": "COVID crash: fell ~45% in 3 weeks",
            "2022-01": "Post-COVID peak: ~$17.50",
            "2019-12": "Pre-COVID normal: ~$15.00",
        },
    },
    "arcc": {
        "name": "Ares Capital (ARCC)",
        "source": "yfinance",
        "ticker": "ARCC",
        "unit": "$/share",
        "category": "Private Credit",
        "description": "Largest publicly traded BDC ($25B+ portfolio). Named in recent private credit redemption gate reports.",
        "thresholds": {"green_min": 18.50, "yellow_min": 15.00, "direction": "down_is_bad"},
        "history_notes": {
            "2008-12": "Financial crisis: fell from $17 to $3",
            "2020-03": "COVID crash: fell ~50% to $8.50",
            "2019-12": "Pre-COVID normal: ~$19",
        },
    },
    "main_street": {
        "name": "Main Street Capital (MAIN)",
        "source": "yfinance",
        "ticker": "MAIN",
        "unit": "$/share",
        "category": "Private Credit",
        "description": "High-quality BDC bellwether. If this drops significantly, broad private credit distress is likely.",
        "thresholds": {"green_min": 55.00, "yellow_min": 45.00, "direction": "down_is_bad"},
        "history_notes": {
            "2020-03": "COVID crash: fell ~50% despite strong portfolio",
            "2022-01": "Post-COVID peak: ~$48",
            "2019-12": "Pre-COVID normal: ~$42",
        },
    },
}

# Historical events for chart annotations
HISTORICAL_EVENTS = [
    {"date": "2008-09-15", "label": "Lehman Brothers collapse"},
    {"date": "2020-03-11", "label": "WHO declares COVID pandemic"},
    {"date": "2022-02-24", "label": "Russia invades Ukraine"},
    {"date": "2025-06-01", "label": "Strait of Hormuz crisis begins"},
]

# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

def get_cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.json")


def read_cache(key):
    path = get_cache_path(key)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    if time.time() - data.get("timestamp", 0) > CACHE_MAX_AGE:
        return None
    return data.get("payload")


def write_cache(key, payload):
    path = get_cache_path(key)
    with open(path, "w") as f:
        json.dump({"timestamp": time.time(), "payload": payload}, f)


def fetch_fred_series(series_id, years=5):
    """Fetch a FRED series, returning list of {date, value} dicts."""
    cached = read_cache(f"fred_{series_id}")
    if cached:
        return cached

    start = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    observations = resp.json().get("observations", [])

    data = []
    for obs in observations:
        if obs["value"] != ".":
            data.append({"date": obs["date"], "value": float(obs["value"])})

    write_cache(f"fred_{series_id}", data)
    return data


def most_recent_business_day():
    """Return the most recent completed business day as YYYY-MM-DD.
    Uses yesterday to be conservative (avoids fetching before market close)."""
    target = datetime.now() - timedelta(days=1)
    while target.weekday() >= 5:  # Saturday=5, Sunday=6
        target -= timedelta(days=1)
    return target.strftime("%Y-%m-%d")


def fill_brent_gaps(fred_data):
    """Append recent Yahoo Finance data if FRED is lagging behind.
    Yahoo days are marked with estimated=True and will be replaced
    by FRED data on the next refresh once FRED catches up."""
    if not fred_data:
        return fred_data

    latest_fred_date = fred_data[-1]["date"]
    target_date = most_recent_business_day()

    if latest_fred_date >= target_date:
        print("Brent FRED data is current, no gap-fill needed")
        return fred_data

    try:
        ticker = yf.Ticker("BZ=F")
        yahoo_data = ticker.history(period="5d")

        if yahoo_data.empty:
            print("Yahoo Finance returned no data for BZ=F, skipping gap-fill")
            return fred_data

        filled_count = 0
        for idx, row in yahoo_data.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            if date_str > latest_fred_date:
                fred_data.append({
                    "date": date_str,
                    "value": round(row["Close"], 2),
                    "estimated": True,
                })
                filled_count += 1

        if filled_count:
            print(f"Filled {filled_count} days of Brent data from Yahoo Finance (BZ=F)")
        else:
            print("No newer Yahoo data found beyond FRED's latest date")

    except Exception as e:
        print(f"Yahoo gap-fill failed, using FRED data only: {e}")

    return fred_data


def fetch_yahoo_ticker(symbol, period="5y"):
    """Fetch historical closing prices for a Yahoo Finance ticker, with caching."""
    cache_key = f"yahoo_{symbol}"
    cached = read_cache(cache_key)
    if cached:
        return cached
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist.empty:
            print(f"Yahoo Finance returned no data for {symbol}")
            return None
        import math
        data = [
            {"date": idx.strftime("%Y-%m-%d"), "value": round(row["Close"], 2)}
            for idx, row in hist.iterrows()
            if not math.isnan(row["Close"])
        ]
        write_cache(cache_key, data)
        return data
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FUTURES_MONTH_CODES = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"]


def ticker_to_label(ticker):
    """Convert a ticker like BZK26.NYM to 'May 2026'."""
    if not ticker or ticker == "BZ=F":
        return None
    code = ticker[2]
    year_suffix = ticker[3:5]
    idx = FUTURES_MONTH_CODES.index(code)
    return f"{MONTH_NAMES[idx]} 20{year_suffix}"


def fetch_calendar_spread():
    """Fetch Brent M1-M2 calendar spread from Yahoo Finance."""
    cached = read_cache("calendar_spread")
    if cached:
        return cached

    now = datetime.now()

    # Try consecutive pairs starting from current month + 1, stepping forward
    # until we find two contracts that both have data (handles expiry roll)
    def make_ticker(month_offset):
        """Build a BZ ticker for N months from now."""
        m = (now.month - 1 + month_offset) % 12  # 0-indexed month
        y = now.year + (now.month - 1 + month_offset) // 12
        return f"BZ{FUTURES_MONTH_CODES[m]}{str(y)[-2:]}.NYM"

    try:
        fm_data = None
        sm_data = None
        fm_ticker = None
        sm_ticker = None

        # Try offsets: +1/+2, then +2/+3 (in case nearest month expired)
        for start_offset in [1, 2, 3]:
            t1 = make_ticker(start_offset)
            t2 = make_ticker(start_offset + 1)
            d1 = yf.Ticker(t1).history(period="1mo")
            d2 = yf.Ticker(t2).history(period="1mo")
            if not d1.empty and not d2.empty:
                fm_data, sm_data = d1, d2
                fm_ticker, sm_ticker = t1, t2
                break

        # Fallback: use BZ=F (continuous front month) and the next available contract
        if fm_data is None or sm_data is None:
            fm_data = yf.Ticker("BZ=F").history(period="6mo")
            # Find the first specific contract with data, starting +2 months out
            for offset in [2, 3, 4]:
                t = make_ticker(offset)
                d = yf.Ticker(t).history(period="6mo")
                if not d.empty:
                    sm_data = d
                    sm_ticker = t
                    break

        if fm_data is None or fm_data.empty or sm_data is None or sm_data.empty:
            return None

        print(f"Calendar spread: front={fm_ticker or 'BZ=F'}, second={sm_ticker}")

        # Align dates and compute spread
        fm_df = fm_data[["Close"]].rename(columns={"Close": "front"})
        sm_df = sm_data[["Close"]].rename(columns={"Close": "second"})

        fm_df.index = fm_df.index.strftime("%Y-%m-%d")
        sm_df.index = sm_df.index.strftime("%Y-%m-%d")

        merged = fm_df.join(sm_df, how="inner")
        merged["spread"] = merged["front"] - merged["second"]

        # Build human-readable contract label
        fm_label = ticker_to_label(fm_ticker)
        sm_label = ticker_to_label(sm_ticker)
        if fm_label and sm_label:
            fm_parts = fm_label.split()
            sm_parts = sm_label.split()
            if fm_parts[1] == sm_parts[1]:
                contracts = f"{fm_parts[0]} vs {sm_parts[0]} {fm_parts[1]}"
            else:
                contracts = f"{fm_label} vs {sm_label}"
        else:
            contracts = None

        data = []
        for date_str, row in merged.iterrows():
            data.append({"date": date_str, "value": round(row["spread"], 2)})

        result = {"data": data, "contracts": contracts}
        write_cache("calendar_spread", result)
        return result

    except Exception as e:
        print(f"Error fetching calendar spread: {e}")
        return None


def compute_crack_spread(brent_data, gasoline_data, heating_oil_data):
    """Compute 3-2-1 crack spread from component series."""
    # Index by date
    brent = {d["date"]: d["value"] for d in brent_data}
    gas = {d["date"]: d["value"] for d in gasoline_data}
    ho = {d["date"]: d["value"] for d in heating_oil_data}

    common_dates = sorted(set(brent.keys()) & set(gas.keys()) & set(ho.keys()))
    data = []
    for date in common_dates:
        # 3-2-1 crack spread: (2*gasoline_bbl + 1*heating_oil_bbl - 3*crude) / 3
        # Gasoline and heating oil are $/gallon, multiply by 42 for $/barrel
        spread = (2 * gas[date] * 42 + 1 * ho[date] * 42 - 3 * brent[date]) / 3
        data.append({"date": date, "value": round(spread, 2)})

    return data


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("docs", "index.html")


@app.route("/api/data")
def get_data():
    """Fetch all metrics and return dashboard payload."""
    results = {}

    try:
        # Fetch all FRED series
        brent = fetch_fred_series("DCOILBRENTEU")
        brent = fill_brent_gaps(brent)
        gasoline = fetch_fred_series("DGASNYH")
        heating_oil = fetch_fred_series("DHOILNYH")
        indpro = fetch_fred_series("INDPRO")
        eu_gas = fetch_fred_series("PNGASEUUSDM")
        tcu = fetch_fred_series("TCU")
        hy_spread = fetch_fred_series("BAMLH0A0HYM2")
        icsa = fetch_fred_series("ICSA")
        mich = fetch_fred_series("MICH")

        # Compute derived metrics
        crack = compute_crack_spread(brent, gasoline, heating_oil)
        cal_spread_result = fetch_calendar_spread()
        cal_spread_data = cal_spread_result["data"] if cal_spread_result else None
        cal_spread_contracts = cal_spread_result["contracts"] if cal_spread_result else None

        # Fetch Private Credit tickers
        bizd = fetch_yahoo_ticker("BIZD")
        arcc = fetch_yahoo_ticker("ARCC")
        main_street = fetch_yahoo_ticker("MAIN")

        # Package each metric
        def package_metric(key, data):
            if not data:
                return None
            meta = METRICS[key]
            # Apply display transforms
            display_data = data
            if "display_multiplier" in meta:
                m = meta["display_multiplier"]
                display_data = [
                    {**{"date": d["date"], "value": round(d["value"] * m, 2)}, **({"estimated": True} if d.get("estimated") else {})}
                    for d in data
                ]
            elif "display_divisor" in meta:
                d_val = meta["display_divisor"]
                display_data = [
                    {**{"date": d["date"], "value": round(d["value"] / d_val, 1)}, **({"estimated": True} if d.get("estimated") else {})}
                    for d in data
                ]

            current = display_data[-1]["value"] if display_data else None
            is_estimated = display_data[-1].get("estimated", False) if display_data else False
            # Recent trend: last 90 days for daily, last 12 points for monthly
            recent = display_data[-90:] if len(display_data) > 90 else display_data

            return {
                "name": meta["name"],
                "category": meta["category"],
                "description": meta["description"],
                "unit": meta["unit"],
                "current_value": current,
                "current_date": display_data[-1]["date"] if display_data else None,
                "current_estimated": is_estimated,
                "recent": recent,
                "full_history": display_data,
                "thresholds": meta["thresholds"],
                "history_notes": meta.get("history_notes", {}),
            }

        results = {
            "brent_crude": package_metric("brent_crude", brent),
            "crack_spread": package_metric("crack_spread", crack),
            "calendar_spread": (lambda p: ({**p, "contracts": cal_spread_contracts} if p and cal_spread_contracts else p))(package_metric("calendar_spread", cal_spread_data)),
            "industrial_production": package_metric("industrial_production", indpro),
            "eu_natural_gas": package_metric("eu_natural_gas", eu_gas),
            "capacity_utilization": package_metric("capacity_utilization", tcu),
            "hy_credit_spread": package_metric("hy_credit_spread", hy_spread),
            "jobless_claims": package_metric("jobless_claims", icsa),
            "inflation_expectations": package_metric("inflation_expectations", mich),
            "bizd_etf": package_metric("bizd_etf", bizd),
            "arcc": package_metric("arcc", arcc),
            "main_street": package_metric("main_street", main_street),
        }

        # Overall assessment
        zone_counts = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
        for key, metric_data in results.items():
            if metric_data is None:
                zone_counts["unknown"] += 1
                continue
            zone = compute_zone(metric_data["current_value"], metric_data["thresholds"])
            metric_data["zone"] = zone
            zone_counts[zone] += 1

        if zone_counts["red"] >= 3:
            overall = "critical"
            overall_label = "Critical — Multiple indicators in alarm territory"
        elif zone_counts["red"] >= 1 or zone_counts["yellow"] >= 4:
            overall = "elevated"
            overall_label = "Elevated — Some indicators showing significant stress"
        elif zone_counts["yellow"] >= 2:
            overall = "caution"
            overall_label = "Caution — Emerging stress in some areas"
        else:
            overall = "stable"
            overall_label = "Stable — Indicators within normal ranges"

        return jsonify({
            "metrics": results,
            "overall": {"level": overall, "label": overall_label, "zones": zone_counts},
            "historical_events": HISTORICAL_EVENTS,
            "last_updated": datetime.now().isoformat(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def compute_zone(value, thresholds):
    if value is None:
        return "unknown"
    direction = thresholds.get("direction", "up_is_bad")
    if direction == "up_is_bad":
        if value <= thresholds["green_max"]:
            return "green"
        elif value <= thresholds["yellow_max"]:
            return "yellow"
        else:
            return "red"
    else:  # down_is_bad
        if value >= thresholds["green_min"]:
            return "green"
        elif value >= thresholds["yellow_min"]:
            return "yellow"
        else:
            return "red"


@app.route("/api/refresh", methods=["POST"])
def refresh_data():
    """Clear cache and force re-fetch."""
    for f in os.listdir(CACHE_DIR):
        os.remove(os.path.join(CACHE_DIR, f))
    return jsonify({"status": "cache_cleared"})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
