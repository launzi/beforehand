"""Every local overlay the code reads has a parseable English example (public-repo safe)."""
from pathlib import Path

from browsing.classify import load_rules
from browsing.mandate import DEFAULT_BASE_PATH, load_mandate

BROWSING = Path(__file__).resolve().parents[1]


def test_examples_exist_parse_and_are_english():
    examples = sorted(p.name for p in BROWSING.glob("*.local.toml.example"))
    assert examples == ["domains.local.toml.example", "mandate.local.toml.example"]
    for name in examples:
        text = (BROWSING / name).read_text(encoding="utf-8")
        assert not any("가" <= ch <= "힣" for ch in text), f"{name} must be English"


def test_examples_load_through_the_real_loaders():
    rules = load_rules(BROWSING / "domains.toml", BROWSING / "domains.local.toml.example")
    assert "finance.test" in rules
    assert load_mandate(DEFAULT_BASE_PATH, BROWSING / "mandate.local.toml.example").error is None
