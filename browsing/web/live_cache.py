"""Produce one LIVE demo cache for an explicit synthetic DB.

Spends money: real Nebius Token Factory, Tavily and Korea Concierge calls. Never called by
the app or tests with real providers. Writes nothing unless all three profiles complete.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from browsing import providers
from browsing.web.app import PROFILES, execute, load_dataset

STAMP = re.compile(r"\d{8}-\d{6}")


def build_live_cache(*, db_path, out, llm=None, search=None, quote_client=None) -> dict:
    out = Path(out)
    if not STAMP.search(out.name):
        raise ValueError("Output file name must contain a YYYYMMDD-HHMMSS timestamp")
    if out.exists():
        raise FileExistsError(f"{out} already exists; live caches are never overwritten")
    if db_path is None:
        raise ValueError("An explicit synthetic --db is required")
    dataset, _, signals = load_dataset(Path(db_path))  # validates the synthetic manifest
    if not signals:
        raise ValueError("Synthetic bundle has no signals")
    llm = providers.get_llm() if llm is None else llm
    search = providers.get_search() if search is None else search
    snapshots = {}
    with tempfile.TemporaryDirectory(prefix=".live-cache-", dir=Path(db_path).resolve().parent) as temp:
        for profile in PROFILES:
            snapshot = execute(signals, profile, Path(temp) / f"{profile}.jsonl",
                               llm=llm, search=search, quote_client=quote_client)
            if snapshot["status"] != "complete" or snapshot["source"] != "live":
                raise RuntimeError(f"Live run failed for {profile}: {snapshot['result']['errors']}")
            snapshots[profile] = snapshot
    cache = {"dataset": dataset, "profiles": snapshots}
    with out.open("x", encoding="utf-8") as stream:
        json.dump(cache, stream, indent=2)
        stream.write("\n")
    return cache
