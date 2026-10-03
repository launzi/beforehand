"""Policy parsing, canonical digests, and deterministic judgments."""

from dataclasses import replace
import hashlib
import json

import pytest

from browsing.agent import SKILLS
from browsing.mandate import DEFAULT_BASE_PATH, evaluate_mandate, load_mandate
from browsing.signals import Signal


BASE = '''allowed_skills = ["unresolved", "new_entry", "recurring", "dropped"]
allow_search = true
require_confirmation = []
'''


@pytest.fixture
def paths(tmp_path):
    base, local = tmp_path / "mandate.toml", tmp_path / "mandate.local.toml"
    base.write_text(BASE, encoding="utf-8")
    return base, local


def signal(kind="unresolved"):
    return Signal(kind, f"{kind}:synthetic", "service.test", "synthetic term", {}, 1, 2)


def test_public_default_allows_all_declared_skills_and_search():
    mandate = load_mandate(DEFAULT_BASE_PATH, None)
    assert mandate.error is None
    assert mandate.allow_search is True
    assert mandate.allowed_skills == frozenset(s.planned_action.skill for s in SKILLS.values())
    for kind, skill in SKILLS.items():
        assert skill.planned_action.signal_kind == kind
        assert evaluate_mandate(mandate, signal(kind), skill.planned_action).verdict == "allow"


def test_absent_local_overlay_is_optional(paths):
    base, local = paths
    assert load_mandate(base, local) == load_mandate(base, None)


def test_local_values_replace_lists_and_preserve_unspecified_fields(paths):
    base, local = paths
    local.write_text('allowed_skills = ["new_entry"]\nrequire_confirmation = ["setup_check"]')
    mandate = load_mandate(base, local)
    assert mandate.error is None
    assert mandate.allowed_skills == frozenset({"new_entry"})
    assert mandate.allow_search is True
    assert mandate.require_confirmation == frozenset({"setup_check"})


def test_empty_overlay_list_replaces_base_restrictions(paths):
    base, local = paths
    base.write_text(BASE.replace("require_confirmation = []", 'require_confirmation = ["setup_check"]'))
    local.write_text('require_confirmation = []\nallowed_skills = []')
    mandate = load_mandate(base, local)
    assert mandate.require_confirmation == frozenset()
    assert mandate.allowed_skills == frozenset()


def test_canonical_digest_ignores_order_case_duplicates_and_formatting(paths):
    base, local = paths
    original = load_mandate(base, None)
    local.write_text('allowed_skills = [" DROPPED ", "recurring", "UNRESOLVED", "new_entry", "new_entry"]')
    normalized = load_mandate(base, local)
    assert normalized == original
    expected = json.dumps({
        "schema_version": 1, "allowed_skills": sorted(original.allowed_skills),
        "allow_search": True, "require_confirmation": [], "error": None,
    }, sort_keys=True, separators=(",", ":"))
    assert normalized.digest == hashlib.sha256(expected.encode()).hexdigest()


@pytest.mark.parametrize("overlay", [
    'allow_search = false', 'allowed_skills = []',
    'require_confirmation = ["setup_check"]',
])
def test_digest_changes_when_policy_changes(paths, overlay):
    base, local = paths
    before = load_mandate(base, None)
    local.write_text(overlay)
    assert load_mandate(base, local).digest != before.digest


@pytest.mark.parametrize("layer", ["base", "local"])
@pytest.mark.parametrize("bad, reason", [
    ('allowed_skills = [', "parsing failed"),
    ('allow_search = "false"', "boolean"),
    ('allow_search = 1', "boolean"),
    ('allowed_skills = "unresolved"', "list"),
    ('allowed_skills = [3]', "list"),
    ('require_confirmation = [""]', "non-empty"),
    ('require_confirmation = ["   "]', "non-empty"),
    ('allow_serach = true', "unknown fields"),
    ('[unexpected]\nallow_search = true', "unknown fields"),
])
def test_bad_configuration_fails_closed(paths, layer, bad, reason):
    base, local = paths
    path = base if layer == "base" else local
    # Full base schema, replacing the corresponding field for type errors.
    if layer == "base" and "=" in bad and not bad.startswith("["):
        key = bad.split("=", 1)[0].strip()
        path.write_text("\n".join(line for line in BASE.splitlines() if not line.startswith(key + " =")) + "\n" + bad)
    else:
        path.write_text(bad)
    mandate = load_mandate(base, local)
    assert mandate.error and layer in mandate.error and reason in mandate.error
    assert mandate.allow_search is False
    assert mandate.allowed_skills == frozenset()
    decision = evaluate_mandate(mandate, signal(), SKILLS["unresolved"].planned_action)
    assert decision.verdict == "deny"
    assert "Invalid mandate" in decision.reason
    assert decision.mandate_digest == mandate.digest


@pytest.mark.parametrize("field", ["allowed_skills", "allow_search", "require_confirmation"])
def test_base_requires_every_field_even_if_overlay_supplies_it(paths, field):
    base, local = paths
    base.write_text("\n".join(line for line in BASE.splitlines() if not line.startswith(field)))
    local.write_text(BASE)
    assert "missing fields" in load_mandate(base, local).error


def test_missing_base_cannot_be_repaired_by_valid_local(paths):
    base, local = paths
    base.unlink()
    local.write_text(BASE)
    mandate = load_mandate(base, local)
    assert "base: required mandate file missing" == mandate.error
    assert evaluate_mandate(mandate, signal(), None).verdict == "deny"


@pytest.mark.parametrize("layer", ["base", "local"])
def test_unreadable_or_non_utf8_policy_fails_closed(paths, layer):
    base, local = paths
    path = base if layer == "base" else local
    path.write_bytes(b"\xff\xfe")
    assert "parsing failed" in load_mandate(base, local).error
    path.unlink()
    path.mkdir()
    assert "unreadable" in load_mandate(base, local).error


@pytest.mark.parametrize("overlay, kind, expected, reason", [
    ('allowed_skills = []', "unresolved", "deny", "not allowed"),
    ('allow_search = false', "unresolved", "deny", "search"),
    ('allow_search = false', "new_entry", "allow", "within"),
    ('require_confirmation = ["research_briefing"]', "unresolved", "hold", "confirmation"),
    ('require_confirmation = ["setup_check"]', "new_entry", "hold", "confirmation"),
    ('allow_search = false\nrequire_confirmation = ["research_briefing"]', "unresolved", "deny", "search"),
    ('allowed_skills = []\nrequire_confirmation = ["setup_check"]', "new_entry", "deny", "not allowed"),
])
def test_rule_precedence_and_determinism(paths, overlay, kind, expected, reason):
    base, local = paths
    local.write_text(overlay)
    mandate = load_mandate(base, local)
    plan = SKILLS[kind].planned_action
    decisions = [evaluate_mandate(mandate, signal(kind), plan) for _ in range(3)]
    assert decisions[0] == decisions[1] == decisions[2]
    assert decisions[0].verdict == expected
    assert reason in decisions[0].reason


def test_unknown_and_mismatched_skill_are_denied(paths):
    mandate = load_mandate(*paths)
    assert evaluate_mandate(mandate, signal(), None).verdict == "deny"
    plan = replace(SKILLS["unresolved"].planned_action, signal_kind="new_entry")
    assert evaluate_mandate(mandate, signal(), plan).verdict == "deny"


def test_skills_declare_actual_provider_usage():
    for kind, skill in SKILLS.items():
        assert skill.planned_action.uses_llm is True
        assert skill.planned_action.uses_search is (kind == "unresolved")
