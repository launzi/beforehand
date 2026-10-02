"""The graph must prevent provider calls, not merely label their results denied."""

import json
from types import SimpleNamespace

import pytest

from browsing.agent import SKILLS, TRIAGE_SYSTEM, build_graph, run_agent
from browsing.mandate import load_mandate
from browsing.signals import Signal
from browsing.trace import Tracer


BASE = '''allowed_skills = ["unresolved", "new_entry", "recurring", "dropped"]
allow_search = true
require_confirmation = []
'''


class FakeLLM:
    def __init__(self, triage="ACT", fail_skill=False):
        self.triage = triage
        self.fail_skill = fail_skill
        self.triage_calls = 0
        self.skill_calls = 0

    def complete(self, prompt, *, system, **kwargs):
        if system == TRIAGE_SYSTEM:
            self.triage_calls += 1
            if isinstance(self.triage, Exception):
                raise self.triage
            return self.triage
        self.skill_calls += 1
        if self.fail_skill:
            raise RuntimeError("synthetic skill failure")
        return "Synthetic briefing."


class FakeSearch:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def search(self, query, *, limit):
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic search failure")
        return [{"title": "Synthetic", "url": "https://example.test", "snippet": "Evidence"}]


def signal(kind="unresolved", key=None):
    return Signal(kind, key or f"{kind}:synthetic", "example.test", "synthetic term", {}, 1, 2)


@pytest.fixture
def setup(tmp_path):
    base, local, trace_path = (tmp_path / name for name in ("mandate.toml", "mandate.local.toml", "trace.jsonl"))
    base.write_text(BASE)
    tracer = Tracer(trace_path)
    yield SimpleNamespace(base=base, local=local, trace_path=trace_path, tracer=tracer)
    tracer.close()


def run(setup, *, llm=None, search=None, signals=None, **kwargs):
    return run_agent(
        None, signals=[signal()] if signals is None else signals,
        llm=llm or FakeLLM(), search=search or FakeSearch(),
        mandate_path=setup.base, mandate_local_path=setup.local,
        tracer=setup.tracer, **kwargs,
    )


def events(setup):
    return [json.loads(line) for line in setup.trace_path.read_text().splitlines()]


@pytest.mark.parametrize("overlay, verdict, reason", [
    ('allowed_skills = ["new_entry"]', "deny", "not allowed"),
    ('allow_search = false', "deny", "search"),
    ('require_confirmation = ["research_briefing"]', "hold", "confirmation"),
])
def test_blocked_skill_never_calls_search_or_skill_llm(setup, overlay, verdict, reason):
    setup.local.write_text(overlay)
    llm, search = FakeLLM(), FakeSearch()
    result = run(setup, llm=llm, search=search)
    assert search.calls == 0
    assert llm.triage_calls == 1 and llm.skill_calls == 0
    assert result.actions == []
    assert result.errors == []
    record = result.decisions[0]
    assert record.mandate.verdict == verdict
    assert reason in record.mandate.reason
    assert record.executed is False
    assert result.stats["acted"] == 0
    assert result.stats["held" if verdict == "hold" else "denied"] == 1
    event, = events(setup)
    assert event == {
        "ts": event["ts"], "kind": "mandate_decision",
        "signal_key": signal().key, "signal_kind": "unresolved", "triage": "ACT",
        "planned_action": {"skill": "unresolved", "signal_kind": "unresolved",
                           "action_kind": "research_briefing", "uses_search": True, "uses_llm": True},
        "mandate_digest": load_mandate(setup.base, setup.local).digest,
        "verdict": verdict, "reason": record.mandate.reason,
        "executed": False, "execution_status": "not_run", "execution_error": None,
    }


def test_allow_executes_search_and_emits_success(setup):
    search, llm = FakeSearch(), FakeLLM()
    result = run(setup, search=search, llm=llm)
    assert search.calls == 1
    assert llm.triage_calls == llm.skill_calls == 1
    assert len(result.actions) == 1
    assert result.stats["acted"] == 1
    assert result.errors == []
    event, = events(setup)
    assert event["verdict"] == "allow"
    assert event["executed"] is True and event["execution_status"] == "succeeded"
    assert event["mandate_digest"] == result.decisions[0].mandate.mandate_digest


def test_search_restriction_does_not_block_nonsearch_skill(setup):
    setup.local.write_text("allow_search = false")
    search, llm = FakeSearch(), FakeLLM()
    result = run(setup, signals=[signal("new_entry")], search=search, llm=llm)
    assert search.calls == 0 and llm.skill_calls == 1
    assert len(result.actions) == 1
    assert result.decisions[0].mandate.verdict == "allow"


