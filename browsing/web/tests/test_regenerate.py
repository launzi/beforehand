import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from urllib.parse import urlsplit

import pytest

from browsing import providers
from browsing.mandate import load_mandate
from browsing.persona.generate import DEFAULT_SCENARIO, load_scenario, populate
from browsing.web.__main__ import main
from browsing.web.app import PROFILES
from browsing.web.regenerate import regenerate_fixtures


def test_regeneration_cli_uses_real_pipeline_without_provider_factories(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("Fixture regeneration must never create a real provider")

    monkeypatch.setattr(providers, "get_llm", forbidden)
    monkeypatch.setattr(providers, "get_search", forbidden)
    monkeypatch.setenv("DEMO_DB", str(tmp_path / "must-not-read.db"))
    monkeypatch.setattr(sys, "argv", ["browsing.web", "regenerate-fixtures",
                                     "--output-dir", str(tmp_path)])
    main()
    source = (tmp_path / "visits.json").read_bytes()
    payload = json.loads(source)
    scenario = load_scenario(DEFAULT_SCENARIO)
    assert {urlsplit(v["url"]).hostname for v in payload["visits"]} == set(scenario["allowed_hosts"])
    with closing(sqlite3.connect(":memory:")) as conn:
        signals = populate(conn, payload, scenario)
    assert len(signals) == 6
    cache = json.loads((tmp_path / "cache.json").read_text())
    assert cache["dataset"] == hashlib.sha256(source).hexdigest()
    assert set(cache["profiles"]) == set(PROFILES)
    for profile, expected in (("public", "allow"), ("no-search", "deny"),
                              ("confirm-research", "hold")):
        snapshot = cache["profiles"][profile]
        assert snapshot["status"] == "complete"
        assert snapshot["source"] == "illustrative-fixture"
        assert snapshot["mandate_digest"] == load_mandate(PROFILES[profile], None).digest
        assert snapshot["result"]["errors"] == []
        decisions = snapshot["result"]["decisions"]
        assert {d["signal_key"] for d in decisions} == {s.key for s in signals}
        research = next(d for d in decisions if d["signal_kind"] == "unresolved")
        assert research["mandate"]["verdict"] == expected
        assert research["executed"] is (expected == "allow")
        trace = [json.loads(line) for line in snapshot["trace"].splitlines()]
        audited = [event for event in trace if event["kind"] == "mandate_decision"]
        assert {e["signal_key"] for e in audited} == {s.key for s in signals}
        assert all(e["mandate_digest"] == snapshot["mandate_digest"] for e in audited)


def test_failed_regeneration_preserves_both_fixtures(tmp_path, monkeypatch):
    from browsing.web import regenerate

    for name in ("visits.json", "cache.json"):
        (tmp_path / name).write_text("previous fixture")

    def fail(*args, **kwargs):
        return {"status": "failed", "result": {"errors": ["script failure"]}}

    monkeypatch.setattr(regenerate, "execute", fail)
    with pytest.raises(ValueError, match="Scripted pipeline failed"):
        regenerate_fixtures(output_dir=tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"visits.json", "cache.json"}
    assert all(p.read_text() == "previous fixture" for p in tmp_path.iterdir())
