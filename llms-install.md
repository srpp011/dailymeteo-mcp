# Installing the DailyMeteo MCP server — instructions for AI agents

Follow these steps when a user asks you to install the DailyMeteo MCP server. The server is the PyPI package `dailymeteo-mcp`. It runs locally over stdio with `uvx --python 3.12 dailymeteo-mcp`.

## 1. Make sure `uv` is installed

Run `uv --version`. If the command is not found, install uv:

- Windows: `winget install --id astral-sh.uv -e` (or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`)
- macOS: `brew install uv` (or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

Open a new shell afterwards so that `uvx` is on the PATH. Check with `uvx --python 3.12 dailymeteo-mcp --version`, which must print a version number.

## 2. Add the server to the user's client

**Claude Code.** Install the plugin, which also teaches Claude when to use each tool:

```
claude plugin marketplace add srpp011/dailymeteo-mcp
claude plugin install dailymeteo@dailymeteo
```

If plugins are not available, use `claude mcp add dailymeteo -s user -- uvx --python 3.12 dailymeteo-mcp` instead.

**Claude Desktop.** Open the config file through Settings → Developer → Edit Config. Do not guess its path: Microsoft Store installs keep it in a different place. Add the following under `mcpServers`, keeping every other key, then quit Claude Desktop completely (tray icon → Quit) and start it again:

```json
"dailymeteo": { "command": "uvx", "args": ["--python", "3.12", "dailymeteo-mcp"], "env": {} }
```

**Cursor.** Add the same entry under `mcpServers` in `~/.cursor/mcp.json`.

**VS Code.** Run:

```
code --add-mcp '{"name":"dailymeteo","command":"uvx","args":["--python","3.12","dailymeteo-mcp"]}'
```

**Cline, Windsurf and other clients.** Add the same `command`/`args` entry to the client's MCP settings.

## 3. Account (optional)

Without an account, these work: monthly and annual values, climate normals, links to the DailyMeteo app, and the MeteoEurope1km grids. Daily values, credits, full point history and area downloads need a DailyMeteo account (sign up at https://app.dailymeteo.com/).

Ask the user whether they have an account. If they do, the server needs two variables, `DAILYMETEO_EMAIL` and `DAILYMETEO_PASSWORD`. Do not ask the user to type the password into the chat. Tell them where to enter it themselves:

- **Claude Desktop / Cursor / Cline:** in the `env` object of the entry above, e.g. `"env": {"DAILYMETEO_EMAIL": "...", "DAILYMETEO_PASSWORD": "..."}`.
- **Claude Code, VS Code:** as user environment variables, then restart the client.
  - Windows: `setx DAILYMETEO_EMAIL "..."` and `setx DAILYMETEO_PASSWORD "..."`.
  - macOS/Linux: `export ...` lines in the shell profile.

An API key (`DAILYMETEO_API_KEY`) can replace the account for daily point data only.

## 4. Verify

Restart the client. The server should expose 11 tools. Test with a free call: the climate normals for Belgrade (lat 44.82, lon 20.46), variable `tmax`, `time_scale` `ann`. It returns values for 1961–1990 and 1991–2020 and their change. If an account was configured, also call `account_status`.

## Troubleshooting

- `uvx` not found: uv is not on the PATH yet. Open a new terminal or restart the client.
- A tool says the account is missing although the variables were set: the client was started before they were set. Restart it fully. Claude Desktop does not pass user environment variables to servers, so use its `env` object.
- Daily requests over 1,000 credits ask for confirmation. This is intended and mirrors the DailyMeteo app.
