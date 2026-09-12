"""ingest 계약 테스트 — 정규화·멱등 적재·워터마크.

정본은 설계 스펙 5절. 이 파일이 입력 레코드 형식의 계약이기도 하다.

⚠ 합성 데이터만 쓴다. 실제 브라우징 기록을 넣지 않는다.
"""

import sqlite3

import pytest

from browsing.ingest import (
    chrome_us_to_utc,
    get_watermark,
    ingest_records,
    init_db,
)

# 13404038416000000 us since 1601-01-01 → 1759564816 unix → 2025-10-04T08:00:16Z
KNOWN_US = 13404038416000000
KNOWN_ISO = "2025-10-04T08:00:16+00:00"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    yield c
    c.close()


def visit(url="https://example.com/a", us=KNOWN_US, profile="Default", title="T"):
    return {"kind": "visit", "profile": profile, "url": url, "title": title,
            "visit_time_us": us, "transition": 0, "duration_us": 0,
            "from_visit_key": None}


def count(c, table):
    return c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# ── 타임스탬프 ───────────────────────────────────────────────────────────────

def test_chrome_timestamp_converts_to_utc_iso():
    assert chrome_us_to_utc(KNOWN_US) == KNOWN_ISO


def test_chrome_timestamp_zero_does_not_crash():
    assert isinstance(chrome_us_to_utc(0), str)


# ── 스키마 ───────────────────────────────────────────────────────────────────

def test_init_db_can_run_twice(conn):
    init_db(conn)  # 재실행이 기존 데이터를 지우거나 실패하면 안 된다
    assert count(conn, "urls") == 0


@pytest.mark.parametrize("table", ["urls", "visits", "searches", "downloads",
                                   "domains", "sync_state"])
def test_all_tables_exist(conn, table):
    conn.execute(f"SELECT * FROM {table} LIMIT 1")


# ── 적재와 스크럽 ────────────────────────────────────────────────────────────

def test_visit_is_stored(conn):
    ingest_records(conn, [visit()])
    assert count(conn, "visits") == 1
    assert count(conn, "urls") == 1


def test_stored_url_is_scrubbed(conn):
    ingest_records(conn, [visit(url="https://example.com/cb?code=SENSITIVE")])
    stored = conn.execute("SELECT url FROM urls").fetchone()[0]
    assert "SENSITIVE" not in stored
    assert "<redacted:" in stored


def test_search_term_is_preserved_through_scrubbing(conn):
    """검색어는 이 시스템의 핵심 자산이라 URL 안에서도 살아남아야 한다."""
    ingest_records(conn, [visit(url="https://example.com/s?keyword=hangeul")])
    stored = conn.execute("SELECT url FROM urls").fetchone()[0]
    assert "keyword=hangeul" in stored


def test_download_referrer_is_scrubbed(conn):
    """urls.url 만 막으면 referrer 로 OAuth 콜백이 새어나간다."""
    ingest_records(conn, [{
        "kind": "download", "profile": "Default", "guid": "g1",
        "target_path": "/tmp/f.pdf", "referrer": "https://example.com/cb?code=SENSITIVE",
        "start_time_us": KNOWN_US, "received_bytes": 10, "mime_type": "application/pdf",
    }])
    rows = conn.execute("SELECT url FROM urls").fetchall()
    assert all("SENSITIVE" not in r[0] for r in rows)


def test_search_record_is_stored(conn):
    ingest_records(conn, [{
        "kind": "search", "profile": "Default", "url": "https://example.com/s?q=font",
        "term": "font", "first_seen_us": KNOWN_US,
    }])
    assert count(conn, "searches") == 1


# ── 멱등성 — 이 시스템의 핵심 계약 ────────────────────────────────────────────

def test_same_batch_twice_does_not_duplicate(conn):
    batch = [visit(), visit(url="https://example.com/b", us=KNOWN_US + 1)]
    ingest_records(conn, batch)
    before = (count(conn, "urls"), count(conn, "visits"))
    ingest_records(conn, batch)
    assert (count(conn, "urls"), count(conn, "visits")) == before


def test_same_url_visited_twice_gives_one_url_and_two_visits(conn):
    ingest_records(conn, [visit(us=KNOWN_US), visit(us=KNOWN_US + 1000)])
    assert count(conn, "urls") == 1
    assert count(conn, "visits") == 2


def test_same_visit_time_different_profile_is_a_separate_visit(conn):
    ingest_records(conn, [visit(profile="Default"), visit(profile="Profile 1")])
    assert count(conn, "visits") == 2


def test_reingest_updates_title(conn):
    ingest_records(conn, [visit(title="old")])
    ingest_records(conn, [visit(title="new")])
    assert conn.execute("SELECT title FROM urls").fetchone()[0] == "new"
    assert count(conn, "urls") == 1


# ── 워터마크 ─────────────────────────────────────────────────────────────────

def test_watermark_is_max_visit_time_for_profile(conn):
    ingest_records(conn, [visit(us=KNOWN_US), visit(us=KNOWN_US + 5000)])
    assert get_watermark(conn, "Default") == KNOWN_US + 5000


def test_watermark_is_per_profile(conn):
    ingest_records(conn, [visit(profile="Default", us=KNOWN_US),
                          visit(profile="Profile 1", us=KNOWN_US + 9000)])
    assert get_watermark(conn, "Default") == KNOWN_US
    assert get_watermark(conn, "Profile 1") == KNOWN_US + 9000


def test_watermark_is_none_for_unseen_profile(conn):
    assert get_watermark(conn, "Profile 9") is None


def test_watermark_does_not_go_backwards(conn):
    ingest_records(conn, [visit(us=KNOWN_US + 5000)])
    ingest_records(conn, [visit(us=KNOWN_US)])
    assert get_watermark(conn, "Default") == KNOWN_US + 5000


# ── 실패를 조용히 넘기지 않는다 ───────────────────────────────────────────────

def test_empty_input_is_safe(conn):
    stats = ingest_records(conn, [])
    assert isinstance(stats, dict)
    assert count(conn, "visits") == 0


def test_unknown_kind_is_counted_not_silently_dropped(conn):
    """모르는 레코드를 조용히 버리면 유실을 발견할 방법이 없다."""
    stats = ingest_records(conn, [{"kind": "telepathy", "profile": "Default"}])
    assert stats.get("skipped") == 1


def test_record_missing_required_field_is_counted(conn):
    stats = ingest_records(conn, [{"kind": "visit", "profile": "Default"}])
    assert stats.get("skipped", 0) >= 1
    assert count(conn, "visits") == 0


def test_stats_report_what_was_written(conn):
    stats = ingest_records(conn, [visit()])
    assert stats.get("visits") == 1
