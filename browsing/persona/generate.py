"""Generate into the existing ingest schema; publish only fully validated output."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import tomllib
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from browsing import providers
from browsing.ingest import ingest_records, init_db
from browsing.signals import _chrome_us_from_iso, detect_all

DEFAULT_SCENARIO = Path(__file__).parent / "scenarios" / "maker.toml"


class GenerationError(ValueError):
    """Invalid generated data or exhausted signal-validation attempts."""


def load_scenario(path: Path) -> dict:
    with Path(path).open("rb") as stream:
        scenario = tomllib.load(stream)
    if scenario.get("fictional") is not True:
        raise ValueError("Scenario must explicitly declare fictional = true")
    window = detector_window(scenario)
    if window["since_us"] >= window["until_us"]:
        raise ValueError("Scenario must have an increasing time window")
    hosts = scenario["allowed_hosts"]
    if not hosts or any(not isinstance(h, str) or "/" in h or "@" in h for h in hosts):
        raise ValueError("allowed_hosts must contain public host names")
    expected = scenario["signals"]
    counts = Counter(item["kind"] for item in expected)
    if counts["new_entry"] < 2 or any(counts[k] < 1 for k in ("unresolved", "dropped", "recurring")):
        raise ValueError("Scenario needs two new entries and each other signal kind")
    identities = set()
    for item in expected:
        kind = item["kind"]
        if kind not in {"new_entry", "unresolved", "dropped", "recurring", "korea_product"}:
            raise ValueError("Unknown signal kind")
        identifier = item["term"].strip().lower() if kind == "unresolved" else item["host"]
        if not identifier or (kind != "unresolved" and identifier not in hosts):
            raise ValueError("Signal identifier must be nonempty and host allowlisted")
        if (kind, identifier) in identities:
            raise ValueError("Expected signals must have distinct identities")
        identities.add((kind, identifier))
    return scenario


def detector_window(scenario: dict) -> dict:
    for key in ("since", "until"):
        if datetime.fromisoformat(scenario[key]).tzinfo is None:
            raise ValueError("Scenario timestamps require a timezone")
    return {"since_us": _chrome_us_from_iso(scenario["since"]),
            "until_us": _chrome_us_from_iso(scenario["until"]),
            "now_us": _chrome_us_from_iso(scenario["until"])}


def records_from_payload(payload: dict, scenario: dict) -> list[dict]:
    """Convert strict fictional visit JSON into the existing ingest record format."""
    if not isinstance(payload, dict) or set(payload) != {"visits"}:
        raise GenerationError("Expected an object with only a visits array")
    visits = payload["visits"]
    if not isinstance(visits, list) or not 1 <= len(visits) <= 300:
        raise GenerationError("Expected 1 to 300 visits")
    window = detector_window(scenario)
    records = []
    for visit in visits:
        if not isinstance(visit, dict) or not {"url", "title", "at"} <= visit.keys():
            raise GenerationError("Visit needs url, title, at")
        if visit.keys() - {"url", "title", "at", "search_term"}:
            raise GenerationError("Unexpected visit fields")
        if any(not isinstance(visit[k], str) or not visit[k].strip() for k in visit):
            raise GenerationError("Visit values must be nonempty strings")
        url = urlsplit(visit["url"])
        if url.scheme != "https" or url.hostname not in scenario["allowed_hosts"] or url.username or url.password or url.port:
            raise GenerationError("Only HTTPS URLs on scenario public hosts are allowed")
        if len(visit["url"]) > 2048 or len(visit["title"]) > 300 or len(visit.get("search_term", "")) > 200:
            raise GenerationError("Visit text exceeds limits")
        dt = datetime.fromisoformat(visit["at"])
        if dt.tzinfo is None:
            raise GenerationError("Visit timestamps require a timezone")
        us = _chrome_us_from_iso(visit["at"])
        if not window["since_us"] <= us < window["until_us"]:
            raise GenerationError("Visit timestamp outside scenario window")
        records.append({"kind": "visit", "profile": "synthetic", "url": visit["url"],
                        "title": visit["title"], "visit_time_us": us,
                        "transition": 1, "duration_us": 30_000_000})
        if "search_term" in visit:
            records.append({"kind": "search", "profile": "synthetic", "url": visit["url"],
                            "term": visit["search_term"], "first_seen_us": us})
    return records


def populate(conn: sqlite3.Connection, payload: dict, scenario: dict) -> list:
    records = records_from_payload(payload, scenario)
    init_db(conn)
    counts = ingest_records(conn, records)
    if counts["skipped"] or counts["deduped"]:
        raise GenerationError(f"Ingest rejected records: {counts}")
    conn.commit()
    signals = detect_all(conn, **detector_window(scenario), profile="synthetic")
    found = {(s.kind, s.term if s.kind == "unresolved" else s.host) for s in signals}
    missing = [(s["kind"], s.get("term", s.get("host", "")).strip().lower())
               for s in scenario["signals"]
               if (s["kind"], s.get("term", s.get("host", "")).strip().lower()) not in found]
    if missing:
        raise GenerationError(f"Missing required signals: {missing}")
    return signals


def generate(scenario_path: Path, out: Path, *, llm=None, attempts: int = 3) -> dict:
    """Provider errors propagate immediately; invalid output retries at most attempts."""
    if not 1 <= attempts <= 10:
        raise ValueError("attempts must be between 1 and 10")
    scenario = load_scenario(scenario_path)
    out = Path(out)
    manifest_path = out.with_suffix(out.suffix + ".json")
    if out.exists() or manifest_path.exists():
        raise FileExistsError("Refusing to overwrite an existing output bundle")
    llm = providers.get_llm() if llm is None else llm
    prompt = (
        "Invent browsing history for this entirely fictional scenario. No real people, "
        "personal identifiers, credentials, email addresses, or copied history. Public services only. "
        "Use exactly these hostnames from scenario.allowed_hosts for every HTTPS URL. "
        "Do not add or remove www., substitute bare domains, or use other subdomains. "
        "Return strict JSON only: {\"visits\":[{\"url\":\"https://...\",\"title\":\"...\","
        "\"at\":\"ISO-8601 with timezone\",\"search_term\":\"optional search text\"}]}. "
        "Use distinct timestamps inside [since, until). Include every planted signal. "
        "New entries need a /signup or /onboarding path. Recurring needs >=3 distinct days. "
        "Dropped needs >=3 distinct days and no visits in the final 7 days. "
        "Unresolved needs a search_term with <3 other-host visits in the next 30 minutes. "
        "Do not repeat identical visits. Keep 15-50 visits. Scenario:\n" + json.dumps(scenario)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    failure = ""
    for attempt in range(1, attempts + 1):
        # Keep this outside the validation catch: network/provider errors are not missing signals.
        reply = llm.complete(prompt + "\nPrevious validation failure: " + failure,
                             tier="super", max_tokens=12000,
                             system="You create fictional, non-identifying demo data. Output JSON only.")
        try:
            payload = json.loads(reply)
            with closing(sqlite3.connect(":memory:")) as conn:
                signals = populate(conn, payload, scenario)
                with tempfile.TemporaryDirectory(prefix=".persona-", dir=out.parent) as tmp:
                    staged = Path(tmp) / "browsing.db"
                    with closing(sqlite3.connect(staged)) as target:
                        conn.backup(target)
                    manifest = {"synthetic": True, "source": "llm-generated-and-validated",
                                "scenario": scenario, "attempts": attempt,
                                "signal_keys": [s.key for s in signals],
                                "sha256": hashlib.sha256(staged.read_bytes()).hexdigest()}
                    staged_manifest = Path(tmp) / "manifest.json"
                    staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
                    # Link is no-clobber; unlike replace it cannot overwrite a competing writer.
                    os.link(staged, out)
                    try:
                        os.link(staged_manifest, manifest_path)
                    except BaseException:
                        out.unlink()
                        raise
            return manifest
        except (ValueError, TypeError, KeyError) as exc:
            failure = str(exc)
    raise GenerationError(f"Validation failed after {attempts} attempts: {failure}")
