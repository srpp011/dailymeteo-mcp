# DailyMeteo

![DailyMeteo](icon.svg)

Historical weather and climate data for any place on land, from 1961 to a few days ago, at 1 km resolution. Claude can answer questions such as *"How much warmer are July days in Belgrade now than in 1961–1990?"* or *"Which was the wettest year in Lisbon since 1961?"*. It can also order raw data for a point or an area.

The data come from [DailyMeteo](https://app.dailymeteo.com/), developed by GILAB and the Faculty of Civil Engineering, University of Belgrade. They are daily grids of mean, maximum and minimum air temperature and precipitation, interpolated from GHCN-Daily, ECA&D and GSOD station observations. They are model grids, not station measurements.

## What it adds

- **MCP server `dailymeteo`** with 11 tools:
  - places and areas;
  - daily, monthly and annual values;
  - climate normals for 1961–1990 and 1991–2020 and their change;
  - account credits;
  - point-history and area downloads;
  - links to the DailyMeteo app;
  - the MeteoEurope1km raster archives on Zenodo.
- **Skill `dailymeteo`**, which tells Claude which tool fits a question and how to present results and costs.

## Account (optional)

Without an account, these work: monthly and annual values, climate normals, app links and the Zenodo archives.

On install the plugin asks for a DailyMeteo email and password. Both are optional, and the password is kept in the secure credential store. With an account, the plugin can also fetch daily values, check credits, and order point histories and area downloads, which use the account's credits.

Daily requests over 1,000 credits ask for confirmation first, as in the DailyMeteo app.

## What it runs, sends and fetches

- **Runs** the open-source Python package [`dailymeteo-mcp`](https://pypi.org/project/dailymeteo-mcp/) (source: https://github.com/srpp011/dailymeteo-mcp). It is started with `uvx` at a pinned version on Python 3.12, so [uv](https://docs.astral.sh/uv/) must be installed. The first start downloads the package and its dependencies from PyPI (about 60 MB).
- **Sends requests to**:
  - `api.dailymeteo.com`: coordinates, variables and dates of each query. With an account, the email and password go to `/auth/login/` to obtain a session token.
  - `nominatim.openstreetmap.org`: place names that you ask about, to find coordinates and boundaries.
  - `zenodo.org`: to list and download the MeteoEurope1km archives.
- **Writes files** only when asked:
  - CSV tables of long series;
  - downloaded archives, in `~/dailymeteo`.
- **Orders** through your account: point histories and area downloads that DailyMeteo prepares and sends to your account's email.

Nothing else is collected or sent. See the DailyMeteo [privacy policy](https://dailymeteo.com/privacy) and [terms](https://dailymeteo.com/terms).

## Citation

Sekulić, A., & Kilibarda, M. (2026). *MeteoEurope1km (1961–2020): daily gridded meteorological dataset for Europe at a 1-km spatial resolution*. Zenodo. https://doi.org/10.5281/zenodo.23264155

License: GPL-2.0-or-later.
