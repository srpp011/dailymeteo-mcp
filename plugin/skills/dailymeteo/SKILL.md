---
name: dailymeteo
description: Use for questions about past weather or climate at a place on land, 1961 to today. Covers temperatures, precipitation, climate normals and change since 1961-1990, the warmest, wettest or coldest year or month, daily series, gridded data downloads for an area, and DailyMeteo credits. Uses the dailymeteo MCP tools.
---

# DailyMeteo data

The dailymeteo tools give interpolated 1 km grids for land areas worldwide, from 1961 to a few days ago:
tmean, tmax, tmin (°C) and prcp (mm). They are model grids, not station measurements; say so when it matters.

## Choosing a tool

1. **Place names** → `find_location` first. If several places match, ask which one. For an area (municipality,
   lake, park) use `find_area`, which also tells whether it fits the 3,000 km² download limit.
2. **"How has the climate changed" / "is it warmer than it used to be"** → `get_climate_normals`
   (1961-1990 vs 1991-2020, free). Use `time_scale="mon"` for seasons and `"ann"` for the year.
3. **Series, records and trends** → `get_weather`:
   - Prefer `time_scale="ann"` or `"mon"`, which are free. Annual series include a trend per decade, and
     long series are summarised by year and saved as CSV (report the file path).
   - Use `"day"` only when daily detail is needed. It costs 1 credit per day and variable. Over 1,000
     credits the tool asks for `confirm_credits=true`: tell the user the cost and wait for a yes.
   - Ask for several variables in one call (e.g. `["tmax", "prcp"]`).
4. **Raw data files**:
   - One location, every variable, whole record → `request_point_history` (1 bulk credit, CSV by email).
   - An area → `estimate_area_download`, show the cost, then `request_area_download` after the user
     agrees. Rasters arrive by email.
   - Europe 1961-2020 rasters, including sea-level pressure → `list_gridded_files` /
     `download_gridded_files` (free). Tell the user the size first.
5. **Credits / plan** → `account_status`.

If a tool reports a missing account, the user can add it by reinstalling the plugin
(`claude plugin uninstall dailymeteo@dailymeteo`, then `claude plugin install dailymeteo@dailymeteo`). The install
asks for the email and password, and the password goes to the secure credential store. Free tools work without it.

## Presenting results

- Give the numbers with units and the period they cover. For changes, say which periods are compared.
- Add the `app_link` (from `get_weather`, or call `app_link`) so the user can open the chart on dailymeteo.com.
- Null values mean no data (sea or outside the grid), not zero.
- For publications, cite: Sekulić, A., & Kilibarda, M. (2026). MeteoEurope1km (1961–2020). Zenodo.
  https://doi.org/10.5281/zenodo.23264155
