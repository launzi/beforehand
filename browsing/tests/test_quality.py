"""Offline prompt contracts; these tests make no claims about live model quality."""
from collections import Counter
from copy import deepcopy
import re

import pytest

from browsing.agent import (
    SKILLS, SKILL_SYSTEM, TRIAGE_SYSTEM, _format_skill_evidence, triage_signal,
)
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
        llm = Recorder("You visited these pages. Consider one next step.")
        original_evidence = deepcopy(signal.evidence)
        SKILLS[signal.kind](signal, llm=llm, search=Search(), verdict=True)
        prompt, options = llm.calls[0]
        assert options["system"] == SKILL_SYSTEM
        assert "2-3 sentences" in prompt
        assert "exactly 2-3 sentences" in SKILL_SYSTEM
        assert "second person" in SKILL_SYSTEM
        assert "one concrete" in SKILL_SYSTEM
        assert "ONLY on the provided evidence and search hits" in SKILL_SYSTEM
        assert "weekly report" not in SKILL_SYSTEM
        assert "Write in English" in SKILL_SYSTEM
        assert "Do not mention internal field names, keys, raw timestamps or IDs" in SKILL_SYSTEM
        assert not re.search(r"\b[a-z]+_[a-z_]+\b", prompt)
        assert signal.evidence == original_evidence
        for name, value in signal.evidence.items():
            for item in value if isinstance(value, list) else [value]:
                if name.endswith("_us"):
                    assert str(item) not in prompt
                    assert "2025-10-04" in prompt
                elif isinstance(item, bool):
                    assert ("yes" if item else "no") in prompt
                else:
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


@pytest.mark.parametrize("timestamp,date", [
    (0, "1601-01-01"),
    (11_644_473_600_000_000, "1970-01-01"),
    (13_434_300_000_000_000, "2026-09-19"),
    (13_434_379_200_000_000, "2026-09-20"),
    (13_434_336_000_000_000, "2026-09-20"),
    (13_434_335_999_999_999, "2026-09-19"),
])
def test_skill_evidence_chrome_timestamps_are_exact_utc_dates(timestamp, date):
    assert _format_skill_evidence({"last_visit_us": timestamp}) == f"  last visit: {date}"


def test_skill_evidence_labels_lists_and_booleans():
    assert _format_skill_evidence({
        "active_days": 3, "distinct_days": 3, "days_quiet": 11,
        "onboarding_paths": ["/signup", "/onboarding"],
        "visit_count": 4, "total_visits": 4, "term": "site comparison",
        "search_count": 2, "follow_through_counts": (0, 1),
        "low_follow_through": True, "repeat_across_days": False,
        "first_day": "2026-09-01", "last_day": "2026-09-23",
    }) == "\n".join([
        "  days active: 3", "  days active: 3", "  days quiet: 11",
        "  onboarding pages visited: /signup, /onboarding",
        "  visits: 4", "  visits: 4", "  search term: site comparison",
        "  searches: 2", "  pages visited after each search: 0, 1",
        "  few pages visited after searching: yes",
        "  search repeated on different days: no",
        "  first day: 2026-09-01", "  last day: 2026-09-23",
    ])
    assert _format_skill_evidence({}) == "(empty)"


@pytest.mark.parametrize("timestamp,error", [("invalid", TypeError), (10**30, OverflowError)])
def test_skill_evidence_does_not_hide_invalid_timestamps(timestamp, error):
    with pytest.raises(error):
        _format_skill_evidence({"first_visit_us": timestamp})
