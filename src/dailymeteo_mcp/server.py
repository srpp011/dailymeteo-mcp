"""MCP server for DailyMeteo: everything the DailyMeteo app offers, for AI assistants.

Point data (daily, monthly, annual) and climate normals for any land location worldwide, 1961 to the
present; bulk point history and polygon (area) raster downloads; account credits; links to the app;
and the MeteoEurope1km grids on Zenodo.
"""
from __future__ import annotations

import functools
import json
import math
import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Optional
from urllib.parse import urlencode

import dailymeteo as dm
import pandas as pd
import requests
from dailymeteo import meteoeurope1km as meu
from dailymeteo._http import USER_AGENT, session
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__

APP_URL = "https://dailymeteo.com"
CITATION = (
    "Sekulić, A., & Kilibarda, M. (2026). MeteoEurope1km (1961–2020): daily gridded meteorological "
    "dataset for Europe at a 1-km spatial resolution. Zenodo. https://doi.org/10.5281/zenodo.23264155"
)
UNITS = {"tmean": "°C", "tmax": "°C", "tmin": "°C", "prcp": "mm"}
NAMES = {"tmean": "mean air temperature", "tmax": "maximum air temperature",
         "tmin": "minimum air temperature", "prcp": "precipitation"}
PERIODS = ("1961-1990", "1991-2020")
CONFIRM_ABOVE = 1000  # same rule as the DailyMeteo app: day requests over 1,000 credits need confirmation
MAX_LISTED_ROWS = 400

INSTRUCTIONS = f"""\
DailyMeteo: gridded weather data at 1 km for land areas worldwide, from 1961 to the present (the latest
days lag by a few days), interpolated from GHCN-Daily, ECA&D and GSOD station observations.
Variables: tmean, tmax, tmin (°C) and prcp (mm). Monthly/annual precipitation are totals, temperatures means.

Tools:
- find_location: place name -> lat/lon. find_area: place name -> polygon for area downloads.
- get_weather: values for a location, one or more variables, daily / monthly / annual. Monthly and annual
  are free. Daily costs 1 credit per day and variable (repeating the same request is not charged again);
  requests over {CONFIRM_ABOVE} credits need confirm_credits=true after the user agreed to the cost.
  Long series are summarised (with yearly aggregates) and saved as CSV.
- get_climate_normals: normals 1961-1990 and 1991-2020 and their change (free).
- account_status: plan and remaining credits.
- request_point_history: every variable, daily, for one location, emailed as CSV (1 bulk credit).
- estimate_area_download / request_area_download: daily rasters clipped to a polygon up to
  3,000 km², emailed to the user. Always estimate and tell the user the cost before requesting.
- app_link: link that opens the location and series in the DailyMeteo app (map and chart).
- list_gridded_files / download_gridded_files: MeteoEurope1km raster archives (Europe, 1961-2020,
  incl. sea-level pressure) on Zenodo, free.

Values for the sea or outside the data are null. The data are interpolated grids, not station
measurements. Cite results as: {CITATION}
"""

mcp = MCPServer("dailymeteo", title="DailyMeteo", instructions=INSTRUCTIONS,
                website_url="https://app.dailymeteo.com/", version=__version__)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
ORDER = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)

