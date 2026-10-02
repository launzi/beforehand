"""
Local-only tracing for the agent loop.

Traces stay on the machine. Nothing is sent anywhere.
Events are written as JSON Lines to a local file under the user's home directory.
"""

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Tracer:
    """Local-only tracer that writes JSON Lines to a file."""

    def __init__(self, path: Optional[Path] = None, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._path: Optional[Path] = None
        self._file = None

        if not enabled:
            return

        if path is None:
            # Compute default path at call time so tests can redirect HOME
            home = Path.home()
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = home / ".browsing" / "traces" / f"{date_str}.jsonl"

        self._path = Path(path)
        # Create parent directories as needed
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Open file in append mode, line-buffered via explicit flush
        self._file = self._path.open("a", encoding="utf-8")

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def _serialize(self, obj: Any) -> Any:
        """Attempt to serialize obj to JSON, falling back to repr for non-serializable values."""
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return repr(obj)

    def _write_event(self, event: dict, *, strict: bool = False) -> None:
        """Write JSONL; policy audit records must surface I/O failures."""
        if not self._enabled or self._file is None:
            return

        # Serialize all fields, falling back on non-serializable values
        safe_event = {k: self._serialize(v) for k, v in event.items()}

        try:
            line = json.dumps(safe_event, ensure_ascii=False)
            self._file.write(line + "\n")
            self._file.flush()
        except OSError:
            if strict:
                raise
            # File I/O failure — give up on this event but don't crash the run
            pass

    def close(self) -> None:
        if self._file is not None:
            self._file.close()

    def decision(self, *, signal_key: str, signal_kind: str, triage: str,
                 mandate_digest: str, verdict: str, reason: str, executed: bool,
                 execution_status: str, planned_action: dict | None,
                 execution_error: str | None) -> None:
        """Record mandate judgments locally; never disguise a failed audit write."""
        self._write_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": "mandate_decision",
            "signal_key": signal_key, "signal_kind": signal_kind,
            "triage": triage, "planned_action": planned_action,
            "mandate_digest": mandate_digest, "verdict": verdict, "reason": reason,
            "executed": executed, "execution_status": execution_status,
            "execution_error": execution_error,
        }, strict=True)

    def event(self, _kind: str, /, **fields) -> None:
        """Write a single event with timestamp and kind."""
        if not self._enabled:
            return

        # 이벤트 종류는 첫 인자가 이긴다. 사용자가 넘긴 kind 는 잃지 않고 옮긴다 —
        # 신호를 기록하려면 그 신호의 kind 를 쓰게 되는데, 그게 죽으면 안 된다.
        if "kind" in fields:
            fields["user_kind"] = fields.pop("kind")

        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": _kind,
            **fields,
        }
        self._write_event(event)

    @contextmanager
    def span(self, _kind: str, /, **fields):
        """
        Context manager that times a block and writes one event on exit.

        The emitted event carries the original fields plus:
          - duration_ms: float
          - ok: bool
          - error: str (only when the block raised)
        On failure the event is recorded and the exception is re-raised.
        """
        if not self._enabled:
            yield
            return

        start = time.perf_counter()
        ok = True
        error: Optional[str] = None
        try:
            yield
        except Exception as e:
            ok = False
            error = repr(e)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            if "kind" in fields:
                fields["user_kind"] = fields.pop("kind")
            event = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": _kind,
                "duration_ms": duration_ms,
                "ok": ok,
                **fields,
            }
            if not ok:
                event["error"] = error  # type: ignore[assignment]
            self._write_event(event)


def disable_external_tracing() -> None:
    """
    Disable external tracing by setting tracing switches to "false"
    and clearing API keys so no other code path can pick them up.
    """
    for var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
        os.environ[var] = "false"

    for var in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        os.environ[var] = ""
