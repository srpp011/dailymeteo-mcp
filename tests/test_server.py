import asyncio
import json
import sys
from unittest import mock

import pandas as pd
import pytest

from dailymeteo_mcp import server as s


def df(rows):
    return pd.DataFrame(rows, columns=["timestamp", "value"])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for k in ("DAILYMETEO_API_KEY", "DAILYMETEO_EMAIL", "DAILYMETEO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DAILYMETEO_OUTPUT_DIR", str(tmp_path))
    s._account.cache_clear()


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(s.mcp.list_tools())}
    assert names == {"find_location", "find_area", "get_weather", "get_climate_normals", "account_status",
                     "request_point_history", "estimate_area_download", "request_area_download", "app_link",
                     "list_gridded_files", "download_gridded_files"}


# --- normals ---
def test_normals_monthly_two_variables():
    fake = df([["01.1961-1990", 3.1], ["07.1961-1990", 27.1], ["01.1991-2020", 4.7], ["07.1991-2020", 29.1]])
    with mock.patch.object(s.dm, "get_meteo", return_value=fake) as g:
        out = s.get_climate_normals(44.8, 20.46, ["tmax", "tmin"], "mon")
    assert g.call_count == 2 and g.call_args.kwargs["time"] == [f"{m:02d}" for m in range(1, 13)]
    jul = next(r for r in out["variables"]["tmax"]["normals"] if r["period_of_year"] == "07")
    assert jul == {"period_of_year": "07", "1961-1990": 27.1, "1991-2020": 29.1, "change": 2.0}


def test_normals_annual_one_call_per_period():
    with mock.patch.object(s.dm, "get_meteo", side_effect=[df([["1961-1990", 16.4]]), df([["1991-2020", 17.6]])]) as g:
        out = s.get_climate_normals(44.8, 20.46, ["tmax"], "ann")
    assert [c.kwargs["time"] for c in g.call_args_list] == ["1961", "1991"]
    assert out["variables"]["tmax"]["normals"][0]["change"] == 1.2


def test_normals_bad_day():
    with pytest.raises(s.ToolError, match="day is out of range"):
        s.get_climate_normals(44.8, 20.46, ["tmax"], "day", month=2, day=30)


# --- weather ---
def test_monthly_two_variables_are_free_and_merged():
    t = df([["2020-01", 1.7], ["2020-02", 7.5]])
    p = df([["2020-01", 20.0], ["2020-02", 35.5]])
    with mock.patch.object(s.dm, "get_meteo", side_effect=[t, p]) as g:
        out = s.get_weather(44.8, 20.46, ["tmean", "prcp"], "mon", "2020-01", "2020-02")
    assert all(c.kwargs["api_key"] is None and c.kwargs["account"] is None for c in g.call_args_list)
    assert out["values"] == [{"timestamp": "2020-01", "tmean": 1.7, "prcp": 20.0}, {"timestamp": "2020-02", "tmean": 7.5, "prcp": 35.5}]
    assert out["summary"]["prcp"]["total"] == 55.5
    assert out["app_link"].startswith("https://dailymeteo.com/explore?var=tmean")


def test_daily_needs_credentials():
    with pytest.raises(s.ToolError, match="DAILYMETEO_API_KEY"):
        s.get_weather(44.8, 20.46, ["tmean"], "day", "2020-01-01", "2020-01-05")


def test_daily_over_1000_credits_needs_confirmation(monkeypatch):
    monkeypatch.setenv("DAILYMETEO_API_KEY", "k")
    with pytest.raises(s.ToolError, match="1,462 credits"):
        s.get_weather(44.8, 20.46, ["tmean", "prcp"], "day", "2019-01-01", "2020-12-31")
    days = pd.date_range("2020-01-01", "2021-12-31").strftime("%Y-%m-%d")
    fake = df([[d, 1.0] for d in days])
    with mock.patch.object(s.dm, "get_meteo", return_value=fake):
        out = s.get_weather(44.8, 20.46, ["prcp"], "day", "2020-01-01", "2021-12-31", confirm_credits=True)
    assert out["credits_charged_at_most"] == 731
    assert isinstance(out["values"], str) and [y["year"] for y in out["yearly"]] == ["2020", "2021"]
    assert out["yearly"][0]["prcp"] == 366.0 and out["yearly"][0]["n"] == 366
    assert pd.read_csv(out["csv"]).shape == (731, 2)


def test_daily_with_account_and_no_key(monkeypatch):
    monkeypatch.setenv("DAILYMETEO_EMAIL", "a@b.c")
    monkeypatch.setenv("DAILYMETEO_PASSWORD", "pw")
    with mock.patch.object(s.dm, "get_meteo", return_value=df([["2020-01-01", 1.0]])) as g:
        s.get_weather(44.8, 20.46, ["tmean"], "day", "2020-01-01", "2020-01-01")
    assert isinstance(g.call_args.kwargs["account"], s.dm.Account) and g.call_args.kwargs["api_key"] is None


def test_annual_trend_and_nodata():
    fake = df([[str(y), 10 + 0.05 * (y - 1961)] for y in range(1961, 2021)])
    with mock.patch.object(s.dm, "get_meteo", return_value=fake):
        out = s.get_weather(44.8, 20.46, ["tmean"], "ann", "1961", "2020")
    assert out["summary"]["tmean"]["linear_trend_per_decade"] == 0.5
    with mock.patch.object(s.dm, "get_meteo", return_value=df([["2020", float("nan")]])):
        out = s.get_weather(40, -35, ["tmean"], "ann", "2020", "2020")
    assert "no data" in out["summary"]["tmean"]["note"] and out["values"][0]["tmean"] is None


