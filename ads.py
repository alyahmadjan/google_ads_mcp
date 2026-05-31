"""
ads.py — Google Ads API Functions
-----------------------------------
All Google Ads API interactions live here. server.py imports from this
module, keeping the MCP layer and the data layer cleanly separated.

Key design choices:
  - resolve_date_range()  converts any preset string OR custom dates into
    a (start, end) tuple.  Every tool calls this one helper — no ad-hoc
    date logic scattered around.
  - All filtering happens in GAQL (server-side).  We never fetch more
    data than the user asked for.
  - Granularity (daily / weekly / monthly) adds segments.date /
    segments.week / segments.month to the SELECT and GROUP BY implicitly
    handled by the API.
  - Row limits guard against huge accounts blowing up the response.
  - A compare_previous flag fetches the prior equivalent period and
    appends delta metrics so Claude can do period-over-period commentary.

Authentication:
    Reads credentials from google-ads.yaml, discovered from:
      1. GOOGLE_ADS_CONFIGURATION_FILE_PATH env variable (set in .env)
      2. ~/google-ads.yaml
      3. ~/.config/google-ads.yaml
"""

import os
import calendar
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

# Accepted preset names — validated before any API call is made.
PRESET_DATE_RANGES = {
    "today",
    "yesterday",
    "this_month",
    "last_month",
    "last_7_days",
    "last_30_days",
    "last_6_months",
    "last_12_months",
}

VALID_GRANULARITIES = {"daily", "weekly", "monthly"}

# Maximum rows returned per query.  Keeps responses LLM-friendly.
# Google Ads API pages automatically; we stop after this many rows.
MAX_ROWS = 500

# Date format used throughout GAQL and all returned payloads.
DATE_FMT = "%Y-%m-%d"


# ─────────────────────────────────────────────────────────────────────────────
# Auth helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_client() -> GoogleAdsClient:
    """
    Build and return a GoogleAdsClient using google-ads.yaml.

    Discovery order:
      1. Path in GOOGLE_ADS_CONFIGURATION_FILE_PATH env var (.env)
      2. ~/google-ads.yaml
      3. ~/.config/google-ads.yaml
    """
    config_path = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE_PATH")
    if config_path:
        return GoogleAdsClient.load_from_storage(path=config_path)
    return GoogleAdsClient.load_from_storage()


# ─────────────────────────────────────────────────────────────────────────────
# Date-range resolver  (the single source of truth for all date logic)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_date_range(
    date_range: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[str, str]:
    """
    Convert a preset name OR explicit start/end dates into a (start, end)
    tuple of 'YYYY-MM-DD' strings.

    Priority:
      1. If date_range is given, it must be one of PRESET_DATE_RANGES.
         start_date / end_date are ignored.
      2. If start_date and end_date are both given, they are validated and used.
      3. If nothing is given, defaults to last_30_days.

    Args:
        date_range:  Preset name, e.g. "last_7_days".
        start_date:  Custom start, e.g. "2024-01-01".
        end_date:    Custom end,   e.g. "2024-03-31".

    Returns:
        (start_str, end_str) both in YYYY-MM-DD format.

    Raises:
        ValueError: On unrecognised preset, bad date format, or start > end.
    """
    today = date.today()

    # ── Preset path ───────────────────────────────────────────────────────────
    if date_range is not None:
        key = date_range.lower().strip()
        if key not in PRESET_DATE_RANGES:
            valid = ", ".join(sorted(PRESET_DATE_RANGES))
            raise ValueError(
                f"Unknown date_range '{date_range}'. "
                f"Valid presets are: {valid}"
            )

        if key == "today":
            return str(today), str(today)

        if key == "yesterday":
            yest = today - timedelta(days=1)
            return str(yest), str(yest)

        if key == "last_7_days":
            # 7 days inclusive of today → today and the 6 days before it
            return str(today - timedelta(days=6)), str(today)

        if key == "last_30_days":
            # 30 days inclusive of today → today and the 29 days before it
            return str(today - timedelta(days=29)), str(today)

        if key == "last_6_months":
            # Six calendar months back, first day of that month → today
            month = today.month - 6
            year = today.year
            if month <= 0:
                month += 12
                year -= 1
            start = date(year, month, 1)
            return str(start), str(today)

        if key == "last_12_months":
            month = today.month - 12
            year = today.year
            if month <= 0:
                month += 12
                year -= 1
            start = date(year, month, 1)
            return str(start), str(today)

        if key == "this_month":
            start = today.replace(day=1)
            return str(start), str(today)

        if key == "last_month":
            first_of_this_month = today.replace(day=1)
            last_of_prev = first_of_this_month - timedelta(days=1)
            first_of_prev = last_of_prev.replace(day=1)
            return str(first_of_prev), str(last_of_prev)

    # ── Custom path ───────────────────────────────────────────────────────────
    if start_date and end_date:
        try:
            s = datetime.strptime(start_date.strip(), DATE_FMT).date()
        except ValueError:
            raise ValueError(
                f"start_date '{start_date}' is not a valid date. "
                "Use YYYY-MM-DD format."
            )
        try:
            e = datetime.strptime(end_date.strip(), DATE_FMT).date()
        except ValueError:
            raise ValueError(
                f"end_date '{end_date}' is not a valid date. "
                "Use YYYY-MM-DD format."
            )
        if s > e:
            raise ValueError(
                f"start_date ({s}) must be before or equal to end_date ({e})."
            )
        if e > today:
            raise ValueError(
                f"end_date ({e}) is in the future. "
                "Google Ads only has data up to yesterday."
            )
        return str(s), str(e)

    if start_date and not end_date:
        raise ValueError("start_date was provided but end_date is missing.")
    if end_date and not start_date:
        raise ValueError("end_date was provided but start_date is missing.")

    # ── Default fallback (mirrors last_30_days) ───────────────────────────────
    return str(today - timedelta(days=29)), str(today)