Lat = Annotated[float, Field(ge=-90, le=90, description="Latitude in decimal degrees (WGS84)")]
Lon = Annotated[float, Field(ge=-180, le=180, description="Longitude in decimal degrees (WGS84)")]
Var = Literal["tmean", "tmax", "tmin", "prcp"]
Variables = Annotated[list[Var], Field(min_length=1, description="One or more of tmean, tmax, tmin (°C), prcp (mm)")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")]


# --- helpers ---------------------------------------------------------------------------------------
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


@functools.lru_cache(maxsize=1)
def _account() -> dm.Account | None:
    if os.environ.get("DAILYMETEO_EMAIL") and os.environ.get("DAILYMETEO_PASSWORD"):
        return dm.Account()
    return None


def _require_account() -> dm.Account:
    a = _account()
    if a is None:
        raise ToolError("this needs a signed-in DailyMeteo account: set DAILYMETEO_EMAIL and DAILYMETEO_PASSWORD "
                        "in the MCP server configuration (sign up at https://app.dailymeteo.com/)")
    return a


def _output_dir() -> Path:
    folder = Path(os.environ.get("DAILYMETEO_OUTPUT_DIR") or Path.home() / "dailymeteo")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save_csv(df: pd.DataFrame, stem: str) -> str:
    path = _output_dir() / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', stem)}.csv"
    df.to_csv(path, index=False)
    return str(path)


_FORMATS = {"ann": (r"\d{4}", "YYYY"), "mon": (r"\d{4}-\d{2}", "YYYY-MM"), "day": (r"\d{4}-\d{2}-\d{2}", "YYYY-MM-DD")}


def _check_dates(time_scale: str, values: list[str]) -> None:
    pattern, fmt = _FORMATS[time_scale]
    for v in values:
        if not re.fullmatch(pattern, v):
            raise ToolError(f"dates for time_scale={time_scale!r} must be {fmt}; got {v!r}")


def _summary(s: pd.Series, var: str, time_scale: str) -> dict:
    valid = s.dropna()
    if valid.empty:
        return {"note": "no data for this location (probably sea or outside the covered area)"}
    out = {"count": int(valid.size), "mean": round(float(valid.mean()), 2),
           "min": {"timestamp": valid.idxmin(), "value": float(valid.min())},
           "max": {"timestamp": valid.idxmax(), "value": float(valid.max())}}
    if var == "prcp":
        out["total"] = round(float(valid.sum()), 1)
        if time_scale == "day":
            out["wet_days_ge_1mm"] = int((valid >= 1).sum())
    if time_scale == "ann" and valid.size >= 10:
        import numpy as np

        slope = np.polyfit(valid.index.astype(int), valid.to_numpy(float), 1)[0]
        out["linear_trend_per_decade"] = round(float(slope) * 10, 2)
    return out


def _yearly(wide: pd.DataFrame) -> list[dict]:
    """Yearly aggregates of a daily/monthly table: means for temperature, totals for precipitation."""
    years = wide.index.str[:4]
    agg = {v: ("sum" if v == "prcp" else "mean") for v in wide.columns}
    y = wide.groupby(years).agg(agg).round(1)
    y["n"] = wide.groupby(years).size()
    return [{"year": k, **{c: (None if pd.isna(v) else float(v)) for c, v in row.items()}} for k, row in y.iterrows()]


def _area_km2(rings: list[list[list[float]]]) -> float:
    """Area of a polygon (outer ring minus holes) on a sphere, km²."""
    def ring(r):
        a = 0.0
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            a += math.radians(x2 - x1) * (2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
        return abs(a) * 6371.0088 ** 2 / 2
    return ring(rings[0]) - sum(ring(h) for h in rings[1:])


def _parse_wkt(wkt: str) -> list[list[list[list[float]]]]:
    """POLYGON / MULTIPOLYGON WKT -> list of polygons (list of rings of [lon, lat])."""
    w = wkt.strip()
    kind = w.split("(", 1)[0].strip().upper()
    if kind not in ("POLYGON", "MULTIPOLYGON"):
        raise ToolError("area must be a POLYGON or MULTIPOLYGON in WKT (lon lat order, WGS84)")
    num = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
    body = re.sub(rf"({num})\s+({num})", r"[\1,\2]", w[w.index("("):]).replace("(", "[").replace(")", "]")
    try:
        coords = json.loads(body)
    except ValueError as e:
        raise ToolError("could not read the polygon coordinates") from e
    return coords if kind == "MULTIPOLYGON" else [coords]


def _area_geometry(area_wkt: Optional[str], bbox: Optional[list[float]]) -> tuple[str, float]:
    if bbox:
        w, s, e, n = bbox
        if not (w < e and s < n):
            raise ToolError("bbox must be [west, south, east, north]")
        area_wkt = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    if not area_wkt:
        raise ToolError("give area_wkt (from find_area) or bbox")
    km2 = sum(_area_km2(p) for p in _parse_wkt(area_wkt))
    if km2 > dm.account.AREA_LIMIT_KM2:
        raise ToolError(f"the area is about {km2:,.0f} km²; DailyMeteo area downloads are limited to "
                        f"{dm.account.AREA_LIMIT_KM2:,} km² — use a smaller area or split it")
    return area_wkt, km2


def _to_wkt(geo: dict, max_points: int = 400) -> str:
    def thin(ring):
        step = max(1, len(ring) // max_points)
        r = ring[::step]
        if r[-1] != ring[-1]:
            r.append(ring[-1])
        return "(" + ",".join(f"{x:.5f} {y:.5f}" for x, y in r) + ")"

    if geo["type"] == "Polygon":
        return "POLYGON(" + ",".join(thin(r) for r in geo["coordinates"]) + ")"
    if geo["type"] == "MultiPolygon":
        return "MULTIPOLYGON(" + ",".join("(" + ",".join(thin(r) for r in p) + ")" for p in geo["coordinates"]) + ")"
    raise ValueError(f"no polygon for this place (got {geo['type']})")


def _nominatim(query: str, limit: int, polygon: bool = False) -> list[dict]:
    params = {"q": query, "format": "json", "limit": limit}
    if polygon:
        params |= {"polygon_geojson": 1, "polygon_threshold": 0.002}
    r = session().get(dm.api.NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise ToolError(f"no place found for {query!r}; try adding the country")
    return hits


# --- tools: places ---------------------------------------------------------------------------------
@mcp.tool(title="Find a place", annotations=READ)
@_guard
def find_location(
    query: Annotated[str, Field(description="Place name, e.g. 'Kopaonik' or 'Lisbon, Portugal'")],
    limit: Annotated[int, Field(ge=1, le=5)] = 3,
) -> list[dict]:
    """Latitude and longitude of a place (OpenStreetMap Nominatim). If several match, ask the user which one."""
    return [{"name": h["display_name"], "lat": round(float(h["lat"]), 5), "lon": round(float(h["lon"]), 5)}
            for h in _nominatim(query, limit)]


@mcp.tool(title="Find an area (polygon)", annotations=READ)
@_guard
def find_area(query: Annotated[str, Field(description="Area name, e.g. 'Opština Brus' or 'Lake Bled'")]) -> dict:
    """Boundary polygon (WKT) and size of a named area, for estimate_area_download / request_area_download."""
    for h in _nominatim(query, 3, polygon=True):
        geo = h.get("geojson") or {}
        if geo.get("type") in ("Polygon", "MultiPolygon"):
            wkt = _to_wkt(geo)
            km2 = sum(_area_km2(p) for p in _parse_wkt(wkt))
            return {"name": h["display_name"], "area_km2": round(km2, 1),
                    "within_download_limit": km2 <= dm.account.AREA_LIMIT_KM2, "area_wkt": wkt}
    raise ToolError(f"{query!r} has no boundary polygon in OpenStreetMap; use a bbox instead")


# --- tools: data -----------------------------------------------------------------------------------
@mcp.tool(title="Weather values for a location", annotations=READ)
@_guard
def get_weather(
    lat: Lat,
    lon: Lon,
    variables: Variables = ["tmean"],
    time_scale: Annotated[Literal["day", "mon", "ann"], Field(description="day, mon (monthly) or ann (annual)")] = "mon",
    start: Annotated[Optional[str], Field(description="First date: YYYY-MM-DD (day), YYYY-MM (mon) or YYYY (ann); from 1961")] = None,
    end: Annotated[Optional[str], Field(description="Last date, same format")] = None,
    dates: Annotated[Optional[list[str]], Field(description="Individual dates instead of a range, same format")] = None,
    confirm_credits: Annotated[bool, Field(description=f"Set true only after the user agreed to a day request over {CONFIRM_ABOVE} credits")] = False,
    save_csv: Annotated[bool, Field(description="Save the table as CSV (long series are always saved)")] = False,
) -> dict:
    """Daily, monthly or annual values for one location and one or more variables, 1961 to the present.

    Monthly and annual values are free. Daily values cost 1 credit per day and variable and need an
    account or API key in the server configuration. Results include a summary per variable; series longer
    than 400 rows are not listed but summarised by year and saved as CSV.
    """
    if dates:
        _check_dates(time_scale, dates)
        n_dates = len(dates)
    elif start and end:
        _check_dates(time_scale, [start, end])
        if time_scale == "day":
            n_dates = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            if n_dates < 1:
                raise ToolError("end is before start")
    else:
        raise ToolError("give start and end, or dates")

    key, acct = os.environ.get("DAILYMETEO_API_KEY"), None
    credits = 0
    if time_scale == "day":
        acct = _account()
        if not (key or acct):
            raise ToolError("daily values need DAILYMETEO_API_KEY, or DAILYMETEO_EMAIL and DAILYMETEO_PASSWORD, "
                            "in the MCP server configuration (https://app.dailymeteo.com/ → Account)")
        credits = n_dates * len(variables)
        if credits > CONFIRM_ABOVE and not confirm_credits:
            balance = ""
            if acct:
                balance = f" The account has {acct.credits()['credits']:,} credits left."
            raise ToolError(f"this request costs up to {credits:,} credits ({n_dates:,} days × {len(variables)} "
                            f"variable(s)).{balance} Ask the user; if they agree, call again with confirm_credits=true. "
                            "Monthly or annual values are free.")

    series = {}
    for v in dict.fromkeys(variables):
        df = dm.get_meteo(lat, lon, api_key=key if time_scale == "day" else None, account=acct, var=v,
                          agg_level="agg", time_scale=time_scale, time=dates, start=None if dates else start,
                          end=None if dates else end)
        series[v] = df.set_index("timestamp")["value"]
    wide = pd.DataFrame(series)
    wide.index.name = "timestamp"

    out = {"location": {"lat": lat, "lon": lon}, "time_scale": time_scale,
           "units": {v: UNITS[v] for v in series},
           "summary": {v: _summary(wide[v], v, time_scale) for v in series},
           "app_link": app_link(lat, lon, variables[0], time_scale, wide.index[0], wide.index[-1]) if len(wide) else None}
    if time_scale == "day":
        out["credits_charged_at_most"] = credits
    if len(wide) <= MAX_LISTED_ROWS:
        out["values"] = [{"timestamp": t, **{v: (None if pd.isna(x) else float(x)) for v, x in row.items()}}
                         for t, row in wide.iterrows()]
    else:
        out["values"] = f"{len(wide):,} rows — see yearly and the CSV file"
        out["yearly"] = _yearly(wide)
    if save_csv or len(wide) > MAX_LISTED_ROWS:
        out["csv"] = _save_csv(wide.reset_index(), f"{'_'.join(series)}_{time_scale}_{wide.index[0]}_{wide.index[-1]}_{lat}_{lon}")
    return out


@mcp.tool(title="Climate normals 1961-1990 vs 1991-2020", annotations=READ)
@_guard
def get_climate_normals(
    lat: Lat,
    lon: Lon,
    variables: Variables = ["tmean"],
    time_scale: Annotated[Literal["ann", "mon", "day"], Field(description="ann (year), mon (by month) or day (one calendar day)")] = "mon",
    month: Annotated[Optional[int], Field(ge=1, le=12, description="Only this month (mon), or the month of the day (day)")] = None,
    day: Annotated[Optional[int], Field(ge=1, le=31, description="Day of month, required for time_scale=day")] = None,
) -> dict:
    """Climate normals for 1961-1990 and 1991-2020 and the change (newer minus older). Free.

    Without `month`, time_scale=mon returns all 12 months. Annual precipitation normals are yearly totals.
    """
    if time_scale == "day":
        if not (month and day):
            raise ToolError("time_scale=day needs both month and day")
        date(2000, month, day)  # validates the calendar day (2000 is a leap year)
    result = {}
    for v in dict.fromkeys(variables):
        if time_scale == "ann":
            # one call per period: the API rejects both periods in one request
            frames = [dm.get_meteo(lat, lon, var=v, agg_level="ltm", time_scale="ann", time=y) for y in ("1961", "1991")]
            keys = [""]
        elif time_scale == "mon":
            months = [month] if month else list(range(1, 13))
            frames = [dm.get_meteo(lat, lon, var=v, agg_level="ltm", time_scale="mon", time=[f"{m:02d}" for m in months])]
            keys = [f"{m:02d}" for m in months]
        else:
            frames = [dm.get_meteo(lat, lon, var=v, agg_level="ltm", time_scale="day", time=f"{month:02d}-{day:02d}")]
            keys = [f"{day:02d}.{month:02d}"]
        values = {}
        for df in frames:
            for t, x in zip(df.timestamp, df.value):
                k, _, period = t.rpartition(".") if "." in t else ("", "", t)
                values[(k, period)] = None if pd.isna(x) else round(float(x), 1)
        rows = []
        for k in keys:
            old, new = values.get((k, PERIODS[0])), values.get((k, PERIODS[1]))
            rows.append({"period_of_year": k or "year", PERIODS[0]: old, PERIODS[1]: new,
                         "change": None if old is None or new is None else round(new - old, 1)})
        result[v] = {"unit": UNITS[v], "normals": rows}
    return {"location": {"lat": lat, "lon": lon}, "variables": result}


# --- tools: account and orders ---------------------------------------------------------------------
@mcp.tool(title="DailyMeteo account and credits", annotations=READ)
@_guard
def account_status() -> dict:
    """Plan and remaining credits: API credits (daily point and area data) and bulk credits (point history)."""
    a = _require_account()
    return {"account": a.email, **a.credits()}


@mcp.tool(title="Order full point history (email)", annotations=ORDER)
@_guard
def request_point_history(
    lat: Lat,
    lon: Lon,
    start: Annotated[Optional[Day], Field(description="First day YYYY-MM-DD; default the start of the record (1961)")] = None,
    end: Annotated[Optional[Day], Field(description="Last day YYYY-MM-DD; default the latest available day")] = None,
) -> dict:
    """Every variable, daily, for one location — by default the whole record since 1961 — as CSV by email.

    Costs one bulk credit (bulk credits are separate from API credits). Preparing the file takes minutes.
    """
    a = _require_account()
    msg = a.bulk_download(lat, lon, start=start, end=end)
    return {"status": msg, "email": a.email, "bulk_credits_left": a.credits()["bulk_credits"]}


@mcp.tool(title="Estimate area download cost", annotations=READ)
@_guard
def estimate_area_download(
    variables: Annotated[list[Literal["tmean", "tmax", "tmin", "prcp", "slp"]], Field(min_length=1)],
    start: Day,
    end: Day,
    area_wkt: Annotated[Optional[str], Field(description="Polygon in WKT, lon lat (from find_area)")] = None,
    bbox: Annotated[Optional[list[float]], Field(min_length=4, max_length=4, description="[west, south, east, north]")] = None,
) -> dict:
    """Credit cost of daily rasters clipped to an area (max 3,000 km²), and the account balance."""
    a = _require_account()
    wkt, km2 = _area_geometry(area_wkt, bbox)
    cost = a.estimate_area(wkt, variables, start, end)
    return {"area_km2": round(km2, 1), "cost_credits": cost, "credits_left": a.credits()["credits"]}


@mcp.tool(title="Order area download (email)", annotations=ORDER)
@_guard
def request_area_download(
    variables: Annotated[list[Literal["tmean", "tmax", "tmin", "prcp", "slp"]], Field(min_length=1)],
    start: Day,
    end: Day,
    area_wkt: Annotated[Optional[str], Field(description="Polygon in WKT, lon lat (from find_area)")] = None,
    bbox: Annotated[Optional[list[float]], Field(min_length=4, max_length=4, description="[west, south, east, north]")] = None,
) -> dict:
    """Daily GeoTIFF rasters clipped to an area (max 3,000 km²), prepared on the server and emailed.

    Spends API credits: run estimate_area_download first and get the user's agreement to the cost.
    """
    a = _require_account()
    wkt, km2 = _area_geometry(area_wkt, bbox)
    msg = a.area_download(wkt, variables, start, end)
    return {"status": msg, "email": a.email, "area_km2": round(km2, 1), "credits_left": a.credits()["credits"]}


# --- tools: app link -------------------------------------------------------------------------------
@mcp.tool(title="Open in the DailyMeteo app", annotations=READ)
def app_link(
    lat: Lat,
    lon: Lon,
    variable: Var = "tmean",
    time_scale: Literal["day", "mon", "ann"] = "ann",
    start: Annotated[str, Field(description="YYYY-MM-DD, YYYY-MM or YYYY to match time_scale")] = "1961",
    end: Annotated[Optional[str], Field(description="Same format; default the current year")] = None,
) -> str:
    """Link that opens the location, variable and period on the DailyMeteo map with its chart and CSV export."""
    params = {"var": variable, "zoom": "8.00", "time_scale": time_scale, "from": start,
              "to": end or str(date.today().year), "lon": f"{lon:.4f}", "lat": f"{lat:.4f}", "basemap": "satellite"}
    return f"{APP_URL}/explore?{urlencode(params)}"


# --- tools: MeteoEurope1km grids on Zenodo ---------------------------------------------------------
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
    """MeteoEurope1km archives on Zenodo (Europe, 1 km, 1961-2020, Cloud-Optimized GeoTIFF), free.

    Rasters are Equi7 Europe (EPSG:27704), Int16 in tenths of the unit (°C, mm, hPa), NoData -9999.
    """
    t = meu.files(var=variable, product=product, years=years, period=period)
    return {"files": [{"file": r.file, "size_mb": round(r.size / 1e6), "zenodo_record": f"https://doi.org/{r.doi}"} for r in t.itertuples()],
            "total_gb": round(float(t["size"].sum()) / 1e9, 2), "citation": CITATION}


@mcp.tool(title="Download MeteoEurope1km grid archives", annotations=WRITES)
@_guard
def download_gridded_files(
    variable: GridVariable,
    product: Product = "day",
    years: Years = None,
    period: Period = None,
    dest_dir: Annotated[Optional[str], Field(description="Folder; default <output dir>/meteoeurope1km")] = None,
    unzip: bool = False,
) -> dict:
    """Download MeteoEurope1km archives (1-3.5 GB per year of daily data), verify MD5, optionally unzip.

    Interrupted downloads resume. Tell the user the total size (list_gridded_files) before large downloads.
    """
    dest = Path(dest_dir) if dest_dir else _output_dir() / "meteoeurope1km"
    out = meu.download(var=variable, product=product, years=years, period=period, dest_dir=dest, unzip=unzip, progress=False)
    return {"folder": str(dest.resolve()), "files": out.path.tolist(),
            "total_gb": round(float(out["size"].sum()) / 1e9, 2), "citation": CITATION}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