# --- areas ---
def test_area_math_and_limit():
    one_degree = s._parse_wkt("POLYGON((0 0,1 0,1 1,0 1,0 0))")
    assert abs(s._area_km2(one_degree[0]) - 12364) < 30
    holed = s._parse_wkt("POLYGON((0 0,1 0,1 1,0 1,0 0),(0.2 0.2,0.4 0.2,0.4 0.4,0.2 0.4,0.2 0.2))")
    assert s._area_km2(holed[0]) < s._area_km2(one_degree[0])
    multi = s._parse_wkt("MULTIPOLYGON(((0 0,0.1 0,0.1 0.1,0 0)),((1 1,1.1 1,1.1 1.1,1 1)))")
    assert len(multi) == 2
    wkt, km2 = s._area_geometry(None, [20.0, 44.0, 20.3, 44.3])
    assert wkt.startswith("POLYGON((20.0 44.0") and 780 < km2 < 820
    with pytest.raises(s.ToolError, match="3,000 km"):
        s._area_geometry("POLYGON((0 0,1 0,1 1,0 1,0 0))", None)


def test_area_tools_use_account(monkeypatch):
    monkeypatch.setenv("DAILYMETEO_EMAIL", "a@b.c")
    monkeypatch.setenv("DAILYMETEO_PASSWORD", "pw")
    with mock.patch.object(s.dm.Account, "estimate_area", return_value=552) as est, \
         mock.patch.object(s.dm.Account, "credits", return_value={"credits": 9000, "bulk_credits": 2}):
        out = s.estimate_area_download(["tmax"], "2020-01-01", "2020-01-31", bbox=[20.0, 44.0, 20.3, 44.3])
    assert out["cost_credits"] == 552 and out["credits_left"] == 9000
    assert est.call_args.args[1:] == (["tmax"], "2020-01-01", "2020-01-31")


def test_account_tools_need_credentials():
    with pytest.raises(s.ToolError, match="DAILYMETEO_EMAIL"):
        s.account_status()


def test_find_area_converts_geojson():
    hit = {"display_name": "Test area", "geojson": {"type": "Polygon", "coordinates": [[[20, 44], [20.1, 44], [20.1, 44.1], [20, 44]]]}}
    with mock.patch.object(s, "_nominatim", return_value=[{"display_name": "point", "geojson": {"type": "Point"}}, hit]):
        out = s.find_area("x")
    assert out["name"] == "Test area" and out["within_download_limit"] and out["area_wkt"].startswith("POLYGON((20.00000 44.00000")


def test_app_link():
    url = s.app_link(44.8153, 20.4457, "tmax", "mon", "2020-01", "2020-12")
    assert url == ("https://dailymeteo.com/explore?var=tmax&zoom=8.00&time_scale=mon&from=2020-01&to=2020-12"
                   "&lon=20.4457&lat=44.8153&basemap=satellite")


# --- live ---
@pytest.mark.network
def test_live_free_tools():
    loc = s.find_location("Belgrade, Serbia")[0]
    out = s.get_weather(loc["lat"], loc["lon"], ["prcp", "tmax"], "ann", "1961", "2025")
    assert out["summary"]["prcp"]["count"] >= 64 and "linear_trend_per_decade" in out["summary"]["tmax"]
    m = s.get_weather(loc["lat"], loc["lon"], ["tmean"], "mon", "1961-01", "2025-12")
    assert isinstance(m["values"], str) and len(m["yearly"]) >= 64
    n = s.get_climate_normals(loc["lat"], loc["lon"], ["tmax", "prcp"], "mon")["variables"]
    assert all(r["change"] is not None for r in n["tmax"]["normals"])
    area = s.find_area("Opština Brus, Srbija")
    assert area["within_download_limit"] and 500 < area["area_km2"] < 800
    assert s.list_gridded_files("slp", "day", years=[2020])["files"][0]["file"] == "slp_2020_equi7.zip"


@pytest.mark.network
def test_stdio_end_to_end():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "dailymeteo_mcp"])
        async with stdio_client(params) as (r, w), ClientSession(r, w) as c:
            init = await c.initialize()
            assert "DailyMeteo" in (init.instructions or "")
            res = await c.call_tool("get_climate_normals", {"lat": 44.8, "lon": 20.46, "variables": ["tmax"], "time_scale": "ann"})
            assert not res.is_error, res.content
            bad = await c.call_tool("get_weather", {"lat": 44.8, "lon": 20.46, "time_scale": "day",
                                                    "start": "2020-01-01", "end": "2020-12-31"})
            assert bad.is_error and "DAILYMETEO_API_KEY" in bad.content[0].text
            return json.loads(res.content[0].text)

    out = asyncio.run(run())
    assert out["variables"]["tmax"]["normals"][0]["change"] > 0


def test_blank_plugin_settings_mean_no_account(monkeypatch):
    monkeypatch.setenv("DAILYMETEO_EMAIL", "${user_config.dailymeteo_email}")
    monkeypatch.setenv("DAILYMETEO_PASSWORD", "")
    assert s._account() is None
    with pytest.raises(s.ToolError, match="DAILYMETEO_EMAIL"):
        s.account_status()


def test_version_flag(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dailymeteo-mcp", "--version"])
    s.main()
    assert capsys.readouterr().out.strip() == f"dailymeteo-mcp {s.__version__}"
