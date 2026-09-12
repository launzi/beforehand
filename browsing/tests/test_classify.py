"""분류 계약 테스트 — 호스트 → (category, sensitivity), 2층 룰.

정본은 설계 스펙 6절. 핵심 제약 두 가지를 여기서 고정한다.

  1. 기본 룰(공개)과 로컬 오버레이(git 제외)가 분리되고, 로컬이 이긴다
  2. **로컬 파일이 없어도 동작한다** — 없으면 못 도는 구조면 추상화가 안 된 것이다

⚠ 합성 도메인만 쓴다. 사용자 실제 업무·금융·채용 호스트를 이 파일에 적지 않는다.
"""

import pytest

from browsing.classify import classify_host, load_rules

BASE_TOML = """
# 기본 룰 — 누구에게나 해당하는 공개 서비스만 둔다.
[ai-tools]
sensitivity = "none"
hosts = ["claude.ai", "chatgpt.com"]

[infra]
sensitivity = "none"
hosts = ["github.com"]

[media]
sensitivity = "none"
hosts = ["youtube.com"]
"""

LOCAL_TOML = """
# 로컬 오버레이 — 사용자 고유 호스트. git 밖에 둔다.
[work]
sensitivity = "none"
hosts = ["intranet.test"]

[finance]
sensitivity = "restricted"
hosts = ["mybank.test"]

# 기본 룰의 분류를 덮어쓴다
[personal]
sensitivity = "restricted"
hosts = ["youtube.com"]
"""


@pytest.fixture
def base_only(tmp_path):
    p = tmp_path / "domains.toml"
    p.write_text(BASE_TOML)
    return load_rules(p)


@pytest.fixture
def layered(tmp_path):
    b = tmp_path / "domains.toml"
    b.write_text(BASE_TOML)
    lo = tmp_path / "domains.local.toml"
    lo.write_text(LOCAL_TOML)
    return load_rules(b, lo)


# ── 기본 매칭 ────────────────────────────────────────────────────────────────

def test_exact_host_is_classified(base_only):
    assert classify_host(base_only, "claude.ai") == ("ai-tools", "none")


def test_subdomain_inherits_parent_rule(base_only):
    assert classify_host(base_only, "docs.github.com") == ("infra", "none")


def test_deep_subdomain_inherits(base_only):
    assert classify_host(base_only, "a.b.c.github.com") == ("infra", "none")


def test_unknown_host_falls_back(base_only):
    assert classify_host(base_only, "nowhere.test") == ("unknown", "none")


def test_host_matching_is_case_insensitive(base_only):
    assert classify_host(base_only, "GitHub.COM") == ("infra", "none")


def test_port_is_ignored(base_only):
    assert classify_host(base_only, "github.com:8443") == ("infra", "none")


def test_unrelated_host_ending_in_same_letters_does_not_match(base_only):
    """notgithub.com 은 github.com 의 서브도메인이 아니다. 접미사 비교만 하면 오분류된다."""
    assert classify_host(base_only, "notgithub.com") == ("unknown", "none")


# ── 2층 룰 ───────────────────────────────────────────────────────────────────

def test_local_overlay_adds_new_hosts(layered):
    assert classify_host(layered, "intranet.test") == ("work", "none")


def test_local_overlay_wins_over_base(layered):
    """youtube.com 은 기본에서 media/none, 로컬에서 personal/restricted 다."""
    assert classify_host(layered, "youtube.com") == ("personal", "restricted")


def test_base_rules_survive_when_local_does_not_mention_them(layered):
    assert classify_host(layered, "claude.ai") == ("ai-tools", "none")


def test_works_without_local_file(tmp_path):
    """로컬 오버레이가 없어도 파이프라인이 서야 한다 — 공개 배포의 최소 조건."""
    b = tmp_path / "domains.toml"
    b.write_text(BASE_TOML)
    rules = load_rules(b, tmp_path / "does-not-exist.toml")
    assert classify_host(rules, "claude.ai") == ("ai-tools", "none")


# ── 민감도 ───────────────────────────────────────────────────────────────────

def test_restricted_sensitivity_is_carried(layered):
    assert classify_host(layered, "mybank.test")[1] == "restricted"


def test_subdomain_inherits_restricted(layered):
    assert classify_host(layered, "login.mybank.test")[1] == "restricted"


def test_more_specific_host_wins_over_parent(tmp_path):
    """example.test 는 none 인데 secret.example.test 만 restricted 인 경우."""
    b = tmp_path / "domains.toml"
    b.write_text('''
[media]
sensitivity = "none"
hosts = ["example.test"]

[finance]
sensitivity = "restricted"
hosts = ["secret.example.test"]
''')
    rules = load_rules(b)
    assert classify_host(rules, "example.test") == ("media", "none")
    assert classify_host(rules, "secret.example.test") == ("finance", "restricted")


# ── 입력 안전성·실패를 드러내기 ────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["", None, "   ", ".", ".."])
def test_weird_host_is_unknown_not_a_crash(base_only, host):
    cat, sens = classify_host(base_only, host)
    assert cat == "unknown"
    assert sens == "none"


def test_missing_base_file_raises_clearly(tmp_path):
    """기본 룰이 없으면 전부 unknown 으로 조용히 도는 대신 명시적으로 실패해야 한다."""
    with pytest.raises((FileNotFoundError, ValueError)):
        load_rules(tmp_path / "nope.toml")


def test_malformed_toml_raises_clearly(tmp_path):
    b = tmp_path / "domains.toml"
    b.write_text("this is not = valid = toml [[[")
    with pytest.raises(ValueError):
        load_rules(b)


def test_category_without_sensitivity_defaults_to_none(tmp_path):
    b = tmp_path / "domains.toml"
    b.write_text('[misc]\nhosts = ["a.test"]\n')
    rules = load_rules(b)
    assert classify_host(rules, "a.test") == ("misc", "none")


def test_invalid_sensitivity_value_raises(tmp_path):
    b = tmp_path / "domains.toml"
    b.write_text('[misc]\nsensitivity = "kinda-secret"\nhosts = ["a.test"]\n')
    with pytest.raises(ValueError):
        load_rules(b)
