# docker build -t dailymeteo-mcp .
# docker run -i --rm -e DAILYMETEO_API_KEY -v "$HOME/dailymeteo:/data" dailymeteo-mcp
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DAILYMETEO_OUTPUT_DIR=/data
COPY . /src
RUN pip install --no-cache-dir --root-user-action=ignore /src && rm -rf /src
VOLUME /data
ENTRYPOINT ["dailymeteo-mcp"]
