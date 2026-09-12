"""scrub_url 계약 테스트.

정본은 설계 스펙 4절(`docs/superpowers/specs/2026-09-13-browsing-history-ingestion-design.md`).
이 파일이 그 스펙의 실행 가능한 표현이다 — 구현이 바뀌어도 여기가 판정 기준이다.

⚠ 실데이터를 쓰지 않는다. 전부 합성 URL 이다.
"""

import pytest

from browsing.scrub import scrub_url


# ── 화이트리스트: 검색어는 이 시스템의 핵심 자산이라 절대 마스킹되면 안 된다 ──────────

def test_keyword_survives_the_key_blacklist_substring():
    """`keyword` 는 블랙리스트 `key` 를 부분문자열로 포함한다.

    블랙리스트를 먼저 돌리면 모든 검색어가 조용히 사라진다. 화이트리스트 정확일치가
    먼저라는 규칙이 지켜지는지 보는 테스트다. 이 하나가 스크럽 전체의 급소다.
    """
    out, status = scrub_url("https://example.com/s?keyword=hangeul")
    assert "keyword=hangeul" in out
    assert status == "ok"


@pytest.mark.parametrize("name", ["q", "query", "search_query", "s", "wd", "page", "tab"])
def test_whitelisted_names_are_preserved(name):
    out, _ = scrub_url(f"https://example.com/s?{name}=nemotron")
    assert f"{name}=nemotron" in out


def test_utm_prefixed_names_are_preserved():
    out, _ = scrub_url("https://example.com/p?utm_source=newsletter&utm_campaign=fall")
    assert "utm_source=newsletter" in out
    assert "utm_campaign=fall" in out


# ── 블랙리스트: 크레덴셜성 파라미터 ────────────────────────────────────────────

@pytest.mark.parametrize("name", ["code", "state", "access_token", "id_token",
                                  "session", "secret", "password", "apikey",
                                  "signature", "nonce"])
def test_blacklisted_names_are_masked(name):
    out, status = scrub_url(f"https://example.com/cb?{name}=SENSITIVE")
    assert "SENSITIVE" not in out
    assert "<redacted:" in out
    assert status == "ok"


def test_blacklist_matches_as_substring():
    """`auth_code` 는 정확히 일치하지 않지만 `code`·`auth` 를 포함하므로 마스킹된다."""
    out, _ = scrub_url("https://example.com/cb?auth_code=SENSITIVE")
    assert "SENSITIVE" not in out


def test_blacklist_is_case_insensitive():
    out, _ = scrub_url("https://example.com/cb?ACCESS_TOKEN=SENSITIVE")
    assert "SENSITIVE" not in out


# ── 값 휴리스틱: 이름이 무해해도 고엔트로피 값이면 가린다 ────────────────────────

def test_long_base64_like_value_is_masked_regardless_of_name():
    out, _ = scrub_url("https://example.com/p?ref=" + "A" * 44)
    assert "<redacted:44>" in out


def test_short_value_with_harmless_name_is_kept():
    out, _ = scrub_url("https://example.com/p?ref=abc")
    assert "ref=abc" in out


def test_long_value_with_whitelisted_name_is_still_kept():
    """화이트리스트가 먼저 끝나므로 긴 검색어도 살아남는다."""
    long_term = "a" * 50
    out, _ = scrub_url(f"https://example.com/s?q={long_term}")
    assert long_term in out


# ── 마스킹 형식 ──────────────────────────────────────────────────────────────

def test_mask_records_original_value_length():
    out, _ = scrub_url("https://example.com/cb?code=" + "x" * 13)
    assert "<redacted:13>" in out


def test_mask_marker_is_not_percent_encoded():
    """`<redacted:N>` 이 %3Credacted%3A13%3E 로 나가면 사람이 읽을 수 없다."""
    out, _ = scrub_url("https://example.com/cb?code=abcdef")
    assert "<redacted:" in out
    assert "%3C" not in out


# ── 구조 보존 ────────────────────────────────────────────────────────────────

def test_scheme_host_and_path_are_preserved():
    out, _ = scrub_url("https://sub.example.com/a/b/c?code=x")
    assert out.startswith("https://sub.example.com/a/b/c")


def test_fragment_is_preserved():
    out, _ = scrub_url("https://example.com/p?q=1#section-2")
    assert out.endswith("#section-2")


def test_url_without_query_is_unchanged():
    url = "https://example.com/plain/path"
    out, status = scrub_url(url)
    assert out == url
    assert status == "ok"


def test_mixed_params_keep_and_mask_independently():
    out, _ = scrub_url("https://example.com/s?q=font&code=SENSITIVE&page=2")
    assert "q=font" in out
    assert "page=2" in out
    assert "SENSITIVE" not in out


# ── 실패 경로: 조용히 통과시키지 않는다 ─────────────────────────────────────────

def test_unparsable_url_reports_failed_and_drops_query():
    out, status = scrub_url("http://[malformed?code=SENSITIVE")
    assert status == "failed"
    assert "SENSITIVE" not in out


@pytest.mark.parametrize("weird", ["", "not a url", "://", "?", "#", "  "])
def test_never_raises_on_weird_input(weird):
    out, status = scrub_url(weird)
    assert isinstance(out, str)
    assert status in ("ok", "failed")


@pytest.mark.parametrize("value", [None, 12345, b"bytes"])
def test_non_string_input_returns_a_string(value):
    """계약은 tuple[str, str] 이다. bytes 를 돌려주면 하류에서 조용히 깨진다."""
    out, status = scrub_url(value)
    assert isinstance(out, str)
    assert status in ("ok", "failed")
