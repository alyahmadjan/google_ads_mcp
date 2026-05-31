# Google Ads MCP Server for Claude Desktop

A local Python MCP server that lets Claude Desktop act as a Google Ads analyst.  
Ask Claude to fetch campaign data, summarize performance, and spot trends — all powered by the real Google Ads API.

---

## Project Structure

```
google-ads-mcp/
├── server.py                 ← MCP server & tool definitions
├── ads.py                    ← Google Ads API logic (pure Python, no MCP)
├── requirements.txt          ← Python dependencies
├── .env.example              ← Copy to .env (sets the yaml path)
├── .env                      ← Your local config (gitignored)
├── google-ads.yaml.example   ← Copy to google-ads.yaml and fill in
├── google-ads.yaml           ← Your real credentials (gitignored)
├── start_mcp.bat             ← Windows launcher (activates venv, runs server)
├── .gitignore                ← Keeps secrets & logs out of git
└── .vscode/
    └── launch.json           ← VS Code debug/run config
```

---

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `hello(name)` | Sanity check — confirms the server is running (no API call) |
| `preview_date_range(...)` | Show what dates a preset resolves to before querying |
| `get_campaigns(...)` | Campaign performance with flexible date range + granularity |
| `get_daily_metrics(...)` | Same as `get_campaigns` but always day-by-day |

