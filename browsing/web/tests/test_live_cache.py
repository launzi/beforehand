"""live-cache with fake providers only; the real run spends money and is never executed by tests."""
import json
import sys

import httpx
import pytest

from browsing import providers
from browsing.providers import ProviderError
from browsing.web import live_cache
from browsing.web.app import PROFILES, create_app, load_dataset
from browsing.web.regenerate import ScriptedLLM, ScriptedQuote, ScriptedSearch
from browsing.web.__main__ import main

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden in live-cache tests")
    monkeypatch.delenv("DEMO_DB", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("browsing.web.korea_quote._http_post", forbidden)


@pytest.fixture
def dataset(monkeypatch):
    loaded = load_dataset(None)  # the offline fixture stands in for a validated synthetic DB
    monkeypatch.setattr(live_cache, "load_dataset", lambda db: loaded)
    return loaded


class BrokenLLM(ScriptedLLM):
    def complete(self, prompt, **kwargs):
        raise ProviderError("token budget exhausted")


def build(tmp_path, out, llm=None):
    return live_cache.build_live_cache(db_path=tmp_path / "synthetic.db", out=out,
                                       llm=llm or ScriptedLLM(), search=ScriptedSearch(),
                                       quote_client=ScriptedQuote())


async def test_writes_three_live_profiles_served_as_cached(tmp_path, dataset):
    out = tmp_path / "cache-live-20261010-120000.json"
    build(tmp_path, out)
    saved = json.loads(out.read_text())
    assert saved["dataset"] == dataset[0]
    assert set(saved["profiles"]) == set(PROFILES)
    assert all(s["source"] == "live" and s["status"] == "complete" for s in saved["profiles"].values())
    app = create_app(state_dir=tmp_path, cache_path=out)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/")
    assert "<strong>CACHED</strong> · live · complete" in page.text


def test_failed_profile_writes_nothing(tmp_path, dataset):
    out = tmp_path / "cache-live-20261010-120001.json"
    with pytest.raises(RuntimeError, match="Live run failed"):
        build(tmp_path, out, llm=BrokenLLM())
    assert not out.exists()


def test_refuses_overwrite_and_missing_timestamp(tmp_path, dataset):
    out = tmp_path / "cache-live-20261010-120002.json"
    out.write_text("keep")
    with pytest.raises(FileExistsError):
        build(tmp_path, out)
    assert out.read_text() == "keep"
    with pytest.raises(ValueError, match="timestamp"):
        build(tmp_path, tmp_path / "cache-live.json")


def test_cli_requires_confirm_spend_before_any_provider(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("No provider may be built without --confirm-spend")
    monkeypatch.setattr(providers, "get_llm", forbidden)
    monkeypatch.setattr(providers, "get_search", forbidden)
    monkeypatch.setattr(sys, "argv", ["browsing.web", "live-cache", "--db", str(tmp_path / "x.db"),
                                      "--out", str(tmp_path / "cache-live-20261010-120003.json")])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


@pytest.mark.parametrize('manual', [False, True])
async def test_unavailable_quote_completes_cache_and_renders_without_prices(tmp_path, dataset, manual):
    from types import SimpleNamespace
    from browsing.web.korea_quote import KoreaQuoteClient

    unavailable_signal = next(s for s in dataset[2] if s.kind == 'korea_product')
    envelope = {'error': 'quote_unavailable', 'message': 'No Korean listing found.', 'warnings': []}
    if manual:
        envelope['needsManualPrice'] = 'Send koreaPriceKrw'
    unavailable_client = KoreaQuoteClient(lambda *a, **kw: SimpleNamespace(
        status_code=200, headers={}, json=lambda: {'result': {'structuredContent': envelope}}))

    class QuoteClient(ScriptedQuote):
        def quote(self, product, destination='US'):
            if product == unavailable_signal.term:
                return unavailable_client.quote(product, destination)
            return super().quote(product, destination)

    class LLM(ScriptedLLM):
        def complete(self, prompt, **kwargs):
            if prompt.startswith('Korea quote facts:'):
                facts = json.loads(prompt.removeprefix('Korea quote facts: '))
                assert facts['product'] != unavailable_signal.term
            return super().complete(prompt, **kwargs)

    out = tmp_path / 'cache-live-20261010-120004.json'
    live_cache.build_live_cache(db_path=tmp_path / 'synthetic.db', out=out,
        llm=LLM(), search=ScriptedSearch(), quote_client=QuoteClient())
    saved = json.loads(out.read_text())
    assert all(s['status'] == 'complete' for s in saved['profiles'].values())
    snapshot = saved['profiles']['public']
    assert snapshot['result']['errors'] == []
    assert snapshot['result']['stats']['errors'] == 0
    action = next(a for a in snapshot['result']['actions'] if a['signal_key'] == unavailable_signal.key)
    assert action['quote'] is None and action['quote_unavailable'] is True
    decision = next(d for d in snapshot['result']['decisions'] if d['signal_key'] == unavailable_signal.key)
    assert decision['execution_status'] == 'succeeded'
    app = create_app(state_dir=tmp_path, cache_path=out)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        page = await client.get('/')
    assert '<strong>CACHED</strong> · live · complete' in page.text
    cards = [c.split('</article>', 1)[0] for c in page.text.split('<article class="quote-card">')[1:]]
    unavailable = [c for c in cards if '<strong>No quote returned.</strong> Korea Concierge could not price this item.' in c]
    assert len(cards) == 3 and len(unavailable) == 1
    assert '<table' not in unavailable[0]
    assert '<a ' not in unavailable[0]
    assert 'USD' not in unavailable[0] and 'KRW' not in unavailable[0]
    assert 'No order or payment was created.' in unavailable[0]
    # Technical checkout denial remains in the signal's collapsed disclosure.
    assert 'commerce.checkout is always denied' in page.text
