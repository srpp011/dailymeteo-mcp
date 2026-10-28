"""MCP server for DailyMeteo: historical weather and climate normals for any land location, 1961 to the present."""
from __future__ import annotations

import functools
import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Optional

import dailymeteo as dm
import requests
from dailymeteo import meteoeurope1km as meu
from dailymeteo._http import session
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__

CITATION = (
    "Sekulić, A., & Kilibarda, M. (2026). MeteoEurope1km (1961–2020): daily gridded meteorological "
    "dataset for Europe at a 1-km spatial resolution. Zenodo. https://doi.org/10.5281/zenodo.23264155"
)
UNITS = {"tmean": "°C", "tmax": "°C", "tmin": "°C", "prcp": "mm"}
NAMES = {
    "tmean": "mean air temperature",
    "tmax": "maximum air temperature",
    "tmin": "minimum air temperature",
    "prcp": "precipitation",
}
PERIODS = ("1961-1990", "1991-2020")

INSTRUCTIONS = f"""\
DailyMeteo gives gridded weather data at 1 km for land areas worldwide (Europe and the rest of the world),
from 1961 to the present, interpolated from GHCN-Daily, ECA&D and GSOD station observations.

Variables: tmean, tmax, tmin (°C) and prcp (mm). Monthly and annual precipitation values are totals (sums);
temperature aggregates are means.

Which tool to use:
- Place names: call find_location first and use its lat/lon; if several places match, ask the user.
- Monthly or annual values (free): get_monthly_or_annual.
- Climate normals for 1961-1990 and 1991-2020, and how much they changed (free): get_climate_normals.
- Daily values: get_daily_values. Each returned day costs one credit on the user's DailyMeteo account,
  so keep ranges short and prefer monthly or annual data when they answer the question.
- Raw grids (GeoTIFF) for Europe 1961-2020, including sea-level pressure: list_gridded_files and
  download_gridded_files (MeteoEurope1km on Zenodo, archives of 1-3.5 GB).

Values for the sea or outside the data come back as null. Mention that the data are interpolated grids,
not station measurements. When results are used in a publication, cite: {CITATION}
"""

mcp = MCPServer(
    "dailymeteo",
    title="DailyMeteo",
    instructions=INSTRUCTIONS,
    website_url="https://app.dailymeteo.com/",
    version=__version__,
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
PAID = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)

Lat = Annotated[float, Field(ge=-90, le=90, description="Latitude in decimal degrees (WGS84)")]
Lon = Annotated[float, Field(ge=-180, le=180, description="Longitude in decimal degrees (WGS84)")]
Variable = Annotated[Literal["tmean", "tmax", "tmin", "prcp"], Field(description="tmean, tmax, tmin (°C) or prcp (mm)")]

