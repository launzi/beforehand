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
