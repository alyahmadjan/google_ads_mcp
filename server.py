r"""
server.py — MCP Server for Google Ads
--------------------------------------
Entry point for Claude Desktop. Registers MCP tools that Claude can call.
All Google Ads API logic lives in ads.py; this file is intentionally thin.

Run (with venv active):
    python server.py

Or call the venv Python directly (Windows):
    .venv\Scripts\python.exe server.py
"""

import json
from functools import partial
from typing import Optional

import anyio
from mcp.server.fastmcp import FastMCP
from ads import (
    PRESET_DATE_RANGES,
    VALID_GRANULARITIES,
    get_campaign_summary,
    resolve_date_range,
)

# ── MCP server instance ───────────────────────────────────────────────────────
mcp = FastMCP("Google Ads Analyst")


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1 — Hello (sanity check, zero external dependencies)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def hello(name: str = "World") -> str:
    """
    Verify the MCP server is running. No Google Ads credentials required.

    Args:
        name: Name to include in the greeting.

    Returns:
        A greeting string confirming the server is up.
    """
    presets = ", ".join(sorted(PRESET_DATE_RANGES))
    return (
        f"Hello, {name}! The Google Ads MCP server is running. 🎉\n\n"
        f"Available date presets: {presets}\n"
        f"Available granularities: {', '.join(sorted(VALID_GRANULARITIES))}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 2 — Campaign Summary (flexible date range + granularity)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_campaigns(
    customer_id: str,
    date_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "daily",
    compare_previous: bool = False,
) -> str:
    """
    Fetch Google Ads campaign performance for a flexible date range.

    Returns a JSON payload with:
      - meta:      request parameters + row count
      - summary:   account-level rolled-up totals
      - campaigns: per-campaign totals, optional period comparison,
                   and a time-series broken down by granularity

    DATE RANGE — choose one approach:

      Preset (date_range):
        last_7_days, last_30_days, last_6_months, last_12_months,
        today, yesterday, this_month, last_month

      Custom (start_date + end_date):
        Provide both as "YYYY-MM-DD". Omit date_range when using custom dates.

    GRANULARITY:
        daily   — one time-series row per calendar day   (best for ≤ 90 days)
        weekly  — one row per week                       (best for ≤ 6 months)
        monthly — one row per calendar month             (best for ≥ 3 months)

    COMPARISON:
        compare_previous=True adds previous_period metrics and a delta (%)
        for each campaign so Claude can do period-over-period commentary.

    Args:
        customer_id:      Google Ads Customer ID without dashes ("1234567890").
        date_range:       Preset name. Ignored when start_date + end_date given.
        start_date:       Custom range start "YYYY-MM-DD".
        end_date:         Custom range end   "YYYY-MM-DD".
        granularity:      "daily" | "weekly" | "monthly"  (default: "daily")
        compare_previous: Include prior equivalent period + delta %? (default: False)

    Returns:
        Compact JSON string ready for Claude to parse and summarise.
    """
    # If the caller supplied ANY custom date, take the custom path so a lone
    # start_date (or lone end_date) raises instead of being silently ignored
    # in favour of the default preset.
    use_custom = start_date is not None or end_date is not None
    try:
        result = await anyio.to_thread.run_sync(
            partial(
                get_campaign_summary,
                customer_id=customer_id,
                date_range=None if use_custom else date_range,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                compare_previous=compare_previous,
            )
        )
        return json.dumps(result, indent=2)

    except ValueError as exc:
        # Bad inputs — Claude should relay this clearly to the user.
        return json.dumps({
            "error": True,
            "error_type": "invalid_input",
            "message": str(exc),
            "valid_date_ranges": sorted(PRESET_DATE_RANGES),
            "valid_granularities": sorted(VALID_GRANULARITIES),
        }, indent=2)

    except RuntimeError as exc:
        # Google Ads API error — usually auth or account issues.
        return json.dumps({
            "error": True,
            "error_type": "api_error",
            "message": str(exc),
            "hint": (
                "Check that customer_id has no dashes, your google-ads.yaml "
                "credentials are valid, and the account has data for the "
                "requested period."
            ),
        }, indent=2)

    except Exception as exc:
        return json.dumps({
            "error": True,
            "error_type": "unexpected",
            "message": str(exc),
        }, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 3 — Date Range Preview (explain what dates a preset resolves to)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def preview_date_range(
    date_range: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Show what calendar dates a preset or custom range resolves to,
    without making any Google Ads API call. Useful for confirming the
    right range before running a report.

    Args:
        date_range:  Preset name (e.g. "last_6_months").
        start_date:  Custom range start "YYYY-MM-DD".
        end_date:    Custom range end   "YYYY-MM-DD".

    Returns:
        JSON with resolved start, end, and day count.
    """
    try:
        s, e = resolve_date_range(date_range, start_date, end_date)
        from datetime import datetime
        delta = (
            datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(s, "%Y-%m-%d")
        ).days + 1
        return json.dumps({
            "resolved_start": s,
            "resolved_end": e,
            "days": delta,
            "input": {
                "date_range": date_range,
                "start_date": start_date,
                "end_date": end_date,
            },
        }, indent=2)
    except ValueError as exc:
        return json.dumps({
            "error": True,
            "message": str(exc),
            "valid_date_ranges": sorted(PRESET_DATE_RANGES),
        }, indent=2)



# ─────────────────────────────────────────────────────────────────────────────
# TOOL 4 — Daily Metrics  (convenience wrapper — Claude should prefer this
#           when the user asks for "daily metrics / daily data / daily report")
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_daily_metrics(
    customer_id: str,
    date_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    compare_previous: bool = False,
) -> str:
    """
    Fetch Google Ads performance broken down by DAY — one row per calendar
    day per campaign.  Use this whenever the user asks for daily metrics,
    daily conversions, day-by-day data, or a daily report.

    This is equivalent to get_campaigns with granularity="daily" but makes
    the intent explicit so Claude always fetches day-level data.

    DATE RANGE — choose one approach:
      Preset (date_range):
        last_7_days, last_30_days, last_6_months, last_12_months,
        today, yesterday, this_month, last_month
      Custom (start_date + end_date):
        Provide both as "YYYY-MM-DD". Omit date_range when using custom dates.

    Args:
        customer_id:      Google Ads Customer ID without dashes.
        date_range:       Preset name (default: last_30_days).
        start_date:       Custom range start "YYYY-MM-DD".
        end_date:         Custom range end   "YYYY-MM-DD".
        compare_previous: Include prior equivalent period + delta %?

    Returns:
        JSON with meta, account summary, and per-campaign daily timeseries.
    """
    use_custom = start_date is not None or end_date is not None
    try:
        result = await anyio.to_thread.run_sync(
            partial(
                get_campaign_summary,
                customer_id=customer_id,
                date_range=None if use_custom else date_range,
                start_date=start_date,
                end_date=end_date,
                granularity="daily",
                compare_previous=compare_previous,
            )
        )
        return json.dumps(result, indent=2)

    except ValueError as exc:
        return json.dumps({
            "error": True,
            "error_type": "invalid_input",
            "message": str(exc),
            "valid_date_ranges": sorted(PRESET_DATE_RANGES),
        }, indent=2)

    except RuntimeError as exc:
        return json.dumps({
            "error": True,
            "error_type": "api_error",
            "message": str(exc),
            "hint": (
                "Check that customer_id has no dashes, your google-ads.yaml "
                "credentials are valid, and the account has data for the "
                "requested period."
            ),
        }, indent=2)

    except Exception as exc:
        return json.dumps({
            "error": True,
            "error_type": "unexpected",
            "message": str(exc),
        }, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # stdio transport is required for Claude Desktop.
    # Claude Desktop launches this script as a subprocess and communicates
    # over stdin / stdout via JSON-RPC. No output = server started correctly.
    mcp.run(transport="stdio")
