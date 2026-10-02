import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from browsing.persona.generate import DEFAULT_SCENARIO, GenerationError, generate, load_scenario, populate
from browsing.providers import ProviderError

FIXTURE = Path(__file__).parents[2] / "web" / "fixtures" / "visits.json"


class FakeLLM:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_generate_validates_all_planted_signals_and_ingest_schema(tmp_path):
    output = tmp_path / "browsing.db"
    llm = FakeLLM([FIXTURE.read_text()])
    manifest = generate(DEFAULT_SCENARIO, output, llm=llm)
    assert manifest["synthetic"] is True
    assert manifest["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(output.with_suffix(".db.json").read_text()) == manifest
    assert len(manifest["signal_keys"]) == 6
    with sqlite3.connect(output) as conn:
        assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 9
        assert conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0] == 1
        assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            "urls", "visits", "searches", "downloads", "domains", "sync_state"}
    assert llm.calls[0][1]["tier"] == "super"


def test_missing_signal_retries_then_fails_without_output(tmp_path):
    payload = json.loads(FIXTURE.read_text())
    payload["visits"] = [v for v in payload["visits"] if "figma" not in v["url"]]
    llm = FakeLLM([json.dumps(payload)] * 3)
    output = tmp_path / "browsing.db"
    with pytest.raises(GenerationError, match="after 3 attempts.*figma.com"):
        generate(DEFAULT_SCENARIO, output, llm=llm)
    assert len(llm.calls) == 3
    assert "Missing required signals" in llm.calls[1][0]
    assert list(tmp_path.iterdir()) == []


def test_invalid_json_can_recover(tmp_path):
    llm = FakeLLM(["invalid json", FIXTURE.read_text()])
    assert generate(DEFAULT_SCENARIO, tmp_path / "browsing.db", llm=llm)["attempts"] == 2


def test_llm_error_propagates_without_retry(tmp_path):
    error = ProviderError("model unavailable")
    llm = FakeLLM([error])
    with pytest.raises(ProviderError) as caught:
        generate(DEFAULT_SCENARIO, tmp_path / "browsing.db", llm=llm)
    assert caught.value is error
    assert len(llm.calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_existing_output_is_not_overwritten(tmp_path):
    output = tmp_path / "browsing.db"
    output.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        generate(DEFAULT_SCENARIO, output, llm=FakeLLM([]))
    assert output.read_bytes() == b"existing"


@pytest.mark.parametrize("change", [
    {"url": "https://unlisted.example/signup"},
    {"url": "https://account:secret@notion.so/signup"},
    {"at": "2026-09-02T00:00:00"},
    {"at": "2027-01-01T00:00:00+00:00"},
    {"title": ""},
])
def test_invalid_records_cannot_be_silently_ingested(change):
    payload = json.loads(FIXTURE.read_text())
    payload["visits"][0].update(change)
    with sqlite3.connect(":memory:") as conn, pytest.raises(ValueError):
        populate(conn, payload, load_scenario(DEFAULT_SCENARIO))


def test_duplicate_records_fail_even_when_all_signals_detectable():
    payload = json.loads(FIXTURE.read_text())
    payload["visits"].append(payload["visits"][0])
    with sqlite3.connect(":memory:") as conn, pytest.raises(GenerationError, match="Ingest rejected"):
        populate(conn, payload, load_scenario(DEFAULT_SCENARIO))
