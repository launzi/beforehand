import argparse
import json
from pathlib import Path

from .generate import generate


def main():
    parser = argparse.ArgumentParser(description="Generate and validate an entirely synthetic browsing DB")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("generate")
    command.add_argument("--scenario", required=True, type=Path)
    command.add_argument("--out", required=True, type=Path)
    command.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(generate(args.scenario, args.out, attempts=args.attempts), indent=2))


if __name__ == "__main__":
    main()
