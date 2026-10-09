"""Starlette demo: immutable synthetic input, fixed policies, bounded real execution."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from markupsafe import Markup, escape

from browsing import providers
from browsing.web.korea_quote import CHECKOUT_NOTICE, DISCLOSURE, quote_request
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
LABELS = {"public": "Allow research & quotes", "no-search": "Block research & quotes",
          "confirm-research": "Hold research & quotes"}
SIGNAL_LABELS = {"dropped": "Activity went quiet", "korea_product": "Korean product interest",
                 "new_entry": "First recorded visit", "recurring": "Repeat visits",
                 "unresolved": "Search with little follow-through"}
ACTION_LABELS = {"followup_nudge": "Follow-up suggestion", "commerce.quote": "Korea price quote",
                 "setup_check": "Setup suggestion", "theme_summary": "Theme summary",
                 "research_briefing": "Research briefing"}
STATUSES = {"allowed": ("Allowed", "✓"), "blocked": ("Blocked", "✕"),
            "held": ("Held", "◐"), "skipped": ("Skipped by model", "○"),
            "failed": ("Failed", "!"),
            "pending": ("Not evaluated", "—")}


def human_date(value, *, include_time=False):
    """Format dates for display only; exact timestamps remain in the audit details."""
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "Date unavailable"
    if date.tzinfo:
        date = date.astimezone(timezone.utc)
    result = f"{date:%b} {date.day}, {date.year}"
    return result + (f", {date:%H:%M} UTC" if include_time else "")


def history_window(scenario):
    start, end = human_date(scenario.get("since")), human_date(scenario.get("until"))
    if start[-4:] == end[-4:] and start != "Date unavailable":
        start = start.rsplit(",", 1)[0]
    return f"{start} – {end}"


def number(value, decimals=2):
    try:
        amount = Decimal(str(value))
        if amount.is_finite():
            return f"{amount:,.{decimals}f}"
    except (InvalidOperation, ValueError, TypeError):
        pass
    return "Not available"


def model_text(value):
    """Escape untrusted prose; only construct HTTP(S) links, with readable labels."""
    text = str(value or "").strip()

    def prose(fragment):
        # A date inside a URL is part of the resource address, not display copy.
        return escape(re.sub(
            r"\b\d{4}[-‑]\d{2}[-‑]\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?",
            lambda m: human_date(m[0].replace("‑", "-")), fragment))

    pattern = r'\[([^\]\n]+)\]\((https?://[^\s<>"\']+)\)|https?://[^\s<>"\']+'
    parts, position = [], 0
    for match in re.finditer(pattern, text):
        parts.append(prose(text[position:match.start()]))
        url = match[2] if match[2] else match[0]
        url = url.rstrip(".,;:!?)]}")
        suffix = (match[2] if match[2] else match[0])[len(url):]
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = None
        if host:
            label = match[1] or host.removeprefix("www.")
            parts.append(Markup('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(url, label))
            parts.append(escape(suffix))
        else:
            parts.append(escape(match[0]))
        position = match.end()
    parts.append(prose(text[position:]))
    return Markup("").join(parts)


def decision_view(decision, action=None):
    """Keep the actual rule verdict separate from the model and final outcome."""
    decision, action = decision or {}, action or {}
    triage = decision.get("triage")
    verdict = (decision.get("mandate") or {}).get("verdict")
    rule_state = {
        "allow": "allowed", "deny": "blocked", "hold": "held"}.get(verdict, "pending")
    state = ("failed" if triage == "ERROR" or decision.get("execution_status") == "failed" else
             "skipped" if triage == "SKIP" else rule_state if triage == "ACT" else "pending")
    outcome = {"skipped": "Not run — skipped by the model", "blocked": "Not run — blocked by your rules",
               "held": "Not run — held by your rules"}.get(state, "No run yet")
    if triage == "ERROR":
        outcome = "Not run — model triage failed"
    elif decision.get("execution_status") == "failed":
        outcome = "Could not complete — see details"
    elif state == "allowed" and (decision.get("executed") or action):
        outcome = ("Request completed — no quote returned" if action.get("quote_unavailable") else
                   "Quote received" if action.get("quote") else
                   "Setup suggestion generated" if decision.get("signal_kind") == "new_entry" else
                   "Research briefing generated" if decision.get("signal_kind") == "unresolved" else "Done")
    label, symbol = STATUSES[state]
    rule_label, rule_symbol = STATUSES[rule_state]
    if triage == "SKIP":
        rule_label = {"allowed": "would allow", "blocked": "would block", "held": "would hold"}.get(
            rule_state, rule_label)
    return {"state": state, "label": label, "symbol": symbol,
            "rule_state": rule_state, "rule_label": rule_label, "rule_symbol": rule_symbol,
            "model": {"ACT": "Proceed", "SKIP": "Skip", "ERROR": "Could not complete"}.get(triage, "Not run"),
            "outcome": outcome,
            "proposed": ACTION_LABELS.get((decision.get("planned_action") or {}).get("action_kind"), "Follow-up")}


def comparison_counts(snapshot):
    if snapshot is None:
        return None
    counts = dict.fromkeys(STATUSES, 0)
    for decision in snapshot.get("result", {}).get("decisions", []):
        counts[decision_view(decision)["state"]] += 1
    return counts


def result_summary(snapshot):
    """Count policy outcomes and successful outputs from the displayed snapshot only."""
    counts = comparison_counts(snapshot)
    if counts is None:
        return "No saved result for this profile. No run yet."
    actions = {a["signal_key"]: a for a in snapshot.get("result", {}).get("actions", [])}
    outputs = dict.fromkeys(("research brief", "quote", "setup suggestion", "no quote returned", "other output"), 0)
    for decision in snapshot.get("result", {}).get("decisions", []):
        action = actions.get(decision["signal_key"])
        if decision_view(decision)["state"] != "allowed" or not action:
            continue
        kind = ("no quote returned" if action.get("quote_unavailable") else
                "quote" if action.get("quote") else
                {"unresolved": "research brief", "new_entry": "setup suggestion"}.get(action.get("kind"), "other output"))
        outputs[kind] += 1
    parts = [f"{n} {kind}{'s' if n != 1 and kind != 'no quote returned' else ''}"
             for kind, n in outputs.items() if n]
    allowed = f"{counts['allowed']} allowed" + (f" ({', '.join(parts)})" if parts else "")
    other = [f"{counts[key]} {label}" for key, label in (
        ("held", "held"), ("blocked", "blocked"), ("skipped", "skipped by the model"),
        ("failed", "failed"), ("pending", "not evaluated")) if counts[key]]
    return ", ".join([allowed, *other]) + "."


def result_provenance(snapshot, mode):
    if snapshot is None:
        return "No saved result for this profile. No run yet."
    if mode == "live":
        return "Live run just now" + (" — some actions failed." if snapshot.get("status") != "complete" else ".")
    origin = "a real API run" if snapshot.get("source") == "live" else "an illustrative run with scripted providers"
    return (f"Saved results from {origin} on {human_date(snapshot.get('created_at'), include_time=True)}. "
            "Switching profiles makes no new calls.")


def research_sources(action):
    """Extract references, without repeating the model's claims about user behaviour."""
    urls = re.findall(r'https?://[^\s<>"\']+', action.get("text", ""))
    result = []
    for raw in urls:
        url = raw.rstrip(".,;:!?)]}")
        try:
            host = urlsplit(url).hostname
        except ValueError:
            continue
        if host and url not in [source["url"] for source in result]:
            result.append({"url": url, "label": host.removeprefix("www.")})
    return result


