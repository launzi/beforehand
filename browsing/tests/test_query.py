"""질의 계약 테스트.

가장 중요한 계약은 **restricted 기본 제외**다. 사용자의 이직 탐색·금융 이력이
일상 조회에 무심코 섞이지 않게 하는 장치이고, 브리프 수용 기준에도 들어 있다.

⚠ 합성 데이터만 쓴다.
"""

import sqlite3

import pytest

from browsing.ingest import init_db, ingest_records
from browsing.query import (
    new_hosts,
    search_terms,
    stats,
    timeline,
    top_hosts,
)

US = 13404038416000000          # 2025-10-04T08:00:16Z
DAY = 86_400_000_000            # 하루(마이크로초)


def visit(url, us, profile="Default", title="T"):
    return {"kind": "visit", "profile": profile, "url": url, "title": title,
            "visit_time_us": us, "transition": 0, "duration_us": 0,
            "from_visit_key": None}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    ingest_records(c, [
        visit("https://github.com/a", US),
        visit("https://github.com/b", US + 100),
        visit("https://claude.ai/x", US + 200),
        visit("https://mybank.test/login", US + 300),      # restricted 로 분류할 것
        visit("https://youtube.com/watch", US + DAY),      # 다음 날
        {"kind": "search", "profile": "Default",
         "url": "https://google.com/s?q=nemotron+traps",
         "term": "nemotron traps", "first_seen_us": US},
        {"kind": "search", "profile": "Default",
         "url": "https://google.com/s?q=tomllib",
         "term": "tomllib", "first_seen_us": US + DAY},
    ])
    # 분류 결과를 domains 에 심는다 (classify 단계가 채우는 테이블)
    c.executemany(
        "INSERT OR REPLACE INTO domains(host, category, sensitivity, label_source)"
        " VALUES (?,?,?,?)",
        [("github.com", "infra", "none", "rule"),
         ("claude.ai", "ai-tools", "none", "rule"),
         ("youtube.com", "media", "none", "rule"),
         ("google.com", "search", "none", "rule"),
         ("mybank.test", "finance", "restricted", "manual")])
    c.commit()
    yield c
    c.close()


def hosts_of(rows):
    return {r["host"] for r in rows}


# ── restricted 기본 제외 — 이 파일의 핵심 ────────────────────────────────────

def test_top_hosts_excludes_restricted_by_default(conn):
    assert "mybank.test" not in hosts_of(top_hosts(conn))


def test_top_hosts_includes_restricted_when_asked(conn):
    assert "mybank.test" in hosts_of(top_hosts(conn, include_restricted=True))


def test_new_hosts_excludes_restricted_by_default(conn):
    assert "mybank.test" not in hosts_of(new_hosts(conn, since_us=0))


def test_timeline_of_restricted_host_is_empty_by_default(conn):
    assert timeline(conn, "mybank.test") == []


def test_timeline_of_restricted_host_works_when_asked(conn):
    assert len(timeline(conn, "mybank.test", include_restricted=True)) == 1


def test_stats_excludes_restricted_visits_by_default(conn):
    with_r = stats(conn, include_restricted=True)["visits"]
    without = stats(conn)["visits"]
    assert without < with_r


# ── 집계 ─────────────────────────────────────────────────────────────────────

def test_top_hosts_counts_visits_per_host(conn):
    row = next(r for r in top_hosts(conn) if r["host"] == "github.com")
    assert row["visits"] == 2


def test_top_hosts_is_sorted_by_visit_count_desc(conn):
    counts = [r["visits"] for r in top_hosts(conn)]
    assert counts == sorted(counts, reverse=True)


def test_top_hosts_carries_category(conn):
    row = next(r for r in top_hosts(conn) if r["host"] == "claude.ai")
    assert row["category"] == "ai-tools"


def test_unclassified_host_is_reported_as_unknown(conn):
    ingest_records(conn, [visit("https://nowhere.test/p", US + 500)])
    row = next(r for r in top_hosts(conn) if r["host"] == "nowhere.test")
    assert row["category"] == "unknown"


# ── 기간 필터 ────────────────────────────────────────────────────────────────

def test_since_filter_excludes_earlier_visits(conn):
    assert "github.com" not in hosts_of(top_hosts(conn, since_us=US + DAY - 1))


def test_until_filter_excludes_later_visits(conn):
    assert "youtube.com" not in hosts_of(top_hosts(conn, until_us=US + DAY - 1))


def test_new_hosts_returns_only_hosts_first_seen_after_since(conn):
    got = hosts_of(new_hosts(conn, since_us=US + DAY - 1))
    assert "youtube.com" in got
    assert "github.com" not in got


# ── 검색어 ───────────────────────────────────────────────────────────────────

def test_search_terms_returns_all(conn):
    assert {r["term"] for r in search_terms(conn)} == {"nemotron traps", "tomllib"}


def test_search_terms_grep_filters(conn):
    assert [r["term"] for r in search_terms(conn, grep="tom")] == ["tomllib"]


def test_search_terms_grep_is_case_insensitive(conn):
    assert [r["term"] for r in search_terms(conn, grep="TOM")] == ["tomllib"]


# ── 타임라인 ─────────────────────────────────────────────────────────────────

def test_timeline_returns_visits_for_host(conn):
    assert len(timeline(conn, "github.com")) == 2


def test_timeline_includes_subdomains(conn):
    ingest_records(conn, [visit("https://docs.github.com/z", US + 900)])
    assert len(timeline(conn, "github.com")) == 3


def test_timeline_is_chronological(conn):
    times = [r["visit_time_utc"] for r in timeline(conn, "github.com")]
    assert times == sorted(times)


# ── 통계 ─────────────────────────────────────────────────────────────────────

def test_stats_reports_totals(conn):
    s = stats(conn)
    assert s["visits"] > 0
    assert s["hosts"] > 0
    assert s["searches"] == 2


def test_stats_on_empty_db_does_not_crash():
    c = sqlite3.connect(":memory:")
    init_db(c)
    s = stats(c)
    assert s["visits"] == 0
    c.close()


# ── 프로파일 필터 ────────────────────────────────────────────────────────────

def test_profile_filter_narrows_results(conn):
    ingest_records(conn, [visit("https://other.test/p", US + 700, profile="Profile 1")])
    assert "other.test" not in hosts_of(top_hosts(conn, profile="Default"))
    assert "other.test" in hosts_of(top_hosts(conn, profile="Profile 1"))
