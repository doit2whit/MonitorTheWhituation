"""
Fetch all dashboard metrics from FRED and Yahoo Finance,
compute derived metrics, and save as static/data.json.

Run locally or via GitHub Actions on a schedule.
"""

import os
import json
from datetime import datetime, timedelta
import requests
import yfinance as yf

FRED_API_KEY = os.environ.get("FRED_API_KEY")

# ---------------------------------------------------------------------------
# Metric definitions (mirrors server.py)
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
        "thresholds": {"green_max": 25, "yellow_max": 40, "direction": "up_is_bad"},
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
        "display_multiplier": 100,
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
        "display_divisor": 1000,
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
}

HISTORICAL_EVENTS = [
    {"date": "2008-09-15", "label": "Lehman Brothers collapse"},
    {"date": "2020-03-11", "label": "WHO declares COVID pandemic"},
    {"date": "2022-02-24", "label": "Russia invades Ukraine"},
    {"date": "2025-06-01", "label": "Strait of Hormuz crisis begins"},
]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_fred_series(series_id, years=5):
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
    return [
        {"date": obs["date"], "value": float(obs["value"])}
        for obs in observations
        if obs["value"] != "."
    ]


def fetch_calendar_spread():
    month_codes = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"]
    now = datetime.now()

    def make_ticker(month_offset):
        m = (now.month - 1 + month_offset) % 12
        y = now.year + (now.month - 1 + month_offset) // 12
        return f"BZ{month_codes[m]}{str(y)[-2:]}.NYM"

    try:
        fm_data = None
        sm_data = None
        fm_ticker = None
        sm_ticker = None

        for start_offset in [1, 2, 3]:
            t1 = make_ticker(start_offset)
            t2 = make_ticker(start_offset + 1)
            d1 = yf.Ticker(t1).history(period="1mo")
            d2 = yf.Ticker(t2).history(period="1mo")
            if not d1.empty and not d2.empty:
                fm_data, sm_data = d1, d2
                fm_ticker, sm_ticker = t1, t2
                break

        if fm_data is None or sm_data is None:
            fm_data = yf.Ticker("BZ=F").history(period="6mo")
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

        fm_df = fm_data[["Close"]].rename(columns={"Close": "front"})
        sm_df = sm_data[["Close"]].rename(columns={"Close": "second"})
        fm_df.index = fm_df.index.strftime("%Y-%m-%d")
        sm_df.index = sm_df.index.strftime("%Y-%m-%d")

        merged = fm_df.join(sm_df, how="inner")
        merged["spread"] = merged["front"] - merged["second"]

        return [
            {"date": date_str, "value": round(row["spread"], 2)}
            for date_str, row in merged.iterrows()
        ]
    except Exception as e:
        print(f"Error fetching calendar spread: {e}")
        return None


def compute_crack_spread(brent_data, gasoline_data, heating_oil_data):
    brent = {d["date"]: d["value"] for d in brent_data}
    gas = {d["date"]: d["value"] for d in gasoline_data}
    ho = {d["date"]: d["value"] for d in heating_oil_data}

    common_dates = sorted(set(brent.keys()) & set(gas.keys()) & set(ho.keys()))
    return [
        {
            "date": date,
            "value": round(
                (2 * gas[date] * 42 + 1 * ho[date] * 42 - 3 * brent[date]) / 3, 2
            ),
        }
        for date in common_dates
    ]


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
    else:
        if value >= thresholds["green_min"]:
            return "green"
        elif value >= thresholds["yellow_min"]:
            return "yellow"
        else:
            return "red"


def package_metric(key, data):
    if not data:
        return None
    meta = METRICS[key]

    display_data = data
    if "display_multiplier" in meta:
        m = meta["display_multiplier"]
        display_data = [{"date": d["date"], "value": round(d["value"] * m, 2)} for d in data]
    elif "display_divisor" in meta:
        dv = meta["display_divisor"]
        display_data = [{"date": d["date"], "value": round(d["value"] / dv, 1)} for d in data]

    current = display_data[-1]["value"] if display_data else None
    recent = display_data[-90:] if len(display_data) > 90 else display_data

    return {
        "name": meta["name"],
        "category": meta["category"],
        "description": meta["description"],
        "unit": meta["unit"],
        "current_value": current,
        "current_date": display_data[-1]["date"] if display_data else None,
        "recent": recent,
        "full_history": display_data,
        "thresholds": meta["thresholds"],
        "history_notes": meta.get("history_notes", {}),
    }


def main():
    print("Fetching FRED series...")
    brent = fetch_fred_series("DCOILBRENTEU")
    gasoline = fetch_fred_series("DGASNYH")
    heating_oil = fetch_fred_series("DHOILNYH")
    indpro = fetch_fred_series("INDPRO")
    eu_gas = fetch_fred_series("PNGASEUUSDM")
    tcu = fetch_fred_series("TCU")
    hy_spread = fetch_fred_series("BAMLH0A0HYM2")
    icsa = fetch_fred_series("ICSA")
    mich = fetch_fred_series("MICH")

    print("Computing derived metrics...")
    crack = compute_crack_spread(brent, gasoline, heating_oil)

    print("Fetching calendar spread from Yahoo Finance...")
    cal_spread = fetch_calendar_spread()

    print("Packaging results...")
    results = {
        "brent_crude": package_metric("brent_crude", brent),
        "crack_spread": package_metric("crack_spread", crack),
        "calendar_spread": package_metric("calendar_spread", cal_spread),
        "industrial_production": package_metric("industrial_production", indpro),
        "eu_natural_gas": package_metric("eu_natural_gas", eu_gas),
        "capacity_utilization": package_metric("capacity_utilization", tcu),
        "hy_credit_spread": package_metric("hy_credit_spread", hy_spread),
        "jobless_claims": package_metric("jobless_claims", icsa),
        "inflation_expectations": package_metric("inflation_expectations", mich),
    }

    # Compute zones and overall assessment
    zone_counts = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
    for key, metric_data in results.items():
        if metric_data is None:
            zone_counts["unknown"] += 1
            continue
        zone = compute_zone(metric_data["current_value"], metric_data["thresholds"])
        metric_data["zone"] = zone
        zone_counts[zone] += 1

    if zone_counts["red"] >= 3:
        overall = {"level": "critical", "label": "Critical — Multiple indicators in alarm territory"}
    elif zone_counts["red"] >= 1 or zone_counts["yellow"] >= 4:
        overall = {"level": "elevated", "label": "Elevated — Some indicators showing significant stress"}
    elif zone_counts["yellow"] >= 2:
        overall = {"level": "caution", "label": "Caution — Emerging stress in some areas"}
    else:
        overall = {"level": "stable", "label": "Stable — Indicators within normal ranges"}

    overall["zones"] = zone_counts

    payload = {
        "metrics": results,
        "overall": overall,
        "historical_events": HISTORICAL_EVENTS,
        "last_updated": datetime.now().isoformat(),
    }

    out_path = os.path.join(os.path.dirname(__file__), "static", "data.json")
    with open(out_path, "w") as f:
        json.dump(payload, f)

    print(f"Wrote {out_path} ({os.path.getsize(out_path)} bytes)")
    print(f"Overall: {overall['label']}")
    for key, m in results.items():
        if m:
            print(f"  {m['name']:35s} | {m['current_value']} {m['unit']} | {m.get('zone', '?')}")


if __name__ == "__main__":
    main()
