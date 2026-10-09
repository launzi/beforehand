"""Presentation contracts, using only committed saved runs (never providers)."""
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup
import httpx
import pytest

from browsing.web.app import create_app
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
            assert "Skipped —" in text and "Not run — skipped by model" in text
            assert "Rules: Allowed" not in text
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
    app.state.store.save(app.state.dataset, "no-search", snapshot)
    page = await page_for(app)
    card = page.select_one('.comparison [data-profile="no-search"]')
    assert card.select_one('[data-count="blocked"]').text == "3"
    assert card.select_one('[data-count="skipped"]').text == "4"


async def test_model_text_is_escaped_and_urls_cannot_inject_markup(tmp_path):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
    action = next(a for a in snapshot["result"]["actions"] if a["kind"] == "unresolved")
    action["text"] = '<script>alert(1)</script> See https://example.test/path?q=" onclick="bad and [bad](javascript:alert(1)).'
    app.state.store.save(app.state.dataset, "public", snapshot)
    page = await page_for(app)
    assert not page.select("script, [onclick]")
    assert not page.select('a[href^="javascript:"]')
    assert "<script>alert(1)</script>" in page.select_one("#research-result").text


async def test_human_dates_do_not_rewrite_dates_inside_source_urls(tmp_path):
    app = app_for(tmp_path)
    snapshot = json.loads(CACHE.read_text())["profiles"]["public"]
    action = next(a for a in snapshot["result"]["actions"] if a["kind"] == "unresolved")
    action["text"] = "Read https://example.test/2026-10-09/report and [Report](https://example.test/2026-09-01). Recorded on 2026-10-09."
    app.state.store.save(app.state.dataset, "public", snapshot)
    page = await page_for(app)
    research = page.select_one("#research-result")
    assert [a["href"] for a in research.select("a")] == [
        "https://example.test/2026-10-09/report", "https://example.test/2026-09-01"]
    assert "Recorded on Oct 9, 2026." in visible(research)