def _previous_period(start: str, end: str) -> tuple[str, str]:
    """
    Return the prior period of equal length immediately before (start, end).

    Example: start=2024-03-01 end=2024-03-31 (31 days)
             → prev_start=2024-01-30, prev_end=2024-02-29
    """
    s = datetime.strptime(start, DATE_FMT).date()
    e = datetime.strptime(end, DATE_FMT).date()
    span = (e - s).days + 1          # inclusive day count
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return str(prev_start), str(prev_end)


# ─────────────────────────────────────────────────────────────────────────────
# Shared metric helpers
# ─────────────────────────────────────────────────────────────────────────────

def _micros_to_dollars(micros: int) -> float:
    """Convert Google Ads micro-currency to account base currency (usually USD)."""
    return round(micros / 1_000_000, 2)


def _safe_divide(num: float, den: float, decimals: int = 4) -> float:
    """Divide safely, returning 0.0 when denominator is zero."""
    return 0.0 if den == 0 else round(num / den, decimals)


def _pct_change(current: float, previous: float) -> Optional[float]:
    """
    Return percentage change from previous to current.
    Returns None if previous is zero (avoids division-by-zero in deltas).
    """
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _build_row_metrics(metrics) -> dict:
    """Extract and derive standard metrics from a GAQL metrics object."""
    impressions = metrics.impressions
    clicks = metrics.clicks
    cost_usd = _micros_to_dollars(metrics.cost_micros)
    conversions = round(metrics.conversions, 2)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "cost_usd": cost_usd,
        "conversions": conversions,
        "ctr": _safe_divide(clicks, impressions, 4),
        "cpc_usd": _safe_divide(cost_usd, clicks, 2),
        "cost_per_conversion_usd": _safe_divide(cost_usd, conversions, 2),
    }


def _sum_metrics(rows: list[dict]) -> dict:
    """Aggregate a list of metric dicts into a single totals dict."""
    totals: dict[str, float] = {
        "impressions": 0,
        "clicks": 0,
        "cost_usd": 0.0,
        "conversions": 0.0,
    }
    for r in rows:
        totals["impressions"] += r.get("impressions", 0)
        totals["clicks"] += r.get("clicks", 0)
        totals["cost_usd"] += r.get("cost_usd", 0.0)
        totals["conversions"] += r.get("conversions", 0.0)

    totals["cost_usd"] = round(totals["cost_usd"], 2)
    totals["conversions"] = round(totals["conversions"], 2)
    totals["ctr"] = _safe_divide(totals["clicks"], totals["impressions"], 4)
    totals["cpc_usd"] = _safe_divide(totals["cost_usd"], totals["clicks"], 2)
    totals["cost_per_conversion_usd"] = _safe_divide(
        totals["cost_usd"], totals["conversions"], 2
    )
    return totals


