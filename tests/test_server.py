import asyncio
import json
import sys
from unittest import mock

import pandas as pd
import pytest

from dailymeteo_mcp import server as s


def df(rows):
    return pd.DataFrame(rows, columns=["timestamp", "value"])


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(s.mcp.list_tools())}
    assert names == {"find_location", "get_monthly_or_annual", "get_climate_normals", "get_daily_values",
                     "list_gridded_files", "download_gridded_files"}


def test_normals_monthly_parsing_and_difference():
    fake = df([["01.1961-1990", 3.1], ["07.1961-1990", 27.1], ["01.1991-2020", 4.7], ["07.1991-2020", 29.1]])
    with mock.patch.object(s.dm, "get_meteo", return_value=fake) as g:
        out = s.get_climate_normals(44.8, 20.46, "tmax", "mon")
    assert g.call_args.kwargs["time"] == [f"{m:02d}" for m in range(1, 13)]
    jul = next(r for r in out["normals"] if r["period_of_year"] == "07")
    assert jul == {"period_of_year": "07", "1961-1990": 27.1, "1991-2020": 29.1, "difference": 2.0}
    assert len(out["normals"]) == 12


def test_normals_annual_asks_each_period_separately():
    with mock.patch.object(s.dm, "get_meteo", side_effect=[df([["1961-1990", 16.4]]), df([["1991-2020", 17.6]])]) as g:
        out = s.get_climate_normals(44.8, 20.46, "tmax", "ann")
    assert [c.kwargs["time"] for c in g.call_args_list] == ["1961", "1991"]
    assert out["normals"] == [{"period_of_year": "year", "1961-1990": 16.4, "1991-2020": 17.6, "difference": 1.2}]


def test_normals_day():
    fake = df([["25.07.1961-1990", 27.7], ["25.07.1991-2020", 29.2]])
    with mock.patch.object(s.dm, "get_meteo", return_value=fake):
        out = s.get_climate_normals(44.8, 20.46, "tmax", "day", month=7, day=25)
    assert out["normals"][0]["difference"] == 1.5
    with pytest.raises(s.ToolError, match="day is out of range"):
        s.get_climate_normals(44.8, 20.46, "tmax", "day", month=2, day=30)


def test_daily_refuses_without_confirmation_and_without_key(monkeypatch):
    with pytest.raises(s.ToolError, match="365 credits"):
        s.get_daily_values(44.8, 20.46, "tmean", "2020-01-01", "2020-12-30")
    monkeypatch.delenv("DAILYMETEO_API_KEY", raising=False)
    with pytest.raises(s.ToolError, match="DAILYMETEO_API_KEY"):
        s.get_daily_values(44.8, 20.46, "tmean", "2020-01-01", "2020-01-05")


def test_series_summary_trend_and_nodata():
    fake = df([[str(y), 10 + 0.05 * (y - 1961)] for y in range(1961, 2021)])
    with mock.patch.object(s.dm, "get_meteo", return_value=fake):
        out = s.get_monthly_or_annual(44.8, 20.46, "tmean", "ann", "1961", "2020")
    assert out["summary"]["linear_trend_per_decade"] == 0.5
    with mock.patch.object(s.dm, "get_meteo", return_value=df([["2020", float("nan")]])):
        out = s.get_monthly_or_annual(40, -35, "tmean", "ann", "2020", "2020")
    assert "no data" in out["summary"]["note"] and out["values"][0]["value"] is None
    with pytest.raises(s.ToolError, match="YYYY-MM"):
        s.get_monthly_or_annual(44.8, 20.46, "tmean", "mon", "2020", "2020-05")


@pytest.mark.network
def test_live_free_tools():
    loc = s.find_location("Belgrade, Serbia")[0]
    out = s.get_monthly_or_annual(loc["lat"], loc["lon"], "prcp", "ann", "1961", "2020")
    assert out["summary"]["count"] == 60 and "linear_trend_per_decade" in out["summary"]
    n = s.get_climate_normals(loc["lat"], loc["lon"], "tmax", "mon")["normals"]
    assert len(n) == 12 and all(r["difference"] is not None for r in n)
    sea = s.get_monthly_or_annual(40, -35, "tmean", "ann", "2020", "2020")
    assert "no data" in sea["summary"]["note"]
    files = s.list_gridded_files("slp", "day", years=[2020])
    assert files["files"][0]["file"] == "slp_2020_equi7.zip"


@pytest.mark.network
def test_stdio_end_to_end():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "dailymeteo_mcp"])
        async with stdio_client(params) as (r, w), ClientSession(r, w) as c:
            init = await c.initialize()
            assert "DailyMeteo" in (init.instructions or "")
            res = await c.call_tool("get_climate_normals", {"lat": 44.8, "lon": 20.46, "variable": "tmax", "time_scale": "ann"})
            assert not res.is_error, res.content
            bad = await c.call_tool("get_daily_values", {"lat": 44.8, "lon": 20.46, "variable": "tmean",
                                                         "start": "2020-01-01", "end": "2020-12-31"})
            assert bad.is_error and "366 credits" in bad.content[0].text
            return json.loads(res.content[0].text)

    out = asyncio.run(run())
    assert out["normals"][0]["difference"] > 0
