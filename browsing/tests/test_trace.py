"""로컬 트레이스 계약 테스트.

사용자 결정(2026-09-13): 트레이스는 **로컬에만** 남긴다. 밖으로 보내지 않는다.

트레이스에 남는 것과 유출되면 안 되는 것이 정확히 같은 데이터다 — triage 프롬프트에는
호스트명과 경로가 들어간다. 그래서 외부 전송 경로를 문서로 금지하는 것으로는 부족하고,
코드가 꺼야 한다. langsmith 패키지가 이미 설치돼 있어 환경변수 하나로 자동 전송이 켜진다.
"""

import json
import os

import pytest

from browsing.trace import Tracer, disable_external_tracing


# ── 파일에만 쓴다 ────────────────────────────────────────────────────────────

def test_event_is_appended_as_jsonl(tmp_path):
    t = Tracer(tmp_path / "t.jsonl")
    t.event("triage", signal_key="K1", verdict=True)
    rows = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert rows[0]["kind"] == "triage"
    assert rows[0]["signal_key"] == "K1"


def test_events_accumulate(tmp_path):
    t = Tracer(tmp_path / "t.jsonl")
    t.event("a")
    t.event("b")
    assert len((tmp_path / "t.jsonl").read_text().strip().splitlines()) == 2


def test_every_event_has_a_timestamp(tmp_path):
    t = Tracer(tmp_path / "t.jsonl")
    t.event("x")
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert row.get("ts")


def test_parent_directory_is_created(tmp_path):
    t = Tracer(tmp_path / "deep" / "nested" / "t.jsonl")
    t.event("x")
    assert (tmp_path / "deep" / "nested" / "t.jsonl").is_file()


def test_disabled_tracer_writes_nothing(tmp_path):
    p = tmp_path / "t.jsonl"
    t = Tracer(p, enabled=False)
    t.event("x")
    assert not p.exists()


def test_disabled_tracer_still_works_as_a_span(tmp_path):
    t = Tracer(tmp_path / "t.jsonl", enabled=False)
    with t.span("work"):
        pass
    assert not (tmp_path / "t.jsonl").exists()


# ── span 은 소요 시간을 남긴다 ───────────────────────────────────────────────

def test_span_records_duration(tmp_path):
    t = Tracer(tmp_path / "t.jsonl")
    with t.span("triage", signal_key="K"):
        pass
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[-1])
    assert row["kind"] == "triage"
    assert isinstance(row["duration_ms"], (int, float))


def test_span_records_failure_and_reraises(tmp_path):
    """실패한 구간이 트레이스에 남지 않으면 왜 멈췄는지 알 수 없다."""
    t = Tracer(tmp_path / "t.jsonl")
    with pytest.raises(ValueError):
        with t.span("boom"):
            raise ValueError("nope")
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[-1])
    assert row["ok"] is False
    assert "nope" in row["error"]


def test_successful_span_is_marked_ok(tmp_path):
    t = Tracer(tmp_path / "t.jsonl")
    with t.span("fine"):
        pass
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[-1])
    assert row["ok"] is True


# ── 외부 전송을 코드가 끈다 ──────────────────────────────────────────────────

@pytest.mark.parametrize("var", ["LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2",
                                 "LANGCHAIN_TRACING"])
def test_disable_external_tracing_turns_off_the_env_switches(monkeypatch, var):
    monkeypatch.setenv(var, "true")
    disable_external_tracing()
    assert os.environ[var].lower() in ("false", "0", "")


def test_disable_external_tracing_clears_the_api_key(monkeypatch):
    """키가 남아 있으면 다른 경로가 그것을 집어 쓸 수 있다."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "secret")
    disable_external_tracing()
    assert not os.environ.get("LANGSMITH_API_KEY")


def test_importing_the_module_changes_nothing(monkeypatch):
    """옵션이지 강제가 아니다.

    import 만으로 사용자 환경변수를 지우면, 다른 용도로 LangSmith 를 쓰는 사람의
    설정을 이 패키지가 말없이 망가뜨린다. 끄는 것은 호출자가 정한다.
    """
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    import importlib

    import browsing.trace
    importlib.reload(browsing.trace)
    assert os.environ["LANGSMITH_TRACING"] == "true"


def test_disable_is_explicit(monkeypatch):
    """우리 실행 경로는 이것을 명시적으로 부른다."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    disable_external_tracing()
    assert os.environ["LANGSMITH_TRACING"].lower() in ("false", "0", "")


# ── 트레이스 자체가 유출 경로가 되지 않게 ────────────────────────────────────

def test_tracer_never_opens_a_socket(tmp_path, monkeypatch):
    import socket

    def boom(*a, **k):
        raise AssertionError("트레이서가 소켓을 열었다")

    monkeypatch.setattr(socket, "socket", boom)
    t = Tracer(tmp_path / "t.jsonl")
    t.event("x", prompt="anything")
    with t.span("y"):
        pass


def test_default_path_is_under_the_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    t = Tracer()
    assert str(tmp_path) in str(t.path)


def test_non_serialisable_values_do_not_crash(tmp_path):
    """트레이스 때문에 본 작업이 멈추면 안 된다."""
    t = Tracer(tmp_path / "t.jsonl")
    t.event("x", obj=object())
    assert (tmp_path / "t.jsonl").is_file()


# ── 예약어 충돌 (실사용에서 바로 걸렸다) ─────────────────────────────────────

def test_field_named_kind_does_not_collide(tmp_path):
    """신호를 기록하려면 그 신호의 kind 를 쓰게 된다 — 자연스러운 요구다.

    실측: tracer.event("action", kind=a.kind, ...) 가
    TypeError: got multiple values for argument 'kind' 로 죽었다.
    트레이스가 본 작업을 죽이는 것은 이 모듈이 절대 하면 안 되는 일이다.
    """
    t = Tracer(tmp_path / "t.jsonl")
    t.event("action", kind="new_entry", signal_key="K1")
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[-1])
    assert row["kind"] == "action"          # 이벤트 종류는 첫 인자가 이긴다
    assert "new_entry" in json.dumps(row)   # 사용자 값도 어딘가 남는다


def test_span_field_named_kind_does_not_collide(tmp_path):
    t = Tracer(tmp_path / "t.jsonl")
    with t.span("work", kind="recurring"):
        pass
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[-1])
    assert row["kind"] == "work"