def _guard(fn):
    """Expected failures reach the model as readable messages (MCPServer hides other exceptions)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, LookupError, dm.DailyMeteoError, requests.RequestException) as e:
            raise ToolError(str(e)) from e

    return wrapper


_FORMATS = {"ann": (r"\d{4}", "YYYY"), "mon": (r"\d{4}-\d{2}", "YYYY-MM"), "day": (r"\d{4}-\d{2}-\d{2}", "YYYY-MM-DD")}


def _check_dates(time_scale: str, *values: str) -> None:
    pattern, fmt = _FORMATS[time_scale]
    for v in values:
        if not re.fullmatch(pattern, v):
            raise ToolError(f"dates for time_scale={time_scale!r} must be {fmt}; got {v!r}")


def _rows(df) -> list[dict]:
    return [{"timestamp": t, "value": None if v != v else round(float(v), 1)} for t, v in zip(df.timestamp, df.value)]


def _summary(df, time_scale: str) -> dict:
    valid = df.dropna(subset=["value"])
    if valid.empty:
        return {"note": "no data for this location (probably sea or outside the covered area)"}
    imin, imax = valid.value.idxmin(), valid.value.idxmax()
    out = {
        "count": int(len(valid)),
        "mean": round(float(valid.value.mean()), 2),
        "min": {"timestamp": valid.timestamp[imin], "value": float(valid.value[imin])},
        "max": {"timestamp": valid.timestamp[imax], "value": float(valid.value[imax])},
    }
    if time_scale == "ann" and len(valid) >= 10:
        import numpy as np

        slope = np.polyfit(valid.timestamp.astype(int), valid.value.astype(float), 1)[0]
        out["linear_trend_per_decade"] = round(float(slope) * 10, 2)
    return out


def _save_csv(df, stem: str) -> str:
    folder = Path(os.environ.get("DAILYMETEO_OUTPUT_DIR") or Path.home() / "dailymeteo")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', stem)}.csv"
    df.to_csv(path, index=False)
    return str(path)


@mcp.tool(title="Find a place", annotations=READ)
@_guard
def find_location(
    query: Annotated[str, Field(description="Place name, e.g. 'Kopaonik' or 'Lisbon, Portugal'")],
    limit: Annotated[int, Field(ge=1, le=5)] = 3,
) -> list[dict]:
    """Find latitude and longitude of a place (OpenStreetMap Nominatim). Returns up to `limit` matches."""
    r = session().get(
        dm.api.NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": limit},
        headers={"User-Agent": dm._http.USER_AGENT},
        timeout=60,
    )
    r.raise_for_status()
    hits = [{"name": h["display_name"], "lat": round(float(h["lat"]), 5), "lon": round(float(h["lon"]), 5)} for h in r.json()]
    if not hits:
        raise ToolError(f"no place found for {query!r}; try adding the country")
    return hits


@mcp.tool(title="Monthly or annual weather values", annotations=READ)
@_guard
def get_monthly_or_annual(
    lat: Lat,
    lon: Lon,
    variable: Variable,
    time_scale: Annotated[Literal["mon", "ann"], Field(description="mon (monthly) or ann (annual)")],
    start: Annotated[str, Field(description="First month YYYY-MM (mon) or year YYYY (ann), from 1961")],
    end: Annotated[str, Field(description="Last month YYYY-MM (mon) or year YYYY (ann)")],
    save_csv: Annotated[bool, Field(description="Also save the series as a CSV file and return its path")] = False,
) -> dict:
    """Monthly or annual values for one location, 1961 to the last complete month/year. Free, no API key.

    Precipitation values are monthly/annual totals; temperatures are means. Annual series of 10+ years
    include a linear trend per decade.
    """
    _check_dates(time_scale, start, end)
    df = dm.get_meteo(lat, lon, var=variable, agg_level="agg", time_scale=time_scale, start=start, end=end)
    out = {
        "variable": f"{variable} ({NAMES[variable]})",
        "unit": UNITS[variable],
        "location": {"lat": lat, "lon": lon},
        "summary": _summary(df, time_scale),
        "values": _rows(df),
    }
    if save_csv:
        out["csv"] = _save_csv(df, f"{variable}_{time_scale}_{start}_{end}_{lat}_{lon}")
    return out


@mcp.tool(title="Climate normals 1961-1990 vs 1991-2020", annotations=READ)
@_guard
def get_climate_normals(
    lat: Lat,
    lon: Lon,
    variable: Variable,
    time_scale: Annotated[Literal["ann", "mon", "day"], Field(description="ann (whole year), mon (by month) or day (one calendar day)")] = "mon",
    month: Annotated[Optional[int], Field(ge=1, le=12, description="Only this month (mon), or the month of the day (day)")] = None,
    day: Annotated[Optional[int], Field(ge=1, le=31, description="Day of month, required for time_scale=day")] = None,
) -> dict:
    """Climate normals for 1961-1990 and 1991-2020 and their difference (newer minus older). Free, no API key.

    Without `month`, time_scale=mon returns all 12 months. Annual precipitation normals are yearly totals.
    """
    if time_scale == "ann":
        frames = [dm.get_meteo(lat, lon, var=variable, agg_level="ltm", time_scale="ann", time=y) for y in ("1961", "1991")]
        keys = [""]
    elif time_scale == "mon":
        months = [month] if month else list(range(1, 13))
        frames = [dm.get_meteo(lat, lon, var=variable, agg_level="ltm", time_scale="mon", time=[f"{m:02d}" for m in months])]
        keys = [f"{m:02d}" for m in months]
    else:
        if not (month and day):
            raise ToolError("time_scale=day needs both month and day")
        date(2000, month, day)  # validates the calendar day (2000 is a leap year)
        frames = [dm.get_meteo(lat, lon, var=variable, agg_level="ltm", time_scale="day", time=f"{month:02d}-{day:02d}")]
        keys = [f"{day:02d}.{month:02d}"]
    values = {}
    for df in frames:
        for t, v in zip(df.timestamp, df.value):
            k, _, period = t.rpartition(".") if "." in t else ("", "", t)
            values[(k, period)] = None if v != v else round(float(v), 1)
    rows = []
    for k in keys:
        old, new = values.get((k, PERIODS[0])), values.get((k, PERIODS[1]))
        row = {"period_of_year": k or "year", PERIODS[0]: old, PERIODS[1]: new,
               "difference": None if old is None or new is None else round(new - old, 1)}
        rows.append(row)
    return {"variable": f"{variable} ({NAMES[variable]})", "unit": UNITS[variable], "location": {"lat": lat, "lon": lon}, "normals": rows}


@mcp.tool(title="Daily weather values (uses credits)", annotations=PAID)
@_guard
def get_daily_values(
    lat: Lat,
    lon: Lon,
    variable: Variable,
    start: Annotated[str, Field(description="First day YYYY-MM-DD, from 1961-01-01")],
    end: Annotated[str, Field(description="Last day YYYY-MM-DD (data lag the present by a few days)")],
    max_days: Annotated[int, Field(ge=1, le=25000, description="Refuse requests longer than this; raise it only after the user agreed to the credit cost")] = 31,
    save_csv: Annotated[bool, Field(description="Also save the series as a CSV file and return its path")] = False,
) -> dict:
    """Daily values for one location. Needs a DailyMeteo API key (DAILYMETEO_API_KEY) and costs one credit per returned day.

    Requests longer than `max_days` (default 31) are refused so credits are not spent by accident: tell the
    user how many days (credits) the request needs and ask before raising `max_days`. Prefer
    get_monthly_or_annual when monthly or annual values answer the question.
    """
    _check_dates("day", start, end)
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    if d1 < d0:
        raise ToolError("end is before start")
    days = (d1 - d0).days + 1
    if days > max_days:
        raise ToolError(f"this request returns {days} days and costs {days} credits, more than max_days={max_days}; "
                         "ask the user to confirm the cost, then call again with a higher max_days")
    key = os.environ.get("DAILYMETEO_API_KEY")
    if not key:
        raise ToolError("daily data need an API key: set DAILYMETEO_API_KEY in the MCP server configuration "
                         "(key from https://app.dailymeteo.com/ → Account → API Keys)")
    df = dm.get_meteo(lat, lon, api_key=key, var=variable, agg_level="agg", time_scale="day", start=start, end=end)
    rows = _rows(df)
    out = {"variable": f"{variable} ({NAMES[variable]})", "unit": UNITS[variable], "location": {"lat": lat, "lon": lon},
           "credits_used": days, "summary": _summary(df, "day")}
    if len(rows) <= 400:
        out["values"] = rows
    else:
        out["values"] = "too many to list; use the summary or save_csv=true"
    if save_csv or len(rows) > 400:
        out["csv"] = _save_csv(df, f"{variable}_day_{start}_{end}_{lat}_{lon}")
    return out


GridVariable = Annotated[Literal["tmean", "tmax", "tmin", "prcp", "slp"], Field(description="tmean, tmax, tmin, prcp or slp (sea-level pressure, daily only)")]
Product = Annotated[
    Literal["day", "mon", "ann", "ltm_day", "ltm_mon_ann", "ltm_diff"],
    Field(description="day (one archive per year), mon (one per decade), ann (1961-2020), ltm_day / ltm_mon_ann (normals), ltm_diff (1991-2020 minus 1961-1990)"),
]
Years = Annotated[Optional[list[int]], Field(description="Years 1961-2020; required for day and mon")]
Period = Annotated[Optional[Literal["1961-1990", "1991-2020"]], Field(description="Normal period for ltm_day / ltm_mon_ann; default both")]


@mcp.tool(title="List MeteoEurope1km grid archives", annotations=READ)
@_guard
def list_gridded_files(variable: GridVariable, product: Product = "day", years: Years = None, period: Period = None) -> dict:
    """List MeteoEurope1km archives on Zenodo (Europe, 1 km, 1961-2020, Cloud-Optimized GeoTIFF) with sizes.

    Rasters are Equi7 Europe (EPSG:27704), Int16 in tenths of the unit (°C, mm, hPa), NoData -9999.
    """
    t = meu.files(var=variable, product=product, years=years, period=period)
    return {
        "files": [{"file": r.file, "size_mb": round(r.size / 1e6), "zenodo_record": f"https://doi.org/{r.doi}"} for r in t.itertuples()],
        "total_gb": round(float(t["size"].sum()) / 1e9, 2),
        "citation": CITATION,
    }


@mcp.tool(title="Download MeteoEurope1km grid archives", annotations=WRITES)
@_guard
def download_gridded_files(
    variable: GridVariable,
    product: Product = "day",
    years: Years = None,
    period: Period = None,
    dest_dir: Annotated[Optional[str], Field(description="Folder for the archives; default ~/dailymeteo/meteoeurope1km")] = None,
    unzip: bool = False,
    max_total_gb: Annotated[float, Field(gt=0, description="Refuse downloads larger than this; raise only after the user agreed")] = 5,
) -> dict:
    """Download MeteoEurope1km archives from Zenodo, verify MD5 and optionally unzip. Can take a long time.

    Check the size with list_gridded_files first and confirm large downloads with the user.
    """
    t = meu.files(var=variable, product=product, years=years, period=period)
    gb = float(t["size"].sum()) / 1e9
    if gb > max_total_gb:
        raise ToolError(f"the download is {gb:.1f} GB, more than max_total_gb={max_total_gb}; confirm with the user first")
    dest = Path(dest_dir) if dest_dir else Path(os.environ.get("DAILYMETEO_OUTPUT_DIR") or Path.home() / "dailymeteo") / "meteoeurope1km"
    out = meu.download(var=variable, product=product, years=years, period=period, dest_dir=dest, unzip=unzip, progress=False)
    return {"folder": str(dest.resolve()), "files": out.path.tolist(), "total_gb": round(gb, 2), "citation": CITATION}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