def test_batch_preserves_allow_hold_and_deny_results(setup):
    setup.local.write_text('allow_search = false\nrequire_confirmation = ["followup_nudge"]')
    search, llm = FakeSearch(), FakeLLM()
    result = run(setup, signals=[signal(kind) for kind in SKILLS], search=search, llm=llm)
    assert search.calls == 0 and llm.skill_calls == 2
    assert [r.mandate.verdict for r in result.decisions] == ["deny", "allow", "allow", "hold"]
    assert result.stats == {"acted": 2, "skipped": 0, "errors": 0, "held": 1, "denied": 1}
    assert len(events(setup)) == 4
    assert len({event["mandate_digest"] for event in events(setup)}) == 1


@pytest.mark.parametrize("bad_layer", ["missing_base", "base", "local"])
def test_missing_or_malformed_policy_denies_every_skill(setup, bad_layer):
    if bad_layer == "missing_base":
        setup.base.unlink()
    else:
        getattr(setup, bad_layer).write_text("invalid = [")
    llm, search = FakeLLM(), FakeSearch()
    result = run(setup, signals=[signal(kind) for kind in SKILLS], llm=llm, search=search)
    assert search.calls == llm.skill_calls == 0
    assert result.actions == []
    assert result.stats["denied"] == 4 and result.stats["acted"] == 0
    assert result.errors and "mandate:" in result.errors[0]
    assert all(r.mandate.verdict == "deny" and "Invalid mandate" in r.mandate.reason for r in result.decisions)
    assert all(e["verdict"] == "deny" and not e["executed"] for e in events(setup))


def test_invalid_policy_is_visible_even_without_signals(setup):
    setup.base.unlink()
    result = run(setup, signals=[])
    assert result.stats["errors"] == 1
    assert "missing" in result.errors[0]


@pytest.mark.parametrize("triage, expected", [("SKIP", "SKIP"), (RuntimeError("triage unavailable"), "ERROR")])
def test_triage_skip_and_error_are_distinct_and_audited(setup, triage, expected):
    llm, search = FakeLLM(triage=triage), FakeSearch()
    result = run(setup, llm=llm, search=search)
    assert llm.skill_calls == search.calls == 0
    assert result.actions == []
    event, = events(setup)
    assert event["triage"] == expected
    assert event["executed"] is False
    assert result.stats["errors"] == (expected == "ERROR")
    assert result.stats["skipped"] == (expected == "SKIP")


@pytest.mark.parametrize("fail_search", [True, False])
def test_provider_failure_is_not_reported_as_success(setup, fail_search):
    result = run(setup, search=FakeSearch(fail=fail_search), llm=FakeLLM(fail_skill=not fail_search))
    assert result.actions == [] and result.stats["errors"] == 1
    assert result.stats["acted"] == 0
    event, = events(setup)
    assert event["verdict"] == "allow" and event["executed"] is True
    assert event["execution_status"] == "failed"
    assert "failure" in event["execution_error"]


def test_graph_has_mandate_node_and_reloads_policy_on_reuse(setup):
    search = FakeSearch()
    graph = build_graph(llm=FakeLLM(), search=search, mandate_path=setup.base,
                        mandate_local_path=setup.local, tracer=setup.tracer)
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("triage", "mandate") in edges and ("mandate", "act") in edges
    assert ("triage", "act") not in edges
    first = graph.invoke({"signals": [signal()]})
    setup.local.write_text("allow_search = false")
    second = graph.invoke({"signals": [signal()]})
    assert search.calls == 1
    assert first["decisions"][0].executed is True
    assert second["decisions"][0].mandate.verdict == "deny"
    assert first["decisions"][0].mandate.mandate_digest != second["decisions"][0].mandate.mandate_digest


def test_signal_limit_applies_to_policy_and_execution(setup):
    search = FakeSearch()
    result = run(setup, signals=[signal(key=f"key-{i}") for i in range(3)], search=search, max_signals=1)
    assert search.calls == 1
    assert len(result.decisions) == len(events(setup)) == 1


def test_missing_skill_declaration_denies_execution(setup, monkeypatch):
    def undeclared(*args, **kwargs):
        pytest.fail("An undeclared skill must never execute")
    monkeypatch.setitem(SKILLS, "unresolved", undeclared)
    search = FakeSearch()
    result = run(setup, search=search)
    assert search.calls == 0
    assert result.decisions[0].mandate.verdict == "deny"
    assert result.errors and "no declared skill" in result.errors[0]


def test_trace_io_failure_is_explicit(setup):
    def broken_write(*args):
        raise OSError("synthetic disk full")
    setup.tracer.close()
    setup.tracer._file = SimpleNamespace(write=broken_write, close=lambda: None)
    setup.local.write_text("allow_search = false")
    with pytest.raises(OSError, match="disk full"):
        run(setup)


def test_duplicate_signal_keys_cannot_overwrite_authorization(setup):
    llm, search = FakeLLM(), FakeSearch()
    with pytest.raises(ValueError, match="unique"):
        run(setup, signals=[signal(), signal()], llm=llm, search=search)
    assert llm.triage_calls == search.calls == 0


def test_negative_limit_is_an_explicit_error(setup):
    with pytest.raises(ValueError, match="non-negative"):
        run(setup, max_signals=-1)
