"""
Spec-driven code generation loop.

A model writes code from a written spec. The code is run against a test suite.
If it fails, the failure output and the previous attempt go back to the model,
which tries again — and is also asked which part of the spec was ambiguous,
so the spec itself can be improved.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Round:
    index: int          # 1-based
    code: str           # generated code with the feedback marker stripped
    passed: int
    failed: int
    output: str         # test output


@dataclass
class LoopResult:
    ok: bool
    rounds: list[Round]
    spec_feedback: list[str]
    best: Round | None


def choose_best(rounds: list[Round]) -> Round | None:
    """Return the best round by most passed, then fewest failed, then earliest index."""
    if not rounds:
        return None
    return min(
        rounds,
        key=lambda r: (-r.passed, r.failed, r.index)
    )


def extract_spec_feedback(text: str) -> str:
    """
    Find SPEC_FEEDBACK: marker and return everything after it, stripped.
    Handles single trailing line or multi-line block. Returns "" when absent.
    """
    match = re.search(r'SPEC_FEEDBACK:\s*(.*)', text, re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _strip_feedback_marker(code: str) -> tuple[str, str]:
    """
    Remove SPEC_FEEDBACK marker and everything after it from code.
    Returns (clean_code, feedback).
    """
    feedback = extract_spec_feedback(code)
    if not feedback:
        return code, ""
    # Find the marker position and cut everything from there
    marker_pos = code.find("SPEC_FEEDBACK:")
    clean_code = code[:marker_pos].rstrip()
    return clean_code, feedback


def run_loop(
    spec_path: Path,
    out_path: Path,
    *,
    generate: Callable[[str], str],
    run_tests: Callable[[Path], tuple[int, int, str]],
    max_rounds: int = 3,
) -> LoopResult:
    """
    Run the generation loop.

    Args:
        spec_path: Path to the spec file.
        out_path: Path where each round's code is written for testing.
        generate: Callable that takes a prompt and returns generated code.
        run_tests: Callable that takes the output path and returns (passed, failed, output).
        max_rounds: Maximum number of rounds to attempt.

    Returns:
        LoopResult with outcome, all rounds, collected spec feedback, and best round.
    """
    # 1. Read the spec
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as e:
        raise ValueError(f"Cannot read spec file: {e}") from e

    if not spec_text.strip():
        raise ValueError("Spec file is empty")

    rounds: list[Round] = []
    spec_feedback: list[str] = []

    for round_idx in range(1, max_rounds + 1):
        # Build prompt
        if round_idx == 1:
            prompt = spec_text
        else:
            prev_round = rounds[-1]
            prompt = (
                f"{spec_text}\n\n"
                f"PREVIOUS ATTEMPT\n"
                f"Code:\n{prev_round.code}\n\n"
                f"Test output:\n{prev_round.output}\n\n"
                f"Return corrected code only. "
                f"At the very end, append a line or block starting with "
                f"`SPEC_FEEDBACK:` naming which part of the spec was ambiguous or missing. "
                f"Write \"SPEC_FEEDBACK: none\" when the spec was clear and the mistake was your own."
            )

        # Generate code
        try:
            raw_code = generate(prompt)
        except Exception as e:
            raw_code = ""
            test_output = f"Generation failed: {e}"
            passed, failed = 0, 1
        else:
            # Strip feedback marker
            clean_code, feedback = _strip_feedback_marker(raw_code)

            # Write code to out_path for testing
            try:
                out_path.write_text(clean_code, encoding="utf-8")
            except OSError as e:
                test_output = f"Failed to write output file: {e}"
                passed, failed = 0, 1
            else:
                # Run tests
                try:
                    passed, failed, test_output = run_tests(out_path)
                except Exception as e:
                    passed, failed, test_output = 0, 1, f"Test runner crashed: {e}"

            # Collect spec feedback
            if feedback and feedback.lower() != "none":
                spec_feedback.append(feedback)

            raw_code = clean_code  # for recording

        # Record round
        round_obj = Round(
            index=round_idx,
            code=raw_code if 'clean_code' in locals() else "",
            passed=passed if 'passed' in locals() else 0,
            failed=failed if 'failed' in locals() else 1,
            output=test_output if 'test_output' in locals() else "Generation failed before test",
        )
        rounds.append(round_obj)

        # Stop if passed > 0 and failed == 0
        if round_obj.passed > 0 and round_obj.failed == 0:
            break

    # Determine best round and write it to out_path
    best = choose_best(rounds)
    if best is not None:
        try:
            out_path.write_text(best.code, encoding="utf-8")
        except OSError:
            pass  # Best effort; result already captured

    # Overall ok: some round had passed > 0 and failed == 0
    ok = any(r.passed > 0 and r.failed == 0 for r in rounds)

    return LoopResult(
        ok=ok,
        rounds=rounds,
        spec_feedback=spec_feedback,
        best=best,
    )


# ============================================================
# CLI wiring
# ============================================================

def _resolve_nebius_cli() -> Path:
    """Resolve the Nebius CLI path, trying known locations."""
    candidates = []

    env_cli = os.environ.get("NEBIUS_CLI")
    if env_cli:
        candidates.append(Path(env_cli).expanduser())

    candidates.append(Path("~/claude/tools/nebius.py").expanduser())
    candidates.append(Path("~/Desktop/claude/tools/nebius.py").expanduser())

    for c in candidates:
        if c.is_file():
            return c

    tried = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"Nebius CLI not found. Tried:\n  {tried}")


def _generate_cli(prompt: str, tier: str) -> str:
    """Generate code by calling the Nebius CLI with a temporary spec file."""
    cli_path = _resolve_nebius_cli()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(prompt)
        spec_file = f.name

    try:
        cmd = [
            sys.executable, str(cli_path), "code", spec_file,
            "--tier", tier,
            "--max-tokens", "20000",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        # Exit code 2 means truncated/empty response
        if result.returncode == 2:
            raise RuntimeError("Nebius CLI returned empty/truncated response (exit 2)")
        if result.returncode != 0:
            raise RuntimeError(f"Nebius CLI failed (exit {result.returncode}): {result.stderr.strip()}")
        return result.stdout
    finally:
        try:
            os.unlink(spec_file)
        except OSError:
            pass


def _run_tests_cli(test_path: Path) -> tuple[int, int, str]:
    """Run pytest on the test file and parse passed/failed counts."""
    cmd = [
        sys.executable, "-m", "pytest",
        str(test_path),
        "-v", "--tb=short",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired as e:
        return 0, 1, f"Test timeout: {e}"
    except Exception as e:
        return 0, 1, f"Test runner error: {e}"

    # Parse pytest summary line: "X passed, Y failed, Z error, ..."
    # Also handle "X passed, Y failed" or collection errors
    passed_match = re.search(r'(\d+)\s+passed', output)
    failed_match = re.search(r'(\d+)\s+failed', output)
    error_match = re.search(r'(\d+)\s+error', output)

    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    errors = int(error_match.group(1)) if error_match else 0

    # Treat errors as failures for our purposes
    failed += errors

    # Collection error or internal error often shows as 0 passed, 0 failed
    # but with traceback in output - that's not a pass
    return passed, failed, output.strip()


def _print_summary(result: LoopResult) -> None:
    """Print a summary of the loop run."""
    print("=== Loop Summary ===")
    for r in result.rounds:
        status = "PASS" if (r.passed > 0 and r.failed == 0) else "FAIL"
        print(f"  Round {r.index}: {r.passed} passed, {r.failed} failed [{status}]")
        if r.code == "":
            print(f"    (no code generated)")
    if result.best:
        print(f"\nKept: Round {result.best.index} ({result.best.passed} passed, {result.best.failed} failed)")
    else:
        print("\nKept: (none)")
    if result.spec_feedback:
        print("\nSpec feedback collected:")
        for i, fb in enumerate(result.spec_feedback, 1):
            print(f"  {i}. {fb}")
    else:
        print("\nSpec feedback: (none)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Spec-driven code generation loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--spec", required=True, type=Path, help="Spec file (Markdown)")
    parser.add_argument("--out", required=True, type=Path, help="Output module file")
    parser.add_argument("--tests", required=True, type=Path, help="Test file for pytest")
    parser.add_argument("--tier", default="ultra", help="Model tier (default: ultra)")
    parser.add_argument("--max-rounds", type=int, default=3, help="Maximum rounds (default: 3)")
    args = parser.parse_args()

    # Validate inputs
    if not args.spec.is_file():
        print(f"Spec file not found: {args.spec}", file=sys.stderr)
        return 2
    if not args.tests.is_file():
        print(f"Test file not found: {args.tests}", file=sys.stderr)
        return 2

    # Wire up the injected functions
    def generate(prompt: str) -> str:
        return _generate_cli(prompt, args.tier)

    def run_tests(code_path: Path) -> tuple[int, int, str]:
        return _run_tests_cli(args.tests)

    # Run the loop
    try:
        result = run_loop(
            spec_path=args.spec,
            out_path=args.out,
            generate=generate,
            run_tests=run_tests,
            max_rounds=args.max_rounds,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    _print_summary(result)
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
