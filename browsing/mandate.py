"""Deterministic delegation policy. No provider calls belong in this module.

The public TOML is required; an absent local overlay is optional. Overlay fields
replace base fields (including entire lists). Invalid input produces an explicit
invalid, deny-all policy, never a permissive fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Callable, Literal

from browsing.signals import Signal


DEFAULT_BASE_PATH = Path(__file__).with_name("mandate.toml")
DEFAULT_LOCAL_PATH = Path(__file__).with_name("mandate.local.toml")
_FIELDS = {"allowed_skills", "allow_search", "require_confirmation"}


@dataclass(frozen=True, slots=True)
class PlannedAction:
    skill: str
    signal_kind: str
    action_kind: str
    uses_search: bool
    uses_llm: bool


def declares_action(plan: PlannedAction):
    """Attach the declaration to the skill itself, preserving its call API."""
    def decorate(skill: Callable) -> Callable:
        skill.planned_action = plan
        return skill
    return decorate


@dataclass(frozen=True, slots=True)
class Mandate:
    allowed_skills: frozenset[str]
    allow_search: bool
    require_confirmation: frozenset[str]
    error: str | None = None

    @property
    def digest(self) -> str:
        """SHA-256 of versioned canonical JSON, independent of TOML formatting."""
        normalized = {
            "schema_version": 1,
            "allowed_skills": sorted(self.allowed_skills),
            "allow_search": self.allow_search,
            "require_confirmation": sorted(self.require_confirmation),
            "error": self.error,
        }
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MandateDecision:
    verdict: Literal["allow", "hold", "deny"]
    reason: str
    mandate_digest: str


def _validate(data: dict, *, source: str, partial: bool = False) -> dict:
    unknown = data.keys() - _FIELDS
    if unknown:
        raise ValueError(f"{source}: unknown fields: {', '.join(sorted(unknown))}")
    if not partial and _FIELDS - data.keys():
        raise ValueError(f"{source}: missing fields: {', '.join(sorted(_FIELDS - data.keys()))}")
    normalized = {}
    for name, value in data.items():
        if name == "allow_search":
            if not isinstance(value, bool):
                raise ValueError(f"{source}: allow_search must be a boolean")
            normalized[name] = value
        else:
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ValueError(f"{source}: {name} must be a list of non-empty strings")
            normalized[name] = frozenset(item.strip().lower() for item in value)
    return normalized


def _read(path: Path, *, source: str, optional: bool = False) -> dict:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError as exc:
        if optional:
            return {}
        raise ValueError(f"{source}: required mandate file missing") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        # Do not echo potentially private configuration contents into the reason.
        raise ValueError(f"{source}: mandate TOML parsing failed ({type(exc).__name__})") from exc
    except OSError as exc:
        raise ValueError(f"{source}: mandate file unreadable ({type(exc).__name__})") from exc
    return _validate(data, source=source, partial=optional)


def load_mandate(
    base_path: Path = DEFAULT_BASE_PATH,
    local_path: Path | None = DEFAULT_LOCAL_PATH,
) -> Mandate:
    """Load one immutable policy snapshot; expose any load failure as deny-all.

    Pass local_path=None to deliberately use only the public/base configuration.
    A missing optional overlay is the only tolerated file absence.
    """
    try:
        base = _read(Path(base_path), source="base")
        overlay = {} if local_path is None else _read(Path(local_path), source="local", optional=True)
        return Mandate(**{**base, **overlay})
    except ValueError as exc:
        return Mandate(frozenset(), False, frozenset(), error=str(exc))


def evaluate_mandate(
    mandate: Mandate, signal: Signal, plan: PlannedAction | None,
) -> MandateDecision:
    """Deny overrides hold; triage enthusiasm cannot grant authorization."""
    verdict = "allow"
    reason = "Action is within the configured mandate"
    if plan is not None and plan.action_kind == "commerce.checkout":
        verdict, reason = "deny", "Checkout is out of scope for this build"
    elif mandate.error is not None:
        verdict, reason = "deny", f"Invalid mandate: {mandate.error}"
    elif plan is None:
        verdict, reason = "deny", "No declared skill for signal kind"
    elif signal.kind != plan.signal_kind:
        verdict, reason = "deny", "Signal kind does not match the skill declaration"
    elif plan.skill not in mandate.allowed_skills:
        verdict, reason = "deny", f"Skill '{plan.skill}' is not allowed"
    elif plan.action_kind == "commerce.quote" and not mandate.allow_search:
        verdict, reason = "deny", "External commerce quotes are not allowed"
    elif plan.uses_search and not mandate.allow_search:
        verdict, reason = "deny", "External search provider calls are not allowed"
    elif plan.action_kind in mandate.require_confirmation:
        verdict, reason = "hold", f"Action '{plan.action_kind}' requires user confirmation"
    return MandateDecision(verdict, reason, mandate.digest)
