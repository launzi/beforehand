"""에이전트 루프 계약 테스트 — 신호를 행동으로 바꾼다.

구조: detect(규칙) → triage(판단) → act(스킬) → surface

급소 세 가지.

  1. **detect 는 LLM 을 쓰지 않는다.** 이미 signals.py 가 결정적으로 뽑는다.
     여기서 또 부르면 비용이 신호 수에 비례해 터진다.
  2. **triage 가 대부분을 버려야 한다.** 신호는 74건씩 나온다. 전부 행동하면
     리포트가 아니라 소음이 된다.
  3. **한 스킬이 실패해도 루프가 죽지 않는다.** 검색 provider 가 죽었다고
     나머지 신호까지 잃으면 안 된다.

⚠ LLM·검색은 주입한다. 네트워크를 타지 않는다.
"""

import sqlite3

import pytest

from browsing.agent import Action, SKILLS, build_graph, run_agent
from browsing.ingest import init_db, ingest_records
from browsing.signals import Signal

US = 13404038416000000
DAY = 86_400_000_000


def visit(url, us, profile="Default"):
    return {"kind": "visit", "profile": profile, "url": url, "title": "T",
            "visit_time_us": us, "transition": 0, "duration_us": 0,
            "from_visit_key": None}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    ingest_records(c, [
        visit("https://newsvc.test/signup", US),
        visit("https://topic.test/a", US + 1 * DAY),
        visit("https://topic.test/b", US + 2 * DAY),
        visit("https://topic.test/c", US + 3 * DAY),
    ])
    c.commit()
    yield c
    c.close()


class FakeLLM:
    """triage 판정을 정해진 대로 돌려주는 가짜 LLM."""

    def __init__(self, verdicts=None, raises=False):
        self.verdicts = verdicts if verdicts is not None else {}
        self.calls = []
        self.raises = raises

    def complete(self, prompt, **kw):
        self.calls.append(prompt)
        if self.raises:
            raise RuntimeError("llm down")
        for key, verdict in self.verdicts.items():
            if key in prompt:
                return verdict
        return "SKIP"


class FakeSearch:
    def __init__(self, hits=None, raises=False):
        self.hits = hits if hits is not None else [
            {"title": "T", "url": "https://x.test", "snippet": "s"}]
        self.queries = []
        self.raises = raises

    def search(self, query, limit=5):
        self.queries.append(query)
        if self.raises:
            raise RuntimeError("search down")
        return self.hits


def sig(kind="new_entry", host="newsvc.test", term=None, key=None):
    return Signal(kind=kind, key=key or f"{kind}|{host or term}", host=host,
                  term=term, evidence={"note": "x"}, first_us=US, last_us=US)


# ── triage 가 걸러낸다 ───────────────────────────────────────────────────────

def test_skipped_signal_produces_no_action(conn):
    llm = FakeLLM({})           # 전부 SKIP
    result = run_agent(conn, signals=[sig()], llm=llm, search=FakeSearch())
    assert result.actions == []


def test_acted_signal_produces_an_action(conn):
    llm = FakeLLM({"newsvc.test": "ACT: worth a follow-up"})
    result = run_agent(conn, signals=[sig()], llm=llm, search=FakeSearch())
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], Action)


def test_triage_is_called_once_per_signal(conn):
    llm = FakeLLM({})
    run_agent(conn, signals=[sig(host="a.test"), sig(host="b.test")],
              llm=llm, search=FakeSearch())
    assert len(llm.calls) == 2


def test_triage_prompt_carries_the_evidence(conn):
    """근거 없이 판단하게 두면 모델이 지어낸다."""
    llm = FakeLLM({})
    s = Signal(kind="new_entry", key="k", host="svc.test", term=None,
               evidence={"onboarding_paths": ["/signup"], "visits": 3},
               first_us=US, last_us=US)
    run_agent(conn, signals=[s], llm=llm, search=FakeSearch())
    assert "/signup" in llm.calls[0]


def test_result_counts_what_was_skipped(conn):
    """몇 건을 버렸는지 알려야 임계값을 조정할 수 있다."""
    llm = FakeLLM({"keep.test": "ACT: yes"})
    result = run_agent(conn, signals=[sig(host="keep.test"), sig(host="drop.test")],
                       llm=llm, search=FakeSearch())
    assert result.stats["acted"] == 1
    assert result.stats["skipped"] == 1


# ── detect 단계는 LLM 을 부르지 않는다 ────────────────────────────────────────

