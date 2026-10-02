"""Exercise the live-evaluation command with fake providers only."""
import json
import sys

import pytest

from browsing.agent import TRIAGE_SYSTEM
from browsing.providers import ProviderError
from browsing.web import eval_live
from browsing.web.__main__ import main


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail

    def complete(self, prompt, **kwargs):
        if kwargs.get("system") == TRIAGE_SYSTEM:
            if self.fail:
                raise ProviderError("triage budget exhausted")
            return "ACT"
        return "활동 기록을 확인했어요. 다음 단계를 확인해 보세요."


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search(self, query, limit):
        self.calls.append(query)
        return []


def test_eval_twelve_signals_reports_rates_samples_and_mandates(tmp_path, monkeypatch, quality_signals):
    monkeypatch.setattr(eval_live, "load_dataset", lambda db: ("fixture", {}, quality_signals))
    search = FakeSearch()
    result = eval_live.evaluate_live(db_path=tmp_path / "synthetic.db", runs=3,
                                     llm=FakeLLM(), search=search)
    assert result["status"] == "complete"
    assert result["signal_count"] == 12
    assert len(result["run_results"]) == 9
    assert len(result["signals"]) == 36
    assert len(search.calls) == 3  # Public only: no mandate bypass for evaluation.
    for row in result["signals"]:
        assert (row["act"], row["skip"], row["triage_errors"], row["act_rate"]) == (3, 0, 0, 1.0)
        if row["signal"]["kind"] == "unresolved":
            verdict = {"public": "allow", "no-search": "deny", "confirm-research": "hold"}[row["profile"]]
            assert row["mandate_counts"] == {verdict: 3}
            assert len(row["skill_samples"]) == (3 if verdict == "allow" else 0)
    assert all(len(s["triage_replies"]) == 12 for s in result["run_results"])
    assert list(tmp_path.iterdir()) == []


def test_eval_errors_are_not_skips_or_zero_act_rates(tmp_path, monkeypatch, quality_signals):
    monkeypatch.setattr(eval_live, "load_dataset", lambda db: ("fixture", {}, quality_signals))
    result = eval_live.evaluate_live(db_path=tmp_path / "synthetic.db", runs=2, profiles=["public"],
                                     llm=FakeLLM(fail=True), search=FakeSearch())
    assert result["status"] == "failed"
    assert all(row["act_rate"] is None and row["triage_errors"] == 2 and row["skip"] == 0
               for row in result["signals"])
    assert all(s["result"]["errors"] for s in result["run_results"])


def test_eval_measures_alternating_verdicts(tmp_path, monkeypatch, quality_signals):
    monkeypatch.setattr(eval_live, "load_dataset", lambda db: ("fixture", {}, quality_signals))

    class AlternatingLLM(FakeLLM):
        count = 0

        def complete(self, prompt, **kwargs):
            if kwargs.get("system") == TRIAGE_SYSTEM:
                run = self.count // 12
                self.count += 1
                return "ACT" if run % 2 == 0 else "SKIP"
            return super().complete(prompt, **kwargs)

    result = eval_live.evaluate_live(db_path=tmp_path / "synthetic.db", runs=3, profiles=["public"],
                                     llm=AlternatingLLM(), search=FakeSearch())
    assert all(row["act_rate"] == pytest.approx(2 / 3) and row["skip"] == 1
               for row in result["signals"])
    assert all(len(row["skill_samples"]) == 2 for row in result["signals"])


def test_eval_valid_synthetic_bundle_runs_real_loader_offline(tmp_path):
    from browsing.persona.generate import DEFAULT_SCENARIO, generate
    from browsing.web.app import ROOT

    class PersonaLLM:
        def complete(self, prompt, **kwargs):
            return (ROOT / "fixtures" / "visits.json").read_text()

    db = tmp_path / "synthetic.db"
    generate(DEFAULT_SCENARIO, db, llm=PersonaLLM())
    result = eval_live.evaluate_live(db_path=db, runs=1, profiles=["public"],
                                     llm=FakeLLM(), search=FakeSearch())
    assert result["status"] == "complete"
    assert result["signal_count"] == 6
    assert len(result["signals"]) == 6


def test_cli_emits_json_and_exits_nonzero_on_failed_evaluation(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_evaluation(**kwargs):
        calls.append(kwargs)
        return {"status": "failed", "signals": []}

    monkeypatch.setattr(eval_live, "evaluate_live", fake_evaluation)
    path = tmp_path / "synthetic.db"
    monkeypatch.setattr(sys, "argv", ["browsing.web", "eval-live", "--db", str(path),
                                     "--runs", "3", "--profile", "no-search"])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert calls == [{"db_path": path, "runs": 3, "profiles": ["no-search"]}]


@pytest.mark.parametrize("options", [{"runs": 0}, {"profiles": ["unknown"]},
                                    {"profiles": ["public", "public"]}])
def test_eval_rejects_invalid_options_before_providers(tmp_path, monkeypatch, options):
    def forbidden():
        pytest.fail("must validate before provider creation")

    monkeypatch.setattr(eval_live.providers, "get_llm", forbidden)
    with pytest.raises(ValueError):
        eval_live.evaluate_live(db_path=tmp_path / "absent.db", **options)


def test_eval_requires_validated_synthetic_manifest_before_providers(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("must validate bundle before provider creation")

    monkeypatch.setattr(eval_live.providers, "get_llm", forbidden)
    db = tmp_path / "synthetic.db"
    db.write_bytes(b"not a real database")
    db.with_suffix(".db.json").write_text('{"synthetic": false}')
    with pytest.raises(ValueError, match="synthetic manifest"):
        eval_live.evaluate_live(db_path=db)
