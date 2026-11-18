# dailymeteo-mcp

<!-- mcp-name: io.github.srpp011/dailymeteo-mcp -->

An [MCP](https://modelcontextprotocol.io/) server for [DailyMeteo](https://app.dailymeteo.com/). With it, an AI assistant (Claude, VS Code, Cursor and other MCP clients) can answer questions about historical weather and climate change for any land location. Data are 1 km grids from 1961 to the present.

> *How much warmer are July days in Belgrade now than in 1961–1990?*
> *Which was the wettest year in Lisbon since 1961?*
> *Download daily mean temperature grids for Europe for 2003.*

## Install

**Easiest:** ask your AI assistant (Claude Code, Cursor, Cline…): *"Install the DailyMeteo MCP server from github.com/srpp011/dailymeteo-mcp"*. It will follow [llms-install.md](llms-install.md).

**Claude Code plugin.** The plugin connects to the hosted server at `https://mcp.dailymeteo.com/mcp` and adds a skill that tells Claude which tool to use. Nothing is installed locally. It asks for a DailyMeteo API key (Account → API Keys), which is optional and only needed for daily values:

```
claude plugin marketplace add srpp011/dailymeteo-mcp
claude plugin install dailymeteo@dailymeteo
```

**Hosted server in any client.** Add `https://mcp.dailymeteo.com/mcp` as a remote (streamable HTTP) MCP server. For daily values, send your API key in the `X-DailyMeteo-Api-Key` header, e.g. in Claude Code:

```
claude mcp add --transport http dailymeteo https://mcp.dailymeteo.com/mcp --header "X-DailyMeteo-Api-Key: YOUR_KEY"
```

The hosted server has the tools that need no account on the server side: places and areas, values, normals, app links and the Zenodo archive list with download links. Account credits, point-history and area orders, and archive downloads to disk need the local server below.

**Local server.** All tools, including the account ones. It needs [uv](https://docs.astral.sh/uv/) and runs with `uvx --python 3.12 dailymeteo-mcp`. See [Configuration](#configuration).

## Tools

Everything the DailyMeteo app offers, for land areas worldwide, from 1961 to the present:

| Tool | What it does | Cost |
|---|---|---|
| `find_location` | Place name → latitude/longitude (OpenStreetMap) | free |
| `find_area` | Area name → boundary polygon and size, for area downloads | free |
| `get_weather` | Daily, monthly or annual values for a location; several variables at once; summary, yearly aggregates, trend, CSV | monthly/annual free; daily 1 credit per day and variable |
| `get_climate_normals` | Normals 1961–1990 and 1991–2020 and their change (year, months, or a calendar day) | free |
| `account_status` | Plan, API credits, bulk credits | free |
| `request_point_history` | Every variable, daily, for one location (whole record by default), CSV by email | 1 bulk credit |
| `estimate_area_download` | Cost of daily rasters clipped to an area (max 3,000 km²) | free |
| `request_area_download` | Daily GeoTIFF rasters clipped to an area, by email | API credits |
| `app_link` | Opens the location and series in the DailyMeteo app (map, chart, CSV/PDF export) | free |
| `list_gridded_files` / `download_gridded_files` | MeteoEurope1km raster archives on Zenodo (Europe, 1961–2020, incl. sea-level pressure) | free |

Variables are `tmean`, `tmax` and `tmin` in °C, and `prcp` in mm (monthly and annual values are totals).

As in the app, daily requests over 1,000 credits ask for the user's confirmation, and area downloads should be estimated before they are ordered. Repeating the same daily request is not charged again. Long series are not dumped into the conversation. They are summarised (per variable and per year) and saved as CSV.

## Configuration

All environment variables are optional. Without any of them, monthly and annual values, normals, links and Zenodo grids work.

- `DAILYMETEO_EMAIL` and `DAILYMETEO_PASSWORD`: your DailyMeteo account. They enable daily values, credits, point history and area downloads. Sign up at https://app.dailymeteo.com/.
- `DAILYMETEO_API_KEY`: alternative for daily values only (Account → API Keys).
- `DAILYMETEO_OUTPUT_DIR`: where CSV files and downloads are saved (default `~/dailymeteo`).

### Running the hosted mode yourself

`DAILYMETEO_MCP_REMOTE=1` starts the server over streamable HTTP at `/mcp` (stateless, JSON responses), with `/health` and `/files/<token>/<name>.csv` for CSV links that expire after one hour. In this mode the account tools and disk downloads are left out, and daily values use only the API key the client sends in `X-DailyMeteo-Api-Key` (or `Authorization: Bearer`), never one from the server's environment.

- `DAILYMETEO_MCP_PUBLIC_URL`: public base URL for CSV links (e.g. `https://mcp.dailymeteo.com`).
- `DAILYMETEO_MCP_HOST`, `DAILYMETEO_MCP_PORT`: listen address (default `0.0.0.0:8000`).
- `DAILYMETEO_OUTPUT_DIR`: where the CSV files are kept.

```
docker run -d -p 8000:8000 -e DAILYMETEO_MCP_REMOTE=1 -e DAILYMETEO_MCP_PUBLIC_URL=https://mcp.example.org dailymeteo-mcp
```

Run it behind a reverse proxy with HTTPS. Requests to OpenStreetMap Nominatim are cached and sent at most one per second, as its usage policy asks.

### Claude Code

```
claude mcp add dailymeteo -s user -e DAILYMETEO_EMAIL=you@example.com -e DAILYMETEO_PASSWORD=... -- uvx --python 3.12 dailymeteo-mcp
```

### Claude Desktop, Cursor, VS Code (`mcpServers` JSON)

```json
{
  "mcpServers": {
    "dailymeteo": {
      "command": "uvx",
      "args": ["--python", "3.12", "dailymeteo-mcp"],
      "env": { "DAILYMETEO_EMAIL": "you@example.com", "DAILYMETEO_PASSWORD": "..." }
    }
  }
}
```

### Docker (no local Python)

```
docker build -t dailymeteo-mcp .
claude mcp add-json dailymeteo -s user '{"type":"stdio","command":"docker","args":["run","-i","--rm","-e","DAILYMETEO_EMAIL","-e","DAILYMETEO_PASSWORD","-v","/path/to/output:/data","dailymeteo-mcp"]}'
```

## Data and citation

The values are interpolated grids, not station measurements. Results used in a publication should cite:

Sekulić, A., & Kilibarda, M. (2026). *MeteoEurope1km (1961–2020): daily gridded meteorological dataset for Europe at a 1-km spatial resolution*. Zenodo. https://doi.org/10.5281/zenodo.23264155

Built on the Python client [`dailymeteo`](https://pypi.org/project/dailymeteo/). License: GPL-2.0-or-later.