def test_no_llm_call_when_there_are_no_signals(conn):
    llm = FakeLLM({})
    run_agent(conn, signals=[], llm=llm, search=FakeSearch())
    assert llm.calls == []


def test_signal_limit_caps_llm_calls(conn):
    """신호가 74건씩 나온다. 상한이 없으면 비용이 신호 수만큼 곱해진다."""
    llm = FakeLLM({})
    many = [sig(host=f"h{i}.test") for i in range(50)]
    run_agent(conn, signals=many, llm=llm, search=FakeSearch(), max_signals=10)
    assert len(llm.calls) == 10


# ── 스킬 ─────────────────────────────────────────────────────────────────────

def test_skills_are_registered_by_signal_kind():
    assert "new_entry" in SKILLS
    assert "unresolved" in SKILLS


def test_unresolved_signal_triggers_a_search(conn):
    """미완결 질문이면 밖에서 답을 찾아온다 — 그게 이 신호의 행동이다."""
    llm = FakeLLM({"tomllib": "ACT: look it up"})
    search = FakeSearch()
    run_agent(conn, signals=[sig(kind="unresolved", host=None, term="tomllib")],
              llm=llm, search=search)
    assert search.queries
    assert "tomllib" in search.queries[0]


def test_new_entry_signal_does_not_search(conn):
    """새 진입은 '세팅 끝냈나'를 묻는 것이지 외부 검색이 아니다."""
    llm = FakeLLM({"newsvc.test": "ACT: check setup"})
    search = FakeSearch()
    run_agent(conn, signals=[sig()], llm=llm, search=search)
    assert search.queries == []


def test_action_carries_its_signal_key(conn):
    """행동이 어느 신호에서 나왔는지 추적할 수 있어야 한다."""
    llm = FakeLLM({"newsvc.test": "ACT: yes"})
    result = run_agent(conn, signals=[sig(key="K1")], llm=llm, search=FakeSearch())
    assert result.actions[0].signal_key == "K1"


def test_action_has_readable_text(conn):
    llm = FakeLLM({"newsvc.test": "ACT: yes"})
    result = run_agent(conn, signals=[sig()], llm=llm, search=FakeSearch())
    assert isinstance(result.actions[0].text, str)
    assert result.actions[0].text.strip()


# ── 한 건이 실패해도 전체가 죽지 않는다 ───────────────────────────────────────

def test_search_failure_does_not_kill_the_loop(conn):
    llm = FakeLLM({"t1": "ACT: yes", "t2": "ACT: yes"})
    result = run_agent(conn,
                       signals=[sig(kind="unresolved", host=None, term="t1"),
                                sig(kind="unresolved", host=None, term="t2")],
                       llm=llm, search=FakeSearch(raises=True))
    assert result.stats["errors"] >= 1
    assert result.stats["acted"] + result.stats["errors"] == 2


def test_llm_failure_is_recorded_not_raised(conn):
    result = run_agent(conn, signals=[sig()], llm=FakeLLM(raises=True),
                       search=FakeSearch())
    assert result.stats["errors"] == 1
    assert result.actions == []


def test_errors_are_reported_with_the_signal_key(conn):
    result = run_agent(conn, signals=[sig(key="BAD")], llm=FakeLLM(raises=True),
                       search=FakeSearch())
    assert any("BAD" in e for e in result.errors)


def test_unknown_signal_kind_is_counted_not_crashed(conn):
    llm = FakeLLM({"weird": "ACT: yes"})
    result = run_agent(conn, signals=[sig(kind="weird", host="weird.test")],
                       llm=llm, search=FakeSearch())
    assert result.stats["skipped"] + result.stats["errors"] == 1


# ── 그래프 ───────────────────────────────────────────────────────────────────

def test_build_graph_returns_something_invocable():
    g = build_graph(llm=FakeLLM({}), search=FakeSearch())
    assert hasattr(g, "invoke")


def test_graph_runs_end_to_end(conn):
    g = build_graph(llm=FakeLLM({"newsvc.test": "ACT: yes"}), search=FakeSearch())
    out = g.invoke({"signals": [sig()], "actions": [], "errors": [],
                    "stats": {}, "max_signals": 10})
    assert out["actions"]


def test_empty_signal_list_runs_clean(conn):
    result = run_agent(conn, signals=[], llm=FakeLLM({}), search=FakeSearch())
    assert result.actions == []
    assert result.errors == []