> Full parameter reference for `get_campaigns` / `get_daily_metrics` is in the
> [Updated Tool Reference](#updated-tool-reference-v2) section below.

---

## Step-by-Step Setup

### 1. Clone or create the project folder

```bash
# If you downloaded this as a zip, just unzip it.
cd ~/projects          # or wherever you keep code
# The folder is already named google-ads-mcp
cd google-ads-mcp
```

### 2. Create and activate a virtual environment

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

You should see `(.venv)` in your terminal prompt once activated.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up Google Ads credentials

You need four things from Google:

| Credential | Where to get it |
|------------|----------------|
| `developer_token` | [Google Ads API Center](https://ads.google.com/aw/apicenter) → Apply for API access |
| `client_id` | [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth 2.0 Client ID (Desktop app type) |
| `client_secret` | Same OAuth 2.0 Client ID creation step above |
| `refresh_token` | Run the OAuth helper below |

**Get a refresh token:**

```bash
# With your virtual environment active:
python -m google.ads.googleads.oauth2 \
  --client_id YOUR_CLIENT_ID \
  --client_secret YOUR_CLIENT_SECRET
```

A browser window will open. Log in with the Google account that has access to the Ads account. Copy the `refresh_token` from the terminal output.

**Create `google-ads.yaml`:**

```bash
cp google-ads.yaml.example google-ads.yaml
```

Open `google-ads.yaml` and replace the placeholder values:

```yaml
developer_token: ABcDeFgHiJkLmNoPqRsTuVwXyZ   # your real token
client_id: 1234567890-abc123.apps.googleusercontent.com
client_secret: GOCSPX-yoursecrethere
refresh_token: 1//0gABcDeFgHiJkLmNo...
use_proto_plus: True
```

**Create `.env`:**

```bash
cp .env.example .env
```

If `google-ads.yaml` is in a non-default location, set the path:

```
GOOGLE_ADS_CONFIGURATION_FILE_PATH=/Users/yourname/projects/google-ads-mcp/google-ads.yaml
```

If it's in `~/google-ads.yaml` or `~/.config/google-ads.yaml`, leave `.env` blank.

### 5. Test the server locally

```bash
# With your virtual environment active:
python server.py
```

The server starts and listens on stdio. You'll see no output — that's correct.  
Press `Ctrl+C` to stop it.

To confirm tools are registered without Claude Desktop, you can use the MCP inspector:

```bash
npx @modelcontextprotocol/inspector python server.py
```

Open the URL it prints in a browser. You should see `hello` and `get_campaigns` listed.

---

## Connecting to Claude Desktop

### 1. Find your config file

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

**Shortcut (macOS):** Open Claude Desktop → Settings → Developer → Edit Config

### 2. Edit `claude_desktop_config.json`

Add your server to the `mcpServers` block. Use the **absolute path** to your virtual environment's Python and your `server.py`.

**macOS example:**
```json
{
  "mcpServers": {
    "google-ads": {
      "command": "/Users/yourname/projects/google-ads-mcp/.venv/bin/python",
      "args": ["/Users/yourname/projects/google-ads-mcp/server.py"],
      "env": {
        "GOOGLE_ADS_CONFIGURATION_FILE_PATH": "/Users/yourname/projects/google-ads-mcp/google-ads.yaml"
      }
    }
  }
}
```

**Windows example:**
```json
{
  "mcpServers": {
    "google-ads": {
      "command": "C:\\Users\\yourname\\projects\\google-ads-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\yourname\\projects\\google-ads-mcp\\server.py"],
      "env": {
        "GOOGLE_ADS_CONFIGURATION_FILE_PATH": "C:\\Users\\yourname\\projects\\google-ads-mcp\\google-ads.yaml"
      }
    }
  }
}
```

> **Tip:** If you already have other MCP servers in the config, add `"google-ads": { ... }` alongside them inside the same `"mcpServers"` object. Don't replace the whole file.

### 3. Restart Claude Desktop

Fully quit the app (don't just close the window):
- **macOS:** `Cmd+Q`
- **Windows:** Right-click the system tray icon → Quit

Reopen Claude Desktop. In a new chat, click the **🔨 hammer icon** — you should see `hello` and `get_campaigns` listed.

---

## Using the Tools in Claude Desktop

**Test the hello tool:**
> "Say hello to me using the MCP tool"

**Fetch campaign data:**
> "Get my campaign summary for customer ID 1234567890"

**Full analyst prompt:**
> "Fetch campaigns for account 1234567890 and summarize performance. Which campaign has the best CTR? Which is spending the most with the lowest conversion rate?"

---

## Troubleshooting

**Hammer icon not appearing:**  
Check your JSON is valid (no trailing commas). Use a JSON validator like [jsonlint.com](https://jsonlint.com). Fully restart Claude Desktop.

**"Configuration file not found" error:**  
Make sure the path in `GOOGLE_ADS_CONFIGURATION_FILE_PATH` uses absolute paths and the file actually exists at that location.

**"Developer token not approved" error:**  
Your developer token may be pending approval or set to test access only. Basic Access is required for production accounts.

**Logs location:**
- macOS: `~/Library/Logs/Claude/`
- Windows: `%APPDATA%\Claude\logs\`

---

## Security Notes

- Never commit `.env` or `google-ads.yaml` to git. Both are in `.gitignore`.
- The `developer_token` and `refresh_token` are long-lived secrets — treat them like passwords.
- Claude Desktop passes environment variables you set in `claude_desktop_config.json` directly to the subprocess; they don't appear in Claude's responses.

---

## Extending the Server

To add more tools, add a function to `ads.py` and decorate a wrapper in `server.py` with `@mcp.tool()`. Some ideas:

- `get_keywords(customer_id, campaign_id)` — keyword-level performance
- `get_ad_groups(customer_id)` — ad group breakdown
- `get_search_terms(customer_id)` — search term report
- `compare_date_ranges(customer_id, range_a, range_b)` — week-over-week or month-over-month

---

## Updated Tool Reference (v2)

### Tools

| Tool | Description |
|------|-------------|
| `hello(name)` | Sanity check — no API call |
| `preview_date_range(...)` | Show what dates a preset resolves to before querying |
| `get_campaigns(...)` | Campaign performance with flexible date range + granularity |
| `get_daily_metrics(...)` | Convenience wrapper — forces `granularity="daily"` |

---

### `get_campaigns` parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `customer_id` | string | required | 10-digit ID, no dashes |
| `date_range` | string | `last_30_days` | Preset name (see below). Ignored if start+end given. |
| `start_date` | string | — | Custom start `YYYY-MM-DD` |
| `end_date` | string | — | Custom end `YYYY-MM-DD` |
| `granularity` | string | `daily` | `daily` / `weekly` / `monthly` |
| `compare_previous` | bool | `false` | Include prior period + delta % |

### Date range presets

| Preset | What it resolves to |
|--------|---------------------|
| `today` | Today only |
| `yesterday` | Yesterday only |
| `last_7_days` | Last 7 days including today |
| `last_30_days` | Last 30 days including today |
| `this_month` | 1st of current month → today |
| `last_month` | Full previous calendar month |
| `last_6_months` | First day of 6 months ago → today |
| `last_12_months` | First day of 12 months ago → today |

### Granularity guidance

| Granularity | Best for |
|-------------|----------|
| `daily` | Up to ~90 days (7 days, 30 days) |
| `weekly` | 30 days to 6 months |
| `monthly` | 3 months to 12 months |

---

### Example Claude Desktop prompts (v2)

```
"Show me campaign performance for last week using daily granularity"
→ get_campaigns(customer_id="...", date_range="last_7_days", granularity="daily")

"How did my campaigns do in Q1 2024 vs Q4 2023?"
→ get_campaigns(customer_id="...", start_date="2024-01-01", end_date="2024-03-31",
                granularity="monthly", compare_previous=True)

"Monthly campaign breakdown for the last year"
→ get_campaigns(customer_id="...", date_range="last_12_months", granularity="monthly")

"Which campaigns are trending up this month vs last month?"
→ get_campaigns(customer_id="...", date_range="this_month", compare_previous=True)
```

### Response shape

```json
{
  "meta": {
    "customer_id": "1234567890",
    "date_range": { "start": "2024-01-01", "end": "2024-03-31" },
    "granularity": "monthly",
    "compare_previous": true,
    "rows_returned": 48,
    "capped_at": null
  },
  "summary": {
    "impressions": 120000, "clicks": 4200, "cost_usd": 3850.00,
    "conversions": 210.5, "ctr": 0.035, "cpc_usd": 0.92,
    "cost_per_conversion_usd": 18.29
  },
  "campaigns": [
    {
      "campaign_id": "987654321",
      "campaign_name": "Brand - Search",
      "status": "ENABLED",
      "totals": { "impressions": 45000, "clicks": 1800, ... },
      "previous_period": { "impressions": 41000, "clicks": 1650, ... },
      "delta": { "impressions": 9.76, "clicks": 9.09, "cost_usd": -2.1, ... },
      "timeseries": [
        { "period": "2024-01-01", "impressions": 15000, "clicks": 590, ... },
        { "period": "2024-02-01", "impressions": 14800, "clicks": 601, ... },
        { "period": "2024-03-01", "impressions": 15200, "clicks": 609, ... }
      ]
    }
  ]
}
```
