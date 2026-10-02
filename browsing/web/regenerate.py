"""Rebuild the fictional maker walkthrough without real providers or browser data."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from browsing.agent import TRIAGE_SYSTEM
from browsing.persona.generate import DEFAULT_SCENARIO, load_scenario, populate
from browsing.web.app import PROFILES, ROOT, execute


def scripted_visits(scenario: dict) -> dict:
    """Fixed maker story; hostnames, search term and story dates come from TOML."""
    entries = [s for s in scenario["signals"] if s["kind"] == "new_entry"]
    others = {kind: [s for s in scenario["signals"] if s["kind"] == kind]
              for kind in ("dropped", "recurring", "unresolved")}
    if len(entries) != 2 or any(len(items) != 1 for items in others.values()):
        raise ValueError("Scripted maker story requires two new entries and one of each other kind")
    end = datetime.fromisoformat(scenario["until"])
    visits = []

    def add(host, path, title, days, hour=10, **extra):
        at = end - timedelta(days=days) + timedelta(hours=hour)
        visits.append({"url": f"https://{host}{path}", "title": title,
                       "at": at.isoformat(), **extra})

    dropped = others["dropped"][0]["host"]
    for days, title in ((29, "Explore project ideas"), (27, "Continue the project"),
                        (25, "Last project session")):
        add(dropped, "/explore", title, days)
    recurring = others["recurring"][0]["host"]
    for days, path, title in ((11, "/3/tutorial/", "Python tutorial"),
                              (7, "/3/library/", "Python library"),
                              (2, "/3/tutorial/", "Return to Python")):
        add(recurring, path, title, days)
    add(entries[0]["host"], "/signup", "Start workspace signup", 3, 12)
    add(entries[1]["host"], "/onboarding", "Start design onboarding", 2, 12)
    term = others["unresolved"][0]["term"]
    add("www.google.com", "/search?" + urlencode({"q": term}),
        "Compare static site generators", 1, 12, search_term=term)
    return {"visits": visits}


class ScriptedLLM:
    def complete(self, prompt, **kwargs):
        if kwargs.get("system") == TRIAGE_SYSTEM:
            return "ACT"
        for marker, reply in (
            ("gone quiet", "Illustrative nudge: is the paused project still relevant?"),
            ("initial setup", "Illustrative suggestion: review the next setup step; a signup visit alone does not prove completion."),
            ("through-line", "Illustrative summary: repeated visits suggest continued learning on this host."),
            ("Search hits:", "Illustrative briefing: compare build steps and hosting before choosing a static site generator."),
        ):
            if marker in prompt:
                return reply
        raise ValueError("Unexpected prompt in scripted walkthrough")


class ScriptedSearch:
    def search(self, query, limit=5):
        return [{"title": "Illustrative Python documentation result",
                 "url": "https://docs.python.org/3/",
                 "snippet": "Scripted example only; no search request was made."}][:limit]


def regenerate_fixtures(*, scenario_path=DEFAULT_SCENARIO, output_dir=ROOT / "fixtures"):
    scenario = load_scenario(scenario_path)
    payload = scripted_visits(scenario)
    source = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    with closing(sqlite3.connect(":memory:")) as conn:
        signals = populate(conn, payload, scenario)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    # All intermediate traces stay inside the requested destination and are removed.
    with tempfile.TemporaryDirectory(prefix=".regenerate-", dir=output_dir) as temporary:
        for profile in PROFILES:
            snapshot = execute(signals, profile, Path(temporary) / f"{profile}.jsonl",
                               llm=ScriptedLLM(), search=ScriptedSearch())
            if snapshot["status"] != "complete":
                raise ValueError(f"Scripted pipeline failed for {profile}: {snapshot['result']['errors']}")
            snapshot["source"] = "illustrative-fixture"
            snapshots[profile] = snapshot
    cache = {"dataset": hashlib.sha256(source).hexdigest(), "profiles": snapshots}
    # Do not replace either published fixture until every profile has succeeded.
    (output_dir / "visits.json").write_bytes(source)
    (output_dir / "cache.json").write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    return cache
