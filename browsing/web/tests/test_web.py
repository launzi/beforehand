import asyncio
from contextlib import suppress
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import httpx

from browsing import providers
from browsing.mandate import load_mandate
from browsing.persona.generate import DEFAULT_SCENARIO, generate
from browsing.web.app import PROFILES, ROOT, create_app, execute, load_dataset
from browsing.web.store import RunStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def event_loop_heartbeat():
    # This sandbox does not wake selector loops on cross-thread notifications.
    # Uvicorn has its own periodic server tick; keep the ASGI test loop ticking too.
    # No application/provider function is patched by this fixture.
    async def tick():
        while True:
            await asyncio.sleep(0.01)
    task = asyncio.create_task(tick())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real provider access is forbidden in demo tests")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.delenv("DEMO_DB", raising=False)


async def post_run(client, profile="public"):
    page = await client.get("/", params={"profile": profile})
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return await client.post("/run", data={"csrf": token, "profile": profile})


class FakeLLM:
    def complete(self, prompt, **kwargs):
        return "ACT" if kwargs.get("max_tokens") == 10 else "Fictional suggestion <script>alert(1)</script>"


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search(self, query, limit=5):
        self.calls.append(query)
        return [{"title": "Synthetic search", "url": "https://docs.python.org/3/", "snippet": "A test"}]


async def test_offline_page_all_profiles_health_and_raw_trace(tmp_path):
    app = create_app(state_dir=tmp_path)
    async with client_for(app) as client:
        assert (await client.get("/healthz")).json() == {"status": "ok", "dataset": "synthetic"}
        for profile in PROFILES:
            page = await client.get("/", params={"profile": profile})
            assert page.status_code == 200
            assert "CACHED" in page.text and "illustrative-fixture" in page.text
            assert load_mandate(PROFILES[profile], None).digest in page.text
            assert 'id="trace"' in page.text and "mandate_decision" in page.text
            assert "new_entry" in page.text and "unresolved" in page.text
        assert "DENY" in (await client.get("/?profile=no-search")).text
        assert "HOLD" in (await client.get("/?profile=confirm-research")).text


