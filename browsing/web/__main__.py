"""Export previously successful demo runs without invoking any provider."""
import argparse
import json
from pathlib import Path

from browsing.mandate import load_mandate
from browsing.web.app import PROFILES, load_dataset
from browsing.web.store import RunStore


def export_cache(*, db_path, state_dir, out):
    dataset, _, _ = load_dataset(db_path)
    if not (Path(state_dir) / "runs.sqlite3").is_file():
        raise FileNotFoundError("No stored runs to export")
    store = RunStore(state_dir)
    snapshots = {}
    for profile, path in PROFILES.items():
        snapshot = store.get(dataset, profile)
        if snapshot is None or snapshot["status"] != "complete":
            raise ValueError(f"No successful cached run for {profile}; run it first")
        if snapshot["mandate_digest"] != load_mandate(path, None).digest:
            raise ValueError(f"Stale mandate for {profile}; rerun it first")
        snapshots[profile] = snapshot
    with Path(out).open("x", encoding="utf-8") as stream:
        json.dump({"dataset": dataset, "profiles": snapshots}, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export-cache")
    export.add_argument("--db", type=Path)
    export.add_argument("--state", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    export_cache(db_path=args.db, state_dir=args.state, out=args.out)


if __name__ == "__main__":
    main()
