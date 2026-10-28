# dailymeteo-mcp

An [MCP](https://modelcontextprotocol.io/) server for [DailyMeteo](https://app.dailymeteo.com/). With it, an AI assistant (Claude, VS Code, Cursor and other MCP clients) can answer questions about historical weather and climate change for any land location. Data are 1 km grids from 1961 to the present.

> *How much warmer are July days in Belgrade now than in 1961–1990?*
> *Which was the wettest year in Lisbon since 1961?*
> *Download daily mean temperature grids for Europe for 2003.*

## Tools

| Tool | What it does | Cost |
|---|---|---|
| `find_location` | Place name → latitude/longitude (OpenStreetMap) | free |
| `get_monthly_or_annual` | Monthly or annual values, summary, trend per decade, optional CSV | free |
| `get_climate_normals` | Normals 1961–1990 and 1991–2020 and their difference (year, months, or a calendar day) | free |
| `get_daily_values` | Daily values | 1 credit per day, API key required |
| `list_gridded_files` | MeteoEurope1km archives on Zenodo (Europe, 1961–2020, GeoTIFF) | free |
| `download_gridded_files` | Download, verify MD5, unzip | free |

Variables are `tmean`, `tmax` and `tmin` in °C, and `prcp` in mm (monthly and annual values are totals). The gridded files also include `slp` (sea-level pressure).

Daily requests longer than 31 days are refused until the user agrees to the credit cost. Large grid downloads (over 5 GB by default) are refused the same way.

## Configuration

Environment variables, both optional:

- `DAILYMETEO_API_KEY`: needed only for daily values. Get one at https://app.dailymeteo.com/ → Account → API Keys.
- `DAILYMETEO_OUTPUT_DIR`: where CSV files and downloads are saved (default `~/dailymeteo`).

### Claude Code

```
claude mcp add dailymeteo -s user -e DAILYMETEO_API_KEY=your-key -- uvx dailymeteo-mcp
```

### Claude Desktop, Cursor, VS Code (`mcpServers` JSON)

```json
{
  "mcpServers": {
    "dailymeteo": {
      "command": "uvx",
      "args": ["dailymeteo-mcp"],
      "env": { "DAILYMETEO_API_KEY": "your-key" }
    }
  }
}
```

### Docker (no local Python)

```
docker build -t dailymeteo-mcp .
claude mcp add-json dailymeteo -s user '{"type":"stdio","command":"docker","args":["run","-i","--rm","-e","DAILYMETEO_API_KEY","-v","/path/to/output:/data","dailymeteo-mcp"]}'
```

## Data and citation

The values are interpolated grids, not station measurements. Results used in a publication should cite:

Sekulić, A., & Kilibarda, M. (2026). *MeteoEurope1km (1961–2020): daily gridded meteorological dataset for Europe at a 1-km spatial resolution*. Zenodo. https://doi.org/10.5281/zenodo.23264155

Built on the Python client [`dailymeteo`](https://pypi.org/project/dailymeteo/). License: GPL-2.0-or-later.
