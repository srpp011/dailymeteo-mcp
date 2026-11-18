# Local (stdio):
#   docker build -t dailymeteo-mcp .
#   docker run -i --rm -e DAILYMETEO_API_KEY -v "$HOME/dailymeteo:/data" dailymeteo-mcp
# Hosted (streamable HTTP on :8000, see README "Running the hosted mode yourself"):
#   docker run -d -p 8000:8000 -e DAILYMETEO_MCP_REMOTE=1 -e DAILYMETEO_MCP_PUBLIC_URL=https://mcp.example.org dailymeteo-mcp
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DAILYMETEO_OUTPUT_DIR=/data
COPY . /src
RUN pip install --no-cache-dir --root-user-action=ignore /src && rm -rf /src \
    && useradd --system --uid 10001 --home-dir /data app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,sys,urllib.request; os.environ.get('DAILYMETEO_MCP_REMOTE')=='1' or sys.exit(0); urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('DAILYMETEO_MCP_PORT','8000')+'/health', timeout=4)"
ENTRYPOINT ["dailymeteo-mcp"]
