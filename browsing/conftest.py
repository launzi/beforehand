"""Offline browsing tests: no real providers or user-home trace artifacts."""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Browsing tests must not access the network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture(autouse=True)
def isolate_default_agent_trace(monkeypatch, tmp_path):
    from browsing import agent
    from browsing.trace import Tracer

    monkeypatch.setattr(agent, "Tracer", lambda: Tracer(tmp_path / "agent.jsonl"))


@pytest.fixture
def quality_signals():
    """Fixed synthetic shape: dropped 4, new_entry 2, recurring 5, unresolved 1.

    Contract inputs, not golden model verdicts or a copy of browsing history.
    """
    from browsing.signals import Signal

    first = 13404038416000000
    day = 86_400_000_000
    cases = []
    for i in range(4):
        cases.append(("dropped", {"active_days": 3 + i, "last_visit_us": first,
                                  "days_quiet": 7 + i}))
    for i in range(2):
        cases.append(("new_entry", {"onboarding_paths": ["/signup", "/onboarding"],
                                    "first_visit_us": first, "visit_count": 2 + i}))
    for i in range(5):
        cases.append(("recurring", {"distinct_days": 3 + i, "total_visits": 6 + i,
                                    "first_day": "2026-09-01", "last_day": "2026-09-07"}))
    cases.append(("unresolved", {"term": "static site generator comparison", "search_count": 3,
                                  "follow_through_counts": [0, 1, 0], "distinct_days": 2,
                                  "low_follow_through": True, "repeat_across_days": True}))
    return [Signal(kind=kind, key=f"{kind}|quality-{i}",
                   host=None if kind == "unresolved" else f"quality-{i}.test",
                   term=evidence.get("term"), evidence=evidence,
                   first_us=first, last_us=first + day)
            for i, (kind, evidence) in enumerate(cases)]