def evidence_summary(signal):
    """Describe detector evidence, never infer intent from model-generated prose."""
    evidence = signal.evidence

    def counted(count, word, plural=None):
        return f"{count} {word if count == 1 else plural or word + 's'}"

    try:
        if signal.kind == "new_entry" and evidence.get("onboarding_paths"):
            first = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=evidence["first_visit_us"])
            date = human_date(first.isoformat())
            visits = evidence["visit_count"]
            detail = (f"Visited the setup page once on {date}" if visits == 1 else
                      f"{counted(visits, 'visit')} to this site, including an onboarding page; first visit {date}")
        elif signal.kind == "unresolved":
            searches, follows = evidence["search_count"], evidence["follow_through_counts"]
            detail = (f"1 search; {counted(follows[0], 'follow-through visit')} within 30 minutes"
                      if searches == 1 and len(follows) == 1 else
                      f"{counted(searches, 'search', 'searches')}; "
                      f"follow-through visits per search: {', '.join(map(str, follows))} (30-minute windows)")
        elif signal.kind == "korea_product":
            detail = f"{counted(evidence['visit_count'], 'product-page visit')} across {counted(evidence['distinct_days'], 'day')}"
        elif signal.kind == "recurring":
            detail = f"{counted(evidence['total_visits'], 'visit')} to this site across {counted(evidence['distinct_days'], 'day')}"
        elif signal.kind == "dropped":
            detail = f"Visits on {counted(evidence['active_days'], 'day')}; no visits for the next {counted(evidence['days_quiet'], 'day')}"
        else:
            return "Sample history: see the recorded evidence below."
    except (KeyError, TypeError, ValueError, OverflowError):
        return "Sample history: see the recorded evidence below."
    return f"Sample history: {detail}."


