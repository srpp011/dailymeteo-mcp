# DailyMeteo

![DailyMeteo](icon.svg)

Historical weather and climate data for any place on land, from 1961 to a few days ago, at 1 km resolution. Claude can answer questions such as *"How much warmer are July days in Belgrade now than in 1961–1990?"* or *"Which was the wettest year in Lisbon since 1961?"*.

The data come from [DailyMeteo](https://app.dailymeteo.com/), developed by GILAB and the Faculty of Civil Engineering, University of Belgrade. They are daily grids of mean, maximum and minimum air temperature and precipitation, interpolated from GHCN-Daily, ECA&D and GSOD station observations. They are model grids, not station measurements.

## What it adds

- **MCP server `dailymeteo`** at `https://mcp.gilab.rs/mcp`, with 6 tools:
  - places and areas;
  - daily, monthly and annual values;
  - climate normals for 1961–1990 and 1991–2020 and their change;
  - links to the DailyMeteo app;
  - the MeteoEurope1km raster archives on Zenodo, with download links.
- **Skill `dailymeteo`**, which tells Claude which tool fits a question and how to present results and costs.

Nothing is installed on your computer.

## API key (optional)

Without a key, these work: monthly and annual values, climate normals, app links and the Zenodo archives.

On install the plugin asks for a DailyMeteo API key, which you can create at https://app.dailymeteo.com/ (Account). It is optional and kept in the secure credential store. With a key, the plugin can also fetch daily values, which use the account's credits. Daily requests over 1,000 credits ask for confirmation first, as in the DailyMeteo app.

Account credits, full point histories and area downloads by email are in the DailyMeteo app, or in the local version of the server (`uvx dailymeteo-mcp`, see the [repository README](https://github.com/srpp011/dailymeteo-mcp#readme)).

## What it sends and where

- **Connects to** `mcp.gilab.rs`, run by GILAB, which develops DailyMeteo. The server is the open-source package [`dailymeteo-mcp`](https://pypi.org/project/dailymeteo-mcp/) (source: https://github.com/srpp011/dailymeteo-mcp). It receives the arguments of each tool call (place names, coordinates, variables, dates) and, if you set one, your API key in the `X-DailyMeteo-Api-Key` header.
- **The server sends requests to**:
  - `api.dailymeteo.com`: coordinates, variables and dates of each query, with your API key for daily values;
  - `nominatim.openstreetmap.org`: place names that you ask about, to find coordinates and boundaries;
  - `zenodo.org`: to list the MeteoEurope1km archives.
- **Long series** are also given as a CSV file on `mcp.gilab.rs`, behind a random link that expires after one hour.

The server keeps no record of who asked what beyond standard web server logs. See the DailyMeteo [privacy policy](https://dailymeteo.com/privacy) and [terms](https://dailymeteo.com/terms).

## Citation

Sekulić, A., & Kilibarda, M. (2026). *MeteoEurope1km (1961–2020): daily gridded meteorological dataset for Europe at a 1-km spatial resolution*. Zenodo. https://doi.org/10.5281/zenodo.23264155

License: GPL-2.0-or-later.
