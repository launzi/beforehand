"""Offline prompt contracts; these tests make no claims about live model quality."""
from collections import Counter

import pytest

from browsing.agent import SKILLS, SKILL_SYSTEM, TRIAGE_SYSTEM, triage_signal
from browsing.providers import ProviderError


class Recorder:
    def __init__(self, reply="SKIP"):
        self.reply = reply
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class Search:
    def search(self, query, limit):
        return [{"title": "Tool A docs", "url": "https://a.test/build", "snippet": "Uses a build step."},
                {"title": "Tool B docs", "url": "https://b.test/build", "snippet": "Serves files directly."}]


def test_fixed_twelve_signals_have_grounded_rubrics_and_no_forced_verdict(quality_signals):
    assert Counter(s.kind for s in quality_signals) == {
        "dropped": 4, "new_entry": 2, "recurring": 5, "unresolved": 1}
    criteria = {"unresolved": "decision briefing", "dropped": "resumption suggestion",
                "new_entry": "next-step check", "recurring": "usually merit SKIP"}
    for signal in quality_signals:
        for reply, expected in (("ACT", True), ("SKIP", False)):
            llm = Recorder(reply)
            assert triage_signal(signal, llm=llm) is expected
            assert len(llm.calls) == 1
            prompt, options = llm.calls[0]
            assert options["tier"] == "ultra"
            assert options["max_tokens"] >= 4096
            assert options["system"] == TRIAGE_SYSTEM
            assert "exactly one word: ACT or SKIP" in prompt
            assert criteria[signal.kind] in prompt
            assert str(signal.first_us) in prompt and str(signal.last_us) in prompt
            evidence, rubric = prompt.split("Kind rubric:")
            for name, value in signal.evidence.items():
                assert f"{name}:" in evidence
                assert name in rubric
                for item in value if isinstance(value, list) else [value]:
                    assert str(item) in evidence
            assert "mandate layer decides" in options["system"]


@pytest.mark.parametrize("reply,expected", [
    ("ACT", True), (" act \n", True), ("ACT: worth checking", True),
    ("SKIP", False), ("SKIP: no ACT needed", False), ("NOT ACT", False),
    ("INACTIVE", False), ("FACT", False), ("ACTION", False),
    ("ACT or SKIP", False), ("ACT\nSKIP", False), ("", False), (None, False),
])
def test_triage_parser_does_not_act_on_substrings(quality_signals, reply, expected):
    assert triage_signal(quality_signals[0], llm=Recorder(reply)) is expected


def test_triage_provider_error_is_not_skip(quality_signals):
    error = ProviderError("nemotron finish_reason=length")
    with pytest.raises(ProviderError) as caught:
        triage_signal(quality_signals[0], llm=Recorder(error))
    assert caught.value is error


def test_all_twelve_skill_prompts_offer_one_grounded_next_step(quality_signals):
    for signal in quality_signals:
        llm = Recorder("활동을 확인했어요. 다음 단계를 확인해 보세요.")
        SKILLS[signal.kind](signal, llm=llm, search=Search(), verdict=True)
        prompt, options = llm.calls[0]
        assert options["system"] == SKILL_SYSTEM
        assert "2-3 sentences" in prompt
        assert "exactly 2-3 sentences" in SKILL_SYSTEM
        assert "second person" in SKILL_SYSTEM
        assert "one concrete" in SKILL_SYSTEM
        assert "ONLY on the provided evidence and search hits" in SKILL_SYSTEM
        assert "weekly report" not in SKILL_SYSTEM
        for name, value in signal.evidence.items():
            assert f"{name}:" in prompt
            for item in value if isinstance(value, list) else [value]:
                assert str(item) in prompt
        if signal.kind == "unresolved":
            assert "comparison points" in prompt
            assert "Tool A docs" in prompt and "https://a.test/build" in prompt
            assert "Tool B docs" in prompt and "Serves files directly." in prompt
            assert "do not invent features or a winner" in prompt


def test_unresolved_empty_hits_require_uncertainty(quality_signals):
    class EmptySearch:
        def search(self, query, limit):
            return []

    llm = Recorder()
    SKILLS["unresolved"](quality_signals[-1], llm=llm, search=EmptySearch(), verdict=True)
    prompt = llm.calls[0][0]
    assert "(no hits)" in prompt
    assert "say what is unknown" in prompt
