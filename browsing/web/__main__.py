"""Export successful demo runs or regenerate the offline scripted walkthrough."""
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
    regenerate = sub.add_parser("regenerate-fixtures", help="Rebuild the maker example using fake providers only")
    from browsing.persona.generate import DEFAULT_SCENARIO
    from browsing.web.app import ROOT
    regenerate.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    regenerate.add_argument("--output-dir", type=Path, default=ROOT / "fixtures")
    evaluate = sub.add_parser("eval-live", help="Call live providers on an explicit validated synthetic DB")
    evaluate.add_argument("--db", type=Path, required=True)
    evaluate.add_argument("--runs", type=int, default=3)
    evaluate.add_argument("--profile", choices=tuple(PROFILES), action="append",
                          help="Repeat for selected profiles; default: all three")
    args = parser.parse_args()
    if args.command == "regenerate-fixtures":
        from browsing.web.regenerate import regenerate_fixtures
        regenerate_fixtures(scenario_path=args.scenario, output_dir=args.output_dir)
    elif args.command == "eval-live":
        if args.runs < 1:
            parser.error("--runs must be positive")
        from browsing.web.eval_live import evaluate_live
        result = evaluate_live(db_path=args.db, runs=args.runs, profiles=args.profile)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "complete":
            raise SystemExit(1)
    else:
        export_cache(db_path=args.db, state_dir=args.state, out=args.out)


if __name__ == "__main__":
    main()
