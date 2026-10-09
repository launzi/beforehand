"""Presentation contracts, using only committed saved runs (never providers)."""
import copy
import json
import re
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import httpx
import pytest

from browsing.web.app import create_app, load_dataset
from browsing.web.korea_quote import CHECKOUT_NOTICE, DISCLOSURE

ASSETS = Path(__file__).resolve().parents[2] / "demo-assets"
CACHE = ASSETS / "cache-live-20261009-120226.json"
DB = ASSETS / "korea-maker-20261003-010959.db"
NAMES = {"public": "Allow research & quotes", "no-search": "Block research & quotes",
         "confirm-research": "Hold for my OK"}
COUNTS = {"public": (6, 0, 0, 3), "no-search": (2, 4, 0, 3),
          "confirm-research": (2, 0, 4, 3)}
PAUSED = "Live runs are paused on this server. Compare the saved results above."
UNAVAILABLE = ("No quote returned — Korea Concierge could not price this item. "
               "No order or payment was created.")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Presentation tests must not call providers")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    for key in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "DEMO_CACHE", "DEMO_DB", "DEMO_DAILY_LIMIT"):
        monkeypatch.delenv(key, raising=False)


def app_for(tmp_path, **kwargs):
    return create_app(db_path=DB, cache_path=CACHE, state_dir=tmp_path, **kwargs)


async def page_for(app, profile="public"):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", params={"profile": profile})
    assert response.status_code == 200
    return BeautifulSoup(response.text, "html.parser")