def remaining_runs(store):
    """Read the same UTC budget as reserve(), without consuming an attempt."""
    day = store.clock().astimezone(timezone.utc).date().isoformat()
    with store.connect() as conn:
        row = conn.execute("SELECT used FROM budget WHERE day=?", (day,)).fetchone()
    return max(0, store.daily_limit - (row[0] if row else 0))


def quote_view(quote):
    currency = quote.get("currency", "")
    local = quote.get("localPrice")
    sentence = ""
    if quote.get("verdict") == "buy_local":
        sentence = (f"It's cheaper to buy locally: {currency} {number(local.get('price'))} locally versus "
                    f"{currency} {number(quote.get('totalCost'))} estimated total cost from Korea." if local else
                    "It's cheaper to buy locally according to the service verdict; no local price was supplied.")
    # Keep the full fulfilment statement in the disclosure, beside the raw quote.
    seller = quote.get("seller") or "Not supplied"
    total_krw = None
    try:
        total_krw = Decimal(str(quote["totalCost"])) * Decimal(str(quote["payNow"]["fxRate"]))
        if not total_krw.is_finite():
            total_krw = None
    except (KeyError, InvalidOperation, TypeError, ValueError):
        pass
    return {"local_first": sentence, "seller": seller, "total_krw": total_krw,
            "verdict": {"buy_local": "Local reference is lower", "buy_from_korea": "Korea estimate is lower",
                        "close_call": "Prices are close", "insufficient_data": "Not enough data to compare"}.get(
                            quote.get("verdict"), "No comparison verdict")}


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
    templates.env.filters.update(number=number, human_date=human_date, model_text=model_text)
    templates.env.globals.update(quote_view=quote_view)
    configured_cache = cache_path or os.getenv("DEMO_CACHE")
    seed = json.loads(Path(configured_cache or ROOT / "fixtures" / "cache.json").read_text())
    if configured_cache and seed["dataset"] != dataset:
        raise ValueError("Precomputed cache does not match the synthetic dataset")

    def cached(profile):
        # Precedence: reviewed LIVE seed > a stored live run > the illustrative fixture.
        # A visitor's live run is shown in that visitor's response and kept in the store for
        # audit, but it never replaces a reviewed live seed for every other visitor
        # (2026-10-09: one live run put an unreviewed model sentence on the public page).
        candidate = None
        if seed["dataset"] == dataset:
            found = seed["profiles"].get(profile)
            if found and found["mandate_digest"] == load_mandate(PROFILES[profile], None).digest:
                candidate = found
        if candidate is not None and candidate.get("source") == "live":
            return candidate
        return store.get(dataset, profile) or candidate

    def render(request, profile, *, snapshot=None, mode="cached", request_activity="not_started", notice="", status=200):
        mandate = load_mandate(PROFILES[profile], None)
        snapshot = cached(profile) if snapshot is None else snapshot
        decisions = {} if snapshot is None else {d["signal_key"]: d for d in snapshot["result"]["decisions"]}
        actions = {} if snapshot is None else {a["signal_key"]: a for a in snapshot["result"]["actions"]}
        rows = [{"signal": signal, "decision": decisions.get(signal.key), "action": actions.get(signal.key),
                 "evidence_summary": evidence_summary(signal),
                 "sources": research_sources(actions.get(signal.key) or {}),
                 "kind": SIGNAL_LABELS.get(signal.kind, "Browsing pattern"),
                 "view": decision_view(decisions.get(signal.key), actions.get(signal.key))} for signal in signals]
        # The comparison is the bundled saved experiment, even after a visitor runs live.
        saved = {key: seed.get("profiles", {}).get(key) if seed["dataset"] == dataset else None
                 for key in PROFILES}
        saved = {key: value if value and value["mandate_digest"] == load_mandate(PROFILES[key], None).digest
                 else None for key, value in saved.items()}
        signal_sets = [set(d["signal_key"] for d in value["result"]["decisions"])
                       for value in saved.values() if value]
        same_signals = len(signal_sets[0]) if signal_sets and all(s == signal_sets[0] for s in signal_sets) else None
        public_actions = (saved.get("public") or {}).get("result", {}).get("actions", [])
        featured_key = next((a["signal_key"] for a in public_actions if a.get("quote")), None)
        product_rows = [row for row in rows if row["signal"].kind == "korea_product"]
        featured_quote = next((row for row in product_rows if row["signal"].key == featured_key),
                              product_rows[0] if product_rows else None)
        csrf = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(request=request, name="index.html", context={
            "quote_disclosure": DISCLOSURE, "quote_checkout_notice": CHECKOUT_NOTICE,
            "signals": signals, "scenario": scenario, "profiles": LABELS, "profile": profile,
            "mandate": mandate, "mandate_text": PROFILES[profile].read_text(),
            "snapshot": snapshot, "decisions": decisions, "actions": actions, "mode": mode,
            "notice": notice, "request_activity": request_activity, "csrf": csrf, "daily_limit": store.daily_limit,
            "remaining_runs": remaining_runs(store), "history_window": history_window(scenario),
            "rows": rows, "statuses": STATUSES,
            "comparisons": {key: comparison_counts(saved[key]) for key in PROFILES},
            "same_signals": same_signals, "featured_quote": featured_quote,
            "result_counts": comparison_counts(snapshot), "result_summary": result_summary(snapshot),
            "result_provenance": result_provenance(snapshot, mode),
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
                          request_activity="ran",
                          notice="Live run failed; errors below. Last successful cache was preserved." if failed else "Live run completed.",
                          status=502 if failed else 200)
        notices = {"busy": "Another run is active. Showing cached results; no new calls were made.",
                   "limit": "Daily server limit reached. Showing cached results; no new calls were made."}
        return render(request, profile, snapshot=store.latest(dataset),
                      request_activity="failed_attempt" if status.startswith("error:") else "not_started",
                      notice=notices.get(status, "Live run failed (" + status + "). Showing cached results."),
                      status=502 if status.startswith("error:") else 200)

    async def health(request):
        return JSONResponse({"status": "ok", "dataset": "synthetic"})

    app = Starlette(routes=[Route("/", home), Route("/run", run_request, methods=["POST"]),
                           Route("/healthz", health)])
    app.state.store = store
    app.state.seed = seed
    app.state.dataset = dataset
    return app