def _granularity_segment(granularity: str) -> tuple[str, str]:
    """
    Return (gaql_field, proto_attr) for the requested granularity.

    daily   → ("segments.date",  "date")   one row per calendar day
    weekly  → ("segments.week",  "week")   one row per week (Monday start)
    monthly → ("segments.month", "month")  one row per calendar month

    gaql_field  — used in SELECT clause
    proto_attr  — used to read the value from row.segments.<proto_attr>
    """
    return {
        "daily":   ("segments.date",  "date"),
        "weekly":  ("segments.week",  "week"),
        "monthly": ("segments.month", "month"),
    }[granularity]


# ─────────────────────────────────────────────────────────────────────────────
# GAQL execution helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_query(
    customer_id: str,
    query: str,
    max_rows: int = MAX_ROWS,
) -> list:
    """
    Execute a GAQL query and return at most max_rows raw result rows.

    The Google Ads Python client paginates transparently; we break out
    once we hit max_rows so large accounts do not produce enormous payloads.

    Raises:
        GoogleAdsException: Propagated from the API with a clear message.
        RuntimeError: On unexpected failures.
    """
    client = _get_client()
    ga_service = client.get_service("GoogleAdsService")

    try:
        stream = ga_service.search_stream(customer_id=customer_id, query=query)
        rows = []
        for batch in stream:
            for row in batch.results:
                rows.append(row)
                if len(rows) >= max_rows:
                    return rows
        return rows
    except GoogleAdsException as ex:
        messages = "; ".join(e.message for e in ex.failure.errors)
        raise RuntimeError(
            f"Google Ads API error (request_id={ex.request_id}): {messages}"
        ) from ex


# ─────────────────────────────────────────────────────────────────────────────
# Public API — get_campaign_summary
# ─────────────────────────────────────────────────────────────────────────────