async def test_failed_attempt_keeps_saved_result_without_claiming_no_calls(tmp_path):
    calls = []

    def called_then_failed(*args):
        calls.append("fake provider call")
        raise RuntimeError("failure after provider call")

    app = app_for(tmp_path, runner=called_then_failed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        page = BeautifulSoup((await client.get("/")).text, "html.parser")
        assert "No new provider calls were made to load this page." in visible(page)
        response = await client.post("/run", data={"profile": "public", "csrf": page.select_one('[name="csrf"]')["value"]})
    assert calls == ["fake provider call"]
    assert response.status_code == 502
    failed = BeautifulSoup(response.text, "html.parser")
    assert "Showing a saved result after a failed attempt. Provider calls may have occurred." in visible(failed)
    assert "No new provider calls" not in response.text
    assert "Live run failed" in visible(failed)
    assert "CACHED · live · complete" in visible(failed)
    assert failed.select_one("#research-result .action-text").text == page.select_one("#research-result .action-text").text
    assert app.state.store.get(app.state.dataset, "public") is None


@pytest.mark.parametrize("refusal", ["limit", "busy"])
async def test_refused_before_runner_may_claim_no_new_calls(tmp_path, refusal):
    def forbidden(*args):
        pytest.fail("A refused request must not start the runner")

    app = app_for(tmp_path, runner=forbidden, daily_limit=0 if refusal == "limit" else 20)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        page = BeautifulSoup((await client.get("/")).text, "html.parser")
        with app.state.store.reserve() if refusal == "busy" else nullcontext():
            response = await client.post("/run", data={"profile": "public", "csrf": page.select_one('[name="csrf"]')["value"]})
    assert response.status_code == 200
    assert "No new provider calls were made to load this page." in response.text
    assert "Provider calls may have occurred" not in response.text


def visible(node):
    """Default-view text, without collapsed details or code in styles/scripts."""
    node = copy.deepcopy(node)
    for hidden in node.select("details, style, script, [hidden]"):
        hidden.decompose()
    return node.get_text(" ", strip=True)


@pytest.mark.parametrize("profile", NAMES)
async def test_story_order_profile_navigation_and_comparison(tmp_path, profile):
    page = await page_for(app_for(tmp_path), profile)
    assert page.title.string == "Beforehand — a personal AI that knows before you ask."
    assert page.h1.get_text(" ", strip=True) == page.title.string
    assert "It reads the signals you already left while browsing, proposes a follow-up, and acts only inside rules you set." in visible(page)
    assert "Demo · synthetic browsing history" in visible(page)
    assert [n.get_text(" ", strip=True) for n in page.select(".flow li")] == [
        "Signals", "Nemotron proposes", "Your rules decide", "Act or stop"]
    assert [n["id"] for n in page.select("main > section")] == [
        "rules", "featured", "signals", "how-it-ran"]
    links = page.select(".profiles a")
    assert {n["href"]: n.get_text(" ", strip=True) for n in links} == {
        f"/?profile={key}": name for key, name in NAMES.items()}
    assert [n["href"] for n in links if n.get("aria-current") == "page"] == [f"/?profile={profile}"]
    cards = page.select(".comparison [data-profile]")
    assert len(cards) == 3
    for card in cards:
        expected = COUNTS[card["data-profile"]]
        actual = tuple(int(card.select_one(f'[data-count="{key}"]').text) for key in (
            "allowed", "blocked", "held", "skipped"))
        assert actual == expected
        assert sum(actual) == 9
    assert "Loading a profile shows its saved results; it does not start a new run." in visible(page)


@pytest.mark.parametrize("profile,rule", [("public", "Allowed ✓"), ("no-search", "Blocked ✕"),
                                         ("confirm-research", "Held ◐")])
async def test_signal_steps_are_human_and_skip_is_not_an_allowed_action(tmp_path, profile, rule):
    page = await page_for(app_for(tmp_path), profile)
    rows = page.select(".signal-row")
    assert len(rows) == 9
    assert sum("Model: Skip" in visible(row) for row in rows) == 3
    for row in rows:
        text = visible(row)
        assert row.select_one("details") and "Outcome:" in text
        if "Model: Skip" in text:
            assert "Rules: Allowed ✓" in text and "Not run — skipped by model" in text
            assert "Rules: Skipped" not in text
        elif "Korean product interest" in text or "Search with little follow-through" in text:
            assert f"Rules: {rule}" in text
    assert "Blocked ✕" in visible(page) and "Held ◐" in visible(page) and "Allowed ✓" in visible(page)


@pytest.mark.parametrize("profile", NAMES)
async def test_technical_identifiers_dates_and_trace_are_collapsed(tmp_path, profile):
    page = await page_for(app_for(tmp_path), profile)
    text = visible(page)
    assert not re.search(r"commerce\.(?:checkout|quote)|not_run|succeeded|buy_local|korea_product|new_entry|\b(?:ACT|SKIP|ALLOW|DENY|HOLD)\b|\d{4}-\d{2}-\d{2}", text)
    assert "Sep 1 – Oct 1, 2026" in text
    assert "Oct 9, 2026," in text
    assert "Saved run" in text and "CACHED · live" in text
    assert page.select_one("#trace").find_parent("details")
    assert not page.select("details[open]")
    assert "mandate_decision" in page.select_one("#trace").text
    for evidence in page.select(".signal-row pre"):
        assert evidence.find_parent("details")


async def test_receipt_numbers_local_first_and_preserved_disclosures(tmp_path):
    page = await page_for(app_for(tmp_path))
    card = page.select_one(".receipt")
    assert [n.get_text(" ", strip=True) for n in card.select(".big")] == ["USD 17.85", "USD 76.70"]
    text = visible(card)
    assert "It's cheaper to buy locally" in text
    assert "Quote only. No order or payment is created." in text
    assert "USD 5.82 estimated, paid on delivery" in text
    assert text.count("Munteok") == 1
    assert "Pay now" not in page.get_text()
    assert "Quoted subtotal — no payment" in card.text
    assert "KRW 31,500" in card.text and "KRW 91,429" in card.text
    assert "USD 3.05" in card.text
    assert card.select_one(".timeline").find_parent("details")
    assert "3.052325581395349" in card.select_one(".raw-quote").text
    assert CHECKOUT_NOTICE in page.get_text() and DISCLOSURE in page.get_text()
    quote = next(a["quote"] for a in json.loads(CACHE.read_text())["profiles"]["public"]["result"]["actions"] if a.get("quote"))
    for warning in quote["warnings"]:
        assert warning in card.get_text()
    assert quote["dutyOnDelivery"]["note"] in card.get_text()
    assert quote["fulfilment"] in card.get_text()


async def test_unavailable_is_one_sentence_without_duplicate_model_text_or_prices(tmp_path):
    page = await page_for(app_for(tmp_path))
    cards = [c for c in page.select(".quote-card") if UNAVAILABLE in visible(c)]
    assert len(cards) == 2
    for card in cards:
        assert visible(card) == UNAVAILABLE
        assert len(card.find_all("p", recursive=False)) == 1
        assert not card.select(".big, table, button, a")
    assert "needs a manual price" not in visible(page)


async def test_model_suggestions_keep_words_but_format_dates_and_link_text(tmp_path):
    page = await page_for(app_for(tmp_path))
    suggestions = page.select(".model-suggestion")
    assert len(suggestions) >= 3
    for suggestion in suggestions:
        assert "Model suggestion" in suggestion.text
        assert "https://" not in visible(suggestion)
    assert "You have visited the onboarding page once" in visible(page)
    research = page.select_one("#research-result")
    assert len(research.select(".model-suggestion a")) == 4
    assert all(a["href"].startswith("https://") and "https://" not in a.text for a in research.select("a"))
    assert "Sep 29, 2026" in visible(page)


@pytest.mark.parametrize("used,limit,remaining", [(0, 0, 0), (0, 3, 3), (2, 3, 1), (3, 3, 0), (4, 3, 0)])
async def test_run_control_reads_actual_shared_budget(tmp_path, used, limit, remaining):
    app = app_for(tmp_path, daily_limit=limit)
    day = app.state.store.clock().astimezone(timezone.utc).date().isoformat()
    with app.state.store.connect() as conn:
        conn.execute("INSERT INTO budget VALUES (?, ?)", (day, used))
    page = await page_for(app)
    button = page.select_one('form[action="/run"] button')
    assert button.has_attr("disabled") == (remaining == 0)
    assert (PAUSED in visible(page)) == (remaining == 0)
    if remaining:
        assert f"{remaining} live runs remaining today" in visible(page)


async def test_remaining_runs_follow_store_utc_clock(tmp_path):
    app = app_for(tmp_path, daily_limit=1)
    now = datetime(2026, 10, 9, 23, 59, tzinfo=timezone.utc)
    app.state.store.clock = lambda: now
    with app.state.store.reserve():
        pass
    assert (await page_for(app)).select_one('form[action="/run"] button').has_attr("disabled")
    now += timedelta(minutes=2)
    assert not (await page_for(app)).select_one('form[action="/run"] button').has_attr("disabled")


async def test_comparison_uses_changed_saved_results_not_hardcoded_counts(tmp_path):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["no-search"]
    snapshot["result"]["decisions"][1]["triage"] = "SKIP"
    app.state.seed["profiles"]["no-search"] = snapshot
    page = await page_for(app)
    card = page.select_one('.comparison [data-profile="no-search"]')
    assert card.select_one('[data-count="blocked"]').text == "3"
    assert card.select_one('[data-count="skipped"]').text == "4"


async def test_model_text_is_escaped_and_urls_cannot_inject_markup(tmp_path):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
    action = next(a for a in snapshot["result"]["actions"] if a["kind"] == "unresolved")
    action["text"] = '<script>alert(1)</script> See https://example.test/path?q=" onclick="bad and [bad](javascript:alert(1)).'
    app.state.seed["profiles"]["public"] = snapshot
    page = await page_for(app)
    assert not page.select("script, [onclick]")
    assert not page.select('a[href^="javascript:"]')
    assert "<script>alert(1)</script>" in page.select_one("#research-result").text


async def test_human_dates_do_not_rewrite_dates_inside_source_urls(tmp_path):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
    action = next(a for a in snapshot["result"]["actions"] if a["kind"] == "unresolved")
    action["text"] = "Read https://example.test/2026-10-09/report and [Report](https://example.test/2026-09-01). Recorded on 2026-10-09."
    app.state.seed["profiles"]["public"] = snapshot
    page = await page_for(app)
    research = page.select_one("#research-result")
    assert [a["href"] for a in research.select("a")] == [
        "https://example.test/2026-10-09/report", "https://example.test/2026-09-01"]
    assert "Recorded on Oct 9, 2026." in visible(research)


@pytest.mark.parametrize("attempt", ["get", "limit", "busy", "exception"])
async def test_request_activity_is_separate_from_saved_result_source(tmp_path, attempt):
    calls = []

    def failing_runner(*args):
        calls.append("simulated provider call")
        raise RuntimeError("failed after calling provider")

    app = app_for(tmp_path, runner=failing_runner, daily_limit=0 if attempt == "limit" else 2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        if attempt != "get":
            csrf = BeautifulSoup(response.text, "html.parser").select_one('[name="csrf"]')["value"]
            if attempt == "busy":
                with app.state.store.reserve():
                    response = await client.post("/run", data={"profile": "public", "csrf": csrf})
            else:
                response = await client.post("/run", data={"profile": "public", "csrf": csrf})
    page = BeautifulSoup(response.text, "html.parser")
    assert "CACHED · live · complete" in visible(page)
    assert "USD 76.70" in visible(page)
    if attempt == "exception":
        assert calls == ["simulated provider call"]
        assert response.status_code == 502
        assert "No new provider calls were made" not in page.text
        assert "Showing a saved result after a failed attempt. Provider calls may have occurred." in visible(page)
    else:
        assert calls == []
        assert response.status_code == 200
        assert "No new provider calls were made to load this page." in visible(page)


@pytest.mark.parametrize("case,model,outcome", [
    ("missing", "Not run", "No run yet"),
    ("skip", "Skip", "Not run — skipped by model"),
    ("error", "Could not complete", "Not run — model triage failed"),
    ("action_failed", "Proceed", "Could not complete — see details"),
])
async def test_missing_skipped_triage_error_and_failed_action_render_distinctly(tmp_path, case, model, outcome):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
    decision = snapshot["result"]["decisions"][0]
    if case == "missing":
        snapshot["result"]["decisions"].remove(decision)
    else:
        decision.update(triage={"skip": "SKIP", "error": "ERROR", "action_failed": "ACT"}[case],
                        executed=False, execution_status="failed" if case == "action_failed" else "not_run")
    app.state.seed["profiles"]["public"] = snapshot
    row = (await page_for(app)).select_one(".signal-row")
    assert f"Model: {model}" in visible(row)
    assert row.select_one(".outcome").text == f"Outcome: {outcome}"
    if case == "error":
        assert "Rules: Allowed ✓" in visible(row)


@pytest.mark.parametrize("verdict,label", [("deny", "Blocked ✕"), ("hold", "Held ◐")])
async def test_triage_error_keeps_actual_mandate(tmp_path, verdict, label):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
    decision = snapshot["result"]["decisions"][0]
    decision["triage"] = "ERROR"
    decision["mandate"]["verdict"] = verdict
    app.state.seed["profiles"]["public"] = snapshot
    row = (await page_for(app)).select_one(".signal-row")
    assert "Model: Could not complete" in visible(row)
    assert f"Rules: {label}" in visible(row)
    assert row.select_one(".outcome").text == "Outcome: Not run — model triage failed"


async def test_public_github_skip_preserves_allowed_mandate_and_comparison_legend(tmp_path):
    page = await page_for(app_for(tmp_path))
    row = page.select_one(".signal-row")
    assert row.h3.text == "github.com"
    assert "Model: Skip Rules: Allowed ✓ Outcome: Not run — skipped by model" in visible(row)
    assert "Allowed counts signals that proceeded past model triage and were allowed by your rules." in visible(page)
    counts = page.select_one('.comparison [data-profile="public"]')
    assert counts.select_one('[data-count="allowed"]').text == "6"
    assert counts.select_one('[data-count="skipped"]').text == "3"


async def test_transfer_disclosure_names_the_demo_server(tmp_path):
    page = await page_for(app_for(tmp_path))
    summaries = [s.text for s in page.select("summary")]
    assert "What this demo server sends" in summaries
    assert "What leaves your device" not in summaries


@pytest.mark.parametrize("profile", NAMES)
async def test_each_model_suggestion_has_factual_evidence_above_it(tmp_path, profile):
    page = await page_for(app_for(tmp_path), profile)
    for suggestion in page.select(".model-suggestion"):
        evidence = suggestion.find_previous_sibling()
        assert "evidence-summary" in evidence.get("class", [])
        assert evidence.text.startswith("Sample history:")
    setup = page.select_one(".setup-result")
    assert "Sample history: 1 visit to an onboarding page on Sep 29, 2026." in visible(setup)
    if profile == "public":
        assert "Sample history: 1 search; 0 follow-through visits within 30 minutes." in visible(page)
        # Preserve the actual model claim; the evidence must independently frame it.
        assert "examined four hits" in visible(page)


async def test_evidence_summary_changes_with_signal_evidence_not_model_output(tmp_path, monkeypatch):
    from dataclasses import replace
    dataset, scenario, signals = load_dataset(DB)
    revised = []
    for signal in signals:
        evidence = dict(signal.evidence)
        if signal.kind == "new_entry":
            evidence.update(visit_count=3, first_visit_us=13435070400000000)
        elif signal.kind == "unresolved":
            evidence.update(search_count=2, follow_through_counts=[0, 2])
        revised.append(replace(signal, evidence=evidence))
    monkeypatch.setattr("browsing.web.app.load_dataset", lambda path: (dataset, scenario, revised))
    page = await page_for(app_for(tmp_path))
    summaries = [p.text for p in page.select(".evidence-summary")]
    assert "Sample history: 3 visits to this site, including an onboarding page; first visit Sep 28, 2026." in summaries
    assert "Sample history: 2 searches; follow-through visits per search: 0, 2 (30-minute windows)." in summaries
    assert "You have visited the onboarding page once" in visible(page)


async def test_header_uses_extension_svg_lockup(tmp_path):
    page = await page_for(app_for(tmp_path))
    brand = page.select_one('header [role="img"][aria-label="Beforehand"]')
    assert brand is not None
    svg = brand.select_one("svg")
    assert svg["viewbox"] == "0 0 213.9 48"
    source = BeautifulSoup((Path(__file__).parents[1] / "templates" / "lockup.svg").read_text(), "html.parser")
    assert [p["d"] for p in svg.select("path")] == [p["d"] for p in source.select("path")]
    assert len(svg.select("path")) == 2  # Speech-bubble b mark and outlined wordmark.


@pytest.mark.parametrize("status", ["complete", "failed"])
async def test_returned_live_attempt_never_claims_no_provider_calls(tmp_path, status):
    calls = []

    def runner(*args):
        calls.append("simulated provider call")
        snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
        snapshot["status"] = status
        return snapshot

    app = app_for(tmp_path, runner=runner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        page = BeautifulSoup((await client.get("/")).text, "html.parser")
        response = await client.post("/run", data={"profile": "public", "csrf": page.select_one('[name="csrf"]')["value"]})
    assert calls == ["simulated provider call"]
    assert response.status_code == (200 if status == "complete" else 502)
    assert "No new provider calls" not in response.text
    assert "Showing a saved result after a failed attempt" not in response.text
    assert f"LIVE · live · {status}" in visible(BeautifulSoup(response.text, "html.parser"))