async def test_default_live_factories_and_search_mandate(tmp_path, monkeypatch):
    search = FakeSearch()
    monkeypatch.setattr(providers, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(providers, "get_search", lambda: search)
    app = create_app(state_dir=tmp_path)
    async with client_for(app) as client:
        live = await post_run(client)
        assert live.status_code == 200 and "LIVE" in live.text
        assert len(search.calls) == 1
        assert "&lt;script&gt;" in live.text and "<script>" not in live.text
        assert (await post_run(client, "no-search")).status_code == 200
        assert (await post_run(client, "confirm-research")).status_code == 200
        assert len(search.calls) == 1
        cached = await client.get("/")
        assert "CACHED" in cached.text and "illustrative-fixture" not in cached.text
    assert len(list(tmp_path.glob("trace-*.jsonl"))) == 3


async def test_daily_limit_survives_app_restart_and_all_profiles(tmp_path):
    calls = []
    def runner(signals, profile, path):
        calls.append(profile)
        return execute(signals, profile, path, llm=FakeLLM(), search=FakeSearch())
    async with client_for(create_app(state_dir=tmp_path, daily_limit=1, runner=runner)) as client:
        assert (await post_run(client)).status_code == 200
    async with client_for(create_app(state_dir=tmp_path, daily_limit=1, runner=runner)) as client:
        response = await post_run(client, "no-search")
        assert "Daily server limit reached" in response.text and "CACHED" in response.text
    assert calls == ["public"]


async def test_failed_provider_is_visible_and_does_not_overwrite_cache(tmp_path):
    calls = 0
    def runner(signals, profile, path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise providers.ProviderError("service down")
        return execute(signals, profile, path, llm=FakeLLM(), search=FakeSearch())
    app = create_app(state_dir=tmp_path, daily_limit=2, runner=runner)
    async with client_for(app) as client:
        assert (await post_run(client)).status_code == 200
        original = app.state.store.get(app.state.dataset, "public")
        response = await post_run(client)
        assert response.status_code == 502
        assert "Live run failed" in response.text and "ProviderError" in response.text
        assert app.state.store.get(app.state.dataset, "public") == original
        assert "Daily server limit reached" in (await post_run(client)).text
    assert calls == 2


async def test_agent_partial_failure_is_not_reported_as_success(tmp_path):
    class BrokenLLM:
        def complete(self, *args, **kwargs):
            raise providers.ProviderError("test provider failure")
    def runner(signals, profile, path):
        return execute(signals, profile, path, llm=BrokenLLM(), search=FakeSearch())
    app = create_app(state_dir=tmp_path, runner=runner)
    async with client_for(app) as client:
        response = await post_run(client)
        assert response.status_code == 502 and "Live run failed" in response.text
        assert "test provider failure" in response.text
        assert app.state.store.get(app.state.dataset, "public") is None


async def test_concurrent_run_is_rejected_across_store_instances(tmp_path):
    first = RunStore(tmp_path)
    second = RunStore(tmp_path)
    with first.reserve() as permission:
        assert permission == "allowed"
        with second.reserve() as other:
            assert other == "busy"
    with second.connect() as conn:
        assert conn.execute("SELECT SUM(used) FROM budget").fetchone()[0] == 1


async def test_health_stays_responsive_while_live_run_active(tmp_path):
    started, release = threading.Event(), threading.Event()
    def runner(signals, profile, path):
        started.set()
        assert release.wait(5)
        return execute(signals, profile, path, llm=FakeLLM(), search=FakeSearch())
    app = create_app(state_dir=tmp_path, runner=runner)
    async with client_for(app) as client, client_for(app) as other:
        pending = asyncio.create_task(post_run(client))
        try:
            async with asyncio.timeout(5):
                while not started.is_set():
                    await asyncio.sleep(.01)
                assert (await other.get("/healthz")).status_code == 200
                assert "Another run is active" in (await post_run(other)).text
        finally:
            release.set()
        assert (await pending).status_code == 200



async def test_utc_budget_rollover(tmp_path):
    now = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)
    store = RunStore(tmp_path, 1, clock=lambda: now)
    with store.reserve() as permission:
        assert permission == "allowed"
    with store.reserve() as permission:
        assert permission == "limit"
    now += timedelta(minutes=2)
    with store.reserve() as permission:
        assert permission == "allowed"


async def test_reject_unknown_profile_csrf_and_oversized_body(tmp_path):
    def forbidden(*args):
        pytest.fail("Invalid request reached agent")
    async with client_for(create_app(state_dir=tmp_path, runner=forbidden)) as client:
        assert (await client.get("/?profile=../../mandate.local.toml")).status_code == 400
        assert (await client.post("/run", data={"csrf": "fake", "profile": "public"})).status_code == 403
        assert (await client.post("/run", json={})).status_code == 415
        assert (await client.post("/run", content="x" * 1025, headers={"content-type": "application/x-www-form-urlencoded"})).status_code == 413


async def test_generated_bundle_is_readonly_and_hash_checked(tmp_path):
    class Generator:
        def complete(self, *args, **kwargs):
            return (ROOT / "fixtures" / "visits.json").read_text()
    path = tmp_path / "browsing.db"
    generate(DEFAULT_SCENARIO, path, llm=Generator())
    before = path.read_bytes()
    _, _, signals = load_dataset(path)
    assert len(signals) == 6
    assert path.read_bytes() == before
    path.write_bytes(before + b"tamper")
    with pytest.raises(ValueError, match="manifest"):
        load_dataset(path)


async def test_no_fixture_cache_masquerades_as_generated_bundle(tmp_path):
    class Generator:
        def complete(self, *args, **kwargs):
            return (ROOT / "fixtures" / "visits.json").read_text()
    path = tmp_path / "browsing.db"
    generate(DEFAULT_SCENARIO, path, llm=Generator())
    async with client_for(create_app(db_path=path, state_dir=tmp_path / "state")) as client:
        response = await client.get("/")
        assert "No cached run for this dataset" in response.text
        assert "illustrative-fixture" not in response.text


async def test_export_cache_round_trip_and_mismatch(tmp_path):
    from browsing.web.__main__ import export_cache
    state = tmp_path / "state"
    def runner(signals, profile, path):
        return execute(signals, profile, path, llm=FakeLLM(), search=FakeSearch())
    async with client_for(create_app(state_dir=state, runner=runner)) as client:
        for profile in PROFILES:
            assert (await post_run(client, profile)).status_code == 200
    exported = tmp_path / "export.json"
    export_cache(db_path=None, state_dir=state, out=exported)
    async with client_for(create_app(state_dir=tmp_path / "fresh", cache_path=exported, daily_limit=0)) as client:
        page = await post_run(client)
        assert "Daily server limit reached" in page.text
        assert "CACHED" in page.text and "illustrative-fixture" not in page.text
        assert "Fictional suggestion" in page.text
    payload = json.loads(exported.read_text())
    payload["dataset"] = "unrelated dataset"
    exported.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="does not match"):
        create_app(state_dir=tmp_path / "mismatch", cache_path=exported)


async def test_export_refuses_partial_cache_and_preserves_existing_output(tmp_path):
    from browsing.web.__main__ import export_cache
    state = tmp_path / "state"
    RunStore(state)
    output = tmp_path / "cache.json"
    with pytest.raises(ValueError, match="No successful cached run"):
        export_cache(db_path=None, state_dir=state, out=output)
    assert not output.exists()


async def test_limit_returns_last_live_result_with_explicit_policy_mismatch(tmp_path):
    def runner(signals, profile, path):
        return execute(signals, profile, path, llm=FakeLLM(), search=FakeSearch())
    async with client_for(create_app(state_dir=tmp_path, daily_limit=1, runner=runner)) as client:
        assert (await post_run(client, "public")).status_code == 200
        response = await post_run(client, "no-search")
        assert "last successful results under a different mandate" in response.text
        assert "Result profile: public" in response.text
        assert "illustrative-fixture" not in response.text


async def test_required_trace_failure_is_visible(tmp_path, monkeypatch):
    from browsing.web.app import Tracer
    def broken_audit(self, **kwargs):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(Tracer, "decision", broken_audit)
    def runner(signals, profile, path):
        return execute(signals, profile, path, llm=FakeLLM(), search=FakeSearch())
    app = create_app(state_dir=tmp_path, runner=runner)
    async with client_for(app) as client:
        response = await post_run(client)
        assert response.status_code == 502 and "error:OSError" in response.text
        assert app.state.store.get(app.state.dataset, "public") is None