def get_campaign_summary(
    customer_id: str,
    date_range: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "daily",
    compare_previous: bool = False,
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """
    Fetch campaign performance for a flexible date range, with optional
    time-series breakdown and period-over-period comparison.

    Args:
        customer_id:      10-digit Google Ads customer ID (no dashes).
        date_range:       Preset name (e.g. "last_7_days"). Takes priority
                          over start_date / end_date if both are supplied.
        start_date:       Custom range start "YYYY-MM-DD".
        end_date:         Custom range end   "YYYY-MM-DD".
        granularity:      "daily" | "weekly" | "monthly"
                          Controls time-series segment in the response.
        compare_previous: If True, also query the prior equivalent period
                          and include delta metrics in each campaign row.
        max_rows:         Hard cap on API rows (default 500).

    Returns:
        {
          "meta": {
            "customer_id":   str,
            "date_range":    {"start": str, "end": str},
            "granularity":   str,
            "compare_previous": bool,
            "rows_returned": int,
            "capped_at":     int | None   # set if rows hit the limit
          },
          "summary": {           # rolled-up totals across all campaigns
            "impressions": int, "clicks": int, "cost_usd": float,
            "conversions": float, "ctr": float, "cpc_usd": float,
            "cost_per_conversion_usd": float
          },
          "campaigns": [         # one entry per campaign
            {
              "campaign_id":   str,
              "campaign_name": str,
              "status":        str,
              "totals":        { ...metrics... },
              "previous_period": { ...metrics... } | None,
              "delta": { ...pct_change per metric... } | None,
              "timeseries": [    # one entry per granularity bucket
                { "period": "YYYY-MM-DD", ...metrics... }, ...
              ]
            }, ...
          ]
        }

    Raises:
        ValueError: On invalid date_range or date format.
        RuntimeError: On Google Ads API errors.
    """
    # ── Validate inputs ───────────────────────────────────────────────────────
    granularity = granularity.lower().strip()
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(
            f"Invalid granularity '{granularity}'. "
            f"Choose from: {', '.join(sorted(VALID_GRANULARITIES))}"
        )

    s, e = resolve_date_range(date_range, start_date, end_date)
    segment_field, segment_attr = _granularity_segment(granularity)

    # ── Build current-period GAQL query ───────────────────────────────────────
    # The API returns one row per (campaign × segment bucket).
    # No LIMIT in GAQL — the Python client paginates; _run_query enforces max_rows.
    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            {segment_field},
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions
        FROM campaign
        WHERE
            segments.date BETWEEN '{s}' AND '{e}'
            AND campaign.status != 'REMOVED'
        ORDER BY segments.date ASC
    """

    raw_rows = _run_query(customer_id, query, max_rows)
    capped = len(raw_rows) >= max_rows

    # ── Aggregate rows by campaign, collecting timeseries per campaign ────────
    campaign_map: dict[str, dict] = {}   # keyed by campaign_id

    for row in raw_rows:
        cid = str(row.campaign.id)
        if cid not in campaign_map:
            campaign_map[cid] = {
                "campaign_id": cid,
                "campaign_name": row.campaign.name,
                "status": row.campaign.status.name,
                "timeseries_rows": [],  # accumulate per-period rows here
            }

        # Read the segment value using the correct proto attribute name
        period_value = getattr(row.segments, segment_attr, None)
        m = _build_row_metrics(row.metrics)
        campaign_map[cid]["timeseries_rows"].append(
            {"period": str(period_value) if period_value else s, **m}
        )

    # ── Compute per-campaign totals from timeseries rows ─────────────────────
    campaigns_out = []
    for cid, camp in campaign_map.items():
        ts_rows = camp["timeseries_rows"]
        totals = _sum_metrics(ts_rows)
        campaigns_out.append({
            "campaign_id": camp["campaign_id"],
            "campaign_name": camp["campaign_name"],
            "status": camp["status"],
            "totals": totals,
            "previous_period": None,   # populated below if compare_previous
            "delta": None,
            "timeseries": sorted(ts_rows, key=lambda r: r["period"]),
        })

    # ── Optional: compare with prior equivalent period ────────────────────────
    if compare_previous and campaigns_out:
        prev_s, prev_e = _previous_period(s, e)
        prev_query = f"""
            SELECT
                campaign.id,
                segments.date,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE
                segments.date BETWEEN '{prev_s}' AND '{prev_e}'
                AND campaign.status != 'REMOVED'
        """
        prev_raw = _run_query(customer_id, prev_query, max_rows)

        # Accumulate previous-period rows by campaign
        prev_map: dict[str, list] = {}
        for row in prev_raw:
            cid = str(row.campaign.id)
            prev_map.setdefault(cid, []).append(_build_row_metrics(row.metrics))

        # Attach previous totals + delta to each campaign entry
        for camp in campaigns_out:
            cid = camp["campaign_id"]
            if cid in prev_map:
                prev_totals = _sum_metrics(prev_map[cid])
                camp["previous_period"] = prev_totals
                camp["delta"] = {
                    k: _pct_change(camp["totals"].get(k, 0), prev_totals.get(k, 0))
                    for k in ("impressions", "clicks", "cost_usd", "conversions",
                              "ctr", "cpc_usd", "cost_per_conversion_usd")
                }

    # ── Roll up account-level summary ─────────────────────────────────────────
    all_totals = [c["totals"] for c in campaigns_out]
    account_summary = _sum_metrics(all_totals) if all_totals else {}

    meta = {
        "customer_id": customer_id,
        "date_range": {"start": s, "end": e},
        "granularity": granularity,
        "compare_previous": compare_previous,
        "rows_returned": len(raw_rows),
        "capped_at": max_rows if capped else None,
    }
    if capped:
        # Rows are ordered by date ascending, so a cap drops the MOST RECENT
        # days. Totals/summary below are therefore PARTIAL — flag it loudly so
        # the model never reports them as complete.
        meta["warning"] = (
            f"Result truncated at {max_rows} rows; the most recent days are "
            "missing and all totals are INCOMPLETE. Narrow the date range or "
            "use a coarser granularity (weekly/monthly) for full coverage."
        )

    return {
        "meta": meta,
        "summary": account_summary,
        "campaigns": campaigns_out,
    }
