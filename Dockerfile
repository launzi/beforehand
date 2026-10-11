FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DEMO_DB=/app/synthetic/browsing.db DEMO_STATE_DIR=/state
WORKDIR /app
COPY browsing/web/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && groupadd --gid 10001 demo && useradd --uid 10001 --gid demo --no-create-home demo \
    && mkdir -p /state /app/synthetic && chown demo:demo /state
COPY browsing/agent.py browsing/providers.py browsing/trace.py browsing/signals.py browsing/mandate.py browsing/mandate.toml browsing/ingest.py browsing/scrub.py /app/browsing/
COPY browsing/persona /app/browsing/persona
COPY browsing/web /app/browsing/web
# Required: reviewed output of persona generate (plus its adjacent .json manifest).
# .dockerignore allows DBs only under browsing/demo-assets/.
ARG SYNTHETIC_DB=browsing/demo-assets/browsing.db
COPY ${SYNTHETIC_DB} /app/synthetic/browsing.db
COPY ${SYNTHETIC_DB}.json /app/synthetic/browsing.db.json
# Optional: exported cache of successful live runs for this exact DB (python -m browsing.web export-cache).
# Lets the full walkthrough render during provider outages. Empty default keeps the built-in fixture.
ARG DEMO_CACHE_FILE=
COPY ${DEMO_CACHE_FILE:-browsing/web/fixtures/cache.json} /app/cache/precomputed.json
ENV DEMO_CACHE=/app/cache/precomputed.json
RUN python -c "from pathlib import Path; from browsing.web.app import load_dataset; load_dataset(Path('/app/synthetic/browsing.db'))"
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["uvicorn", "browsing.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
