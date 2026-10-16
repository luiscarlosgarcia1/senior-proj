# The RGV Flood Impact Visualizer as one image: the FastAPI app, its built
# front-end assets, the live-alert pollers and the database.
#
# Build from the repository root after pipeline/build_all.py has made
# data/generated/rgv-flood.sqlite3 (GitHub Actions does both; see release.yml):
#   docker build -f deploy/Dockerfile -t rgv-flood .

ARG PYTHON=3.13-slim
ARG UV=ghcr.io/astral-sh/uv:0.9.25

FROM ${UV} AS uv

# ---- stage 1: front-end assets (pinned vendor files, compiled Tailwind) -------
FROM python:${PYTHON} AS assets
COPY --from=uv /uv /bin/uv
ENV UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --group dev
COPY src ./src
RUN uv sync --frozen --group dev \
 && uv run --frozen python -c "from rgv_flood import assets, vendor; vendor.fetch_all(); assets.build_css()"

# ---- stage 2: runtime ---------------------------------------------------------
FROM python:${PYTHON} AS runtime
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
# The live-alert pollers the scheduler runs (src/rgv_flood/live_signals_scheduler.py
# looks for them in pipeline/ next to src/), and the modules they import.
COPY pipeline/run_nws.py pipeline/run_drivetexas.py pipeline/run_hidalgo_rss.py \
     pipeline/nws.py pipeline/drivetexas.py pipeline/hidalgo_rss.py \
     pipeline/live_signals.py pipeline/database.py pipeline/jsonio.py pipeline/net.py pipeline/paths.py \
     ./pipeline/
COPY --from=assets /app/src/rgv_flood/static/css/site.css ./src/rgv_flood/static/css/site.css
COPY --from=assets /app/src/rgv_flood/static/vendor ./src/rgv_flood/static/vendor
COPY --from=assets /app/src/rgv_flood/static/fonts ./src/rgv_flood/static/fonts
COPY data/generated/rgv-flood.sqlite3 /data/rgv-flood.sqlite3

RUN useradd --create-home --uid 10001 app && chown -R app /data
USER app
ENV PATH="/app/.venv/bin:${PATH}" RGV_DATABASE=/data/rgv-flood.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status != 200)"
CMD ["uvicorn", "rgv_flood.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "*"]
