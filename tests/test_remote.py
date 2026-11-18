"""Remote (shared HTTP) mode: no server-side account, the user's key from request headers, CSV links."""
import asyncio
import importlib
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest
from starlette.testclient import TestClient

from dailymeteo_mcp import server


@pytest.fixture
def remote(monkeypatch, tmp_path):
    for k in ("DAILYMETEO_EMAIL", "DAILYMETEO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DAILYMETEO_API_KEY", "server-key-must-not-be-used")
    monkeypatch.setenv("DAILYMETEO_MCP_REMOTE", "1")
    monkeypatch.setenv("DAILYMETEO_MCP_PUBLIC_URL", "https://mcp.example.org")
    monkeypatch.setenv("DAILYMETEO_OUTPUT_DIR", str(tmp_path))
    s = importlib.reload(server)
    yield s
    monkeypatch.delenv("DAILYMETEO_MCP_REMOTE")
    importlib.reload(server)


def ctx(headers):
    return SimpleNamespace(headers=headers)


def days(n):
    t = pd.date_range("2020-01-01", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame({"timestamp": t, "value": range(n)})


def test_local_only_tools_are_removed(remote):
    names = {t.name for t in asyncio.run(remote.mcp.list_tools())}
    assert names == {"find_location", "find_area", "get_weather", "get_climate_normals", "app_link", "list_gridded_files"}


def test_daily_without_user_key_ignores_server_key(remote):
    with mock.patch.object(remote.dm, "get_meteo") as g, pytest.raises(remote.ToolError, match="X-DailyMeteo-Api-Key"):
        remote.get_weather(44.8, 20.46, ["tmean"], "day", "2020-01-01", "2020-01-02", ctx=ctx({}))
    g.assert_not_called()


@pytest.mark.parametrize("headers", [{"x-dailymeteo-api-key": "user-key"}, {"authorization": "Bearer user-key"}])
def test_daily_uses_key_from_headers(remote, headers):
    with mock.patch.object(remote.dm, "get_meteo", return_value=days(2)) as g:
        remote.get_weather(44.8, 20.46, ["tmean"], "day", "2020-01-01", "2020-01-02", ctx=ctx(headers))
    assert g.call_args.kwargs["api_key"] == "user-key" and g.call_args.kwargs["account"] is None


def test_unexpanded_placeholder_is_no_key(remote):
    with pytest.raises(remote.ToolError, match="API key"):
        remote.get_weather(44.8, 20.46, ["tmean"], "day", "2020-01-01", "2020-01-02",
                           ctx=ctx({"x-dailymeteo-api-key": "${user_config.dailymeteo_api_key}"}))


def test_long_series_csv_is_a_link_served_over_http(remote):
    with mock.patch.object(remote.dm, "get_meteo", return_value=days(500)):
        out = remote.get_weather(44.8, 20.46, ["tmean"], "day", "2020-01-01", "2021-05-14", ctx=ctx({"x-dailymeteo-api-key": "k"}))
    assert out["csv"].startswith("https://mcp.example.org/files/")
    path = out["csv"].removeprefix("https://mcp.example.org")
    with TestClient(remote.http_app()) as c:
        r = c.get(path)
        assert r.status_code == 200 and r.text.splitlines()[0] == "timestamp,tmean" and len(r.text.splitlines()) == 501
        assert c.get("/files/aaaaaaaaaaaaaaaaaaaaaa/x.csv").status_code == 404
        assert c.get("/files/aaaaaaaaaaaaaaaaaaaaaa/..%2F..%2Fsecret.csv").status_code == 404


def test_mcp_over_http_lists_tools_and_passes_header(remote):
    app = remote.http_app()
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        assert c.post("/mcp", json=init, headers=h).status_code == 200
        tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=h).json()
        assert "account_status" not in {t["name"] for t in tools["result"]["tools"]}
        call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "get_weather", "arguments": {"lat": 44.8, "lon": 20.46, "time_scale": "day",
                                                                "start": "2020-01-01", "end": "2020-01-02"}}}
        with mock.patch.object(remote.dm, "get_meteo", return_value=days(2)) as g:
            r = c.post("/mcp", json=call, headers=h | {"X-DailyMeteo-Api-Key": "user-key"}).json()
        assert not r["result"].get("isError"), r
        assert g.call_args.kwargs["api_key"] == "user-key"
