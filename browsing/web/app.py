"""Starlette demo: immutable synthetic input, fixed policies, bounded real execution."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from browsing import providers
from browsing.web.korea_quote import quote_request
from browsing.agent import run_agent
from browsing.mandate import DEFAULT_BASE_PATH, load_mandate
from browsing.persona.generate import DEFAULT_SCENARIO, detector_window, load_scenario, populate
from browsing.signals import detect_all
from browsing.trace import Tracer, disable_external_tracing
from browsing.web.store import RunStore

ROOT = Path(__file__).parent
PROFILES = {"public": DEFAULT_BASE_PATH,
            "no-search": ROOT / "profiles" / "no-search.toml",
            "confirm-research": ROOT / "profiles" / "confirm-research.toml"}
LABELS = {"public": "Public default", "no-search": "Search disabled",
          "confirm-research": "Confirm research first"}


def load_dataset(db_path: Path | None):
    if db_path is None:
        source = (ROOT / "fixtures" / "visits.json").read_bytes()
        scenario = load_scenario(DEFAULT_SCENARIO)
        with closing(sqlite3.connect(":memory:")) as conn:
            signals = populate(conn, json.loads(source), scenario)
        return hashlib.sha256(source).hexdigest(), scenario, signals
    # Require an explicit synthetic bundle. Never probe a local browser/data directory.
    db_path = Path(db_path).resolve(strict=True)
    manifest = json.loads(db_path.with_suffix(db_path.suffix + ".json").read_text())
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    if manifest.get("synthetic") is not True or manifest.get("sha256") != digest:
        raise ValueError("A matching validated synthetic manifest is required")
    scenario = manifest["scenario"]
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as conn:
        signals = detect_all(conn, **detector_window(scenario), profile="synthetic")
    if sorted(s.key for s in signals) != sorted(manifest["signal_keys"]):
        raise ValueError("Synthetic bundle signal validation mismatch")
    return digest, scenario, signals


def execute(signals, profile, trace_path, *, llm=None, search=None, quote_client=None, destination="US"):
    disable_external_tracing()
    tracer = Tracer(path=trace_path)
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = run_agent(None, signals=signals,
                           llm=providers.get_llm() if llm is None else llm,
                           search=providers.get_search() if search is None else search,
                           max_signals=20, mandate_path=PROFILES[profile],
                           mandate_local_path=None, tracer=tracer, quote_client=quote_client, destination=destination)
    finally:
        tracer.close()
    return {"profile": profile, "mandate_digest": load_mandate(PROFILES[profile], None).digest,
            "created_at": started, "source": "live", "status": "failed" if result.errors else "complete",
            "result": asdict(result), "trace": Path(trace_path).read_text()}


def create_app(*, db_path=None, state_dir=None, daily_limit=None, runner=execute, cache_path=None):
    disable_external_tracing()
    configured_db = db_path or os.getenv("DEMO_DB")
    dataset, scenario, signals = load_dataset(Path(configured_db) if configured_db else None)
    store = RunStore(Path(state_dir or os.getenv("DEMO_STATE_DIR", ".demo-state")),
                     int(os.getenv("DEMO_DAILY_LIMIT", "20")) if daily_limit is None else daily_limit)
    templates = Jinja2Templates(directory=ROOT / "templates")
    configured_cache = cache_path or os.getenv("DEMO_CACHE")
    seed = json.loads(Path(configured_cache or ROOT / "fixtures" / "cache.json").read_text())
    if configured_cache and seed["dataset"] != dataset:
        raise ValueError("Precomputed cache does not match the synthetic dataset")

    def cached(profile):
        saved = store.get(dataset, profile)
        if saved is not None:
            return saved
        if seed["dataset"] == dataset:
            candidate = seed["profiles"].get(profile)
            if candidate and candidate["mandate_digest"] == load_mandate(PROFILES[profile], None).digest:
                return candidate
        return None

    def render(request, profile, *, snapshot=None, mode="cached", notice="", status=200):
        mandate = load_mandate(PROFILES[profile], None)
        snapshot = cached(profile) if snapshot is None else snapshot
        decisions = {} if snapshot is None else {d["signal_key"]: d for d in snapshot["result"]["decisions"]}
        actions = {} if snapshot is None else {a["signal_key"]: a for a in snapshot["result"]["actions"]}
        csrf = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(request=request, name="index.html", context={
            "signals": signals, "scenario": scenario, "profiles": LABELS, "profile": profile,
            "mandate": mandate, "mandate_text": PROFILES[profile].read_text(),
            "snapshot": snapshot, "decisions": decisions, "actions": actions, "mode": mode,
            "notice": notice, "csrf": csrf, "daily_limit": store.daily_limit,
            "quote_requests": {s.key: quote_request(s.term) for s in signals if s.kind == "korea_product"},
        }, status_code=status)
        response.set_cookie("demo_csrf", csrf, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def home(request: Request):
        profile = request.query_params.get("profile", "public")
        if profile not in PROFILES:
            return PlainTextResponse("Unknown mandate profile", status_code=400)
        return render(request, profile)

    def run(profile):
        with store.reserve() as permission:
            if permission != "allowed":
                return permission, None
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            trace = store.directory / f"trace-{stamp}-{uuid4().hex}.jsonl"
            try:
                snapshot = runner(signals, profile, trace)
            except Exception as exc:
                # An explicit failed request, not a synthetic successful result or SKIP.
                return "error:" + type(exc).__name__, None
            if snapshot["status"] == "complete":
                store.save(dataset, profile, snapshot)
            return "ran", snapshot

    async def run_request(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            return PlainTextResponse("Expected a form", status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024:
                return PlainTextResponse("Form too large", status_code=413)
        try:
            form = parse_qs(body.decode("utf-8"), strict_parsing=True)
        except (UnicodeDecodeError, ValueError):
            return PlainTextResponse("Invalid form", status_code=400)
        if set(form) != {"profile", "csrf"} or any(len(v) != 1 for v in form.values()):
            return PlainTextResponse("Invalid form fields", status_code=400)
        profile, token = form["profile"][0], form["csrf"][0]
        if profile not in PROFILES:
            return PlainTextResponse("Unknown mandate profile", status_code=400)
        cookie = request.cookies.get("demo_csrf", "")
        if not cookie or not hmac.compare_digest(token.encode(), cookie.encode()):
            return PlainTextResponse("Reload the page before running", status_code=403)
        status, snapshot = await run_in_threadpool(run, profile)
        if status == "ran":
            failed = snapshot["status"] != "complete"
            return render(request, profile, snapshot=snapshot, mode="live",
                          notice="Live run failed; errors below. Last successful cache was preserved." if failed else "Live run completed.",
                          status=502 if failed else 200)
        notices = {"busy": "Another run is active. Showing cached results; no new calls were made.",
                   "limit": "Daily server limit reached. Showing cached results; no new calls were made."}
        return render(request, profile, snapshot=store.latest(dataset),
                      notice=notices.get(status, "Live run failed (" + status + "). Showing cached results."),
                      status=502 if status.startswith("error:") else 200)

    async def health(request):
        return JSONResponse({"status": "ok", "dataset": "synthetic"})

    app = Starlette(routes=[Route("/", home), Route("/run", run_request, methods=["POST"]),
                           Route("/healthz", health)])
    app.state.store = store
    app.state.dataset = dataset
    return app
