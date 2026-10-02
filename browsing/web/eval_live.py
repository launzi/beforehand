"""Opt-in live evaluation of validated synthetic bundles; never called by the app."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
import tempfile

from browsing import providers
from browsing.agent import TRIAGE_MAX_TOKENS, TRIAGE_SYSTEM, TRIAGE_TIER
from browsing.web.app import PROFILES, execute, load_dataset


class RecordingLLM:
    def __init__(self, delegate):
        self.delegate = delegate
        self.triage_replies = []

    def complete(self, prompt, **kwargs):
        reply = self.delegate.complete(prompt, **kwargs)
        if kwargs.get("system") == TRIAGE_SYSTEM:
            self.triage_replies.append({"prompt": prompt, "reply": reply})
        return reply


def evaluate_live(*, db_path: Path, runs: int = 3, profiles=None, llm=None, search=None):
    """Run the unchanged mandate pipeline; injected providers support offline tests.

    Errors remain in run snapshots and make the CLI fail. ACT rate uses successful
    triage decisions only; triage errors are reported separately, never as SKIP.
    No retries, cache writes, default browser DB or local mandate overlay.
    """
    if runs < 1:
        raise ValueError("runs must be positive")
    profiles = list(PROFILES) if profiles is None else list(profiles)
    if not profiles or len(set(profiles)) != len(profiles) or any(p not in PROFILES for p in profiles):
        raise ValueError("profiles must be distinct known demo profiles")
    if db_path is None:
        raise ValueError("An explicit synthetic --db is required")
    dataset, scenario, signals = load_dataset(db_path)
    if not signals:
        raise ValueError("Synthetic bundle has no signals to evaluate")
    if len(signals) > 20:
        raise ValueError("Evaluation supports at most 20 signals, matching the demo run limit")
    # Validate inputs before constructing any live providers.
    llm = providers.get_llm() if llm is None else llm
    search = providers.get_search() if search is None else search
    snapshots = []
    summaries = []
    # execute() returns the audit trace in its snapshot before temporary cleanup.
    with tempfile.TemporaryDirectory(prefix=".eval-live-", dir=Path(db_path).resolve().parent) as temp:
        for profile in profiles:
            profile_runs = []
            for run in range(1, runs + 1):
                recorder = RecordingLLM(llm)
                snapshot = execute(signals, profile, Path(temp) / f"{profile}-{run}.jsonl",
                                   llm=recorder, search=search)
                snapshot.update(run=run, triage_replies=recorder.triage_replies)
                snapshots.append(snapshot)
                profile_runs.append(snapshot)
            for signal in signals:
                decisions = [d for snapshot in profile_runs for d in snapshot["result"]["decisions"]
                             if d["signal_key"] == signal.key]
                counts = Counter(d["triage"] for d in decisions)
                judged = counts["ACT"] + counts["SKIP"]
                samples = [dict(run=snapshot["run"], text=a["text"])
                           for snapshot in profile_runs for a in snapshot["result"]["actions"]
                           if a["signal_key"] == signal.key]
                summaries.append({"profile": profile, "signal": asdict(signal),
                                  "attempts": runs, "act": counts["ACT"], "skip": counts["SKIP"],
                                  "triage_errors": runs - judged,
                                  "act_rate": counts["ACT"] / judged if judged else None,
                                  "mandate_counts": dict(Counter(d["mandate"]["verdict"] for d in decisions)),
                                  "skill_samples": samples})
    return {"status": "failed" if any(s["status"] != "complete" for s in snapshots) else "complete",
            "dataset": dataset, "scenario": scenario, "runs": runs, "profiles": profiles,
            "signal_count": len(signals), "triage_tier": TRIAGE_TIER,
            "triage_max_tokens": TRIAGE_MAX_TOKENS,
            "act_rate_denominator": "successful ACT + SKIP triage decisions; errors excluded",
            "signals": summaries, "run_results": snapshots}
