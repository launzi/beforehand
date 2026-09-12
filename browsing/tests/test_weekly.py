"""주간 다이제스트 계약 테스트.

이 모듈의 산출물은 사람이 읽는 마크다운이고, 그래서 두 가지가 급소다.

  1. restricted 가 새어나가면 안 된다 — 리포트는 파일로 남고 공유되기 쉽다
  2. 정적 목록이 아니라 **변화**를 보여야 한다 — 새 도메인, 전주 대비 증감,
     미분류 상위(분류 커버리지가 조용히 낮아지는 것을 막는 장치)

⚠ 합성 데이터만 쓴다.
"""

import sqlite3

import pytest

from browsing.ingest import init_db, ingest_records
from browsing.weekly import build_digest, render_markdown

US = 13404038416000000        # 2025-10-04T08:00:16Z (토)
DAY = 86_400_000_000
WEEK = 7 * DAY


def visit(url, us, profile="Default", title="T"):
    return {"kind": "visit", "profile": profile, "url": url, "title": title,
            "visit_time_us": us, "transition": 0, "duration_us": 0,
            "from_visit_key": None}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    # 지난 주
    ingest_records(c, [
        visit("https://github.com/a", US - WEEK),
        visit("https://github.com/b", US - WEEK + 10),
        visit("https://oldsite.test/x", US - WEEK + 20),
    ])
    # 이번 주
    ingest_records(c, [
        visit("https://github.com/c", US),
        visit("https://claude.ai/x", US + 10),
        visit("https://claude.ai/y", US + 20),
        visit("https://claude.ai/z", US + 30),
        visit("https://newthing.test/p", US + 40),     # 이번 주 처음
        visit("https://mybank.test/login", US + 50),   # restricted
        {"kind": "search", "profile": "Default",
         "url": "https://search.test/s?q=tomllib", "term": "tomllib",
         "first_seen_us": US + 60},
        {"kind": "download", "profile": "Default", "guid": "g1",
         "target_path": "/tmp/spec.pdf", "referrer": "https://github.com/c",
         "start_time_us": US + 70, "received_bytes": 100,
         "mime_type": "application/pdf", "state": 1},
    ])
    c.executemany(
        "INSERT OR REPLACE INTO domains(host, category, sensitivity, label_source)"
        " VALUES (?,?,?,?)",
        [("github.com", "infra", "none", "rule"),
         ("claude.ai", "ai-tools", "none", "rule"),
         ("oldsite.test", "media", "none", "rule"),
         ("mybank.test", "finance", "restricted", "manual")])
    # newthing.test, search.test 는 일부러 분류하지 않는다 → unknown
    c.commit()
    yield c
    c.close()


@pytest.fixture
def digest(conn):
    return build_digest(conn, start_us=US, end_us=US + WEEK)


# ── restricted 는 리포트에 절대 나오지 않는다 ─────────────────────────────────

def test_restricted_host_absent_from_digest(digest):
    assert "mybank.test" not in render_markdown(digest)


def test_restricted_host_absent_from_new_hosts(digest):
    assert all(h["host"] != "mybank.test" for h in digest["new_hosts"])


def test_restricted_visits_excluded_from_totals(conn):
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    d_all = build_digest(conn, start_us=US, end_us=US + WEEK, include_restricted=True)
    assert d["totals"]["visits"] < d_all["totals"]["visits"]


def test_restricted_appears_only_when_explicitly_asked(conn):
    d = build_digest(conn, start_us=US, end_us=US + WEEK, include_restricted=True)
    assert any(h["host"] == "mybank.test" for h in d["top_hosts"])


# ── 변화를 보여준다 (정적 목록이 아니라) ──────────────────────────────────────

def test_new_hosts_lists_hosts_first_seen_this_week(digest):
    hosts = {h["host"] for h in digest["new_hosts"]}
    assert "newthing.test" in hosts
    assert "github.com" not in hosts       # 지난 주에 이미 봤다


def test_week_over_week_delta_is_reported(digest):
    assert "prev_visits" in digest["totals"]
    assert "delta_visits" in digest["totals"]


def test_delta_is_previous_week_difference(conn):
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert d["totals"]["delta_visits"] == d["totals"]["visits"] - d["totals"]["prev_visits"]


def test_disappeared_hosts_are_reported(digest):
    """지난 주에 보던 것을 이번 주에 안 봤다면 그것도 신호다."""
    assert "oldsite.test" in {h["host"] for h in digest["dropped_hosts"]}


# ── 분류 커버리지 — 조용히 낮아지는 것을 막는다 ───────────────────────────────

def test_unclassified_hosts_are_surfaced(digest):
    assert "newthing.test" in {h["host"] for h in digest["unknown_hosts"]}


def test_classified_host_not_in_unknown_list(digest):
    assert "github.com" not in {h["host"] for h in digest["unknown_hosts"]}


# ── 내용 ─────────────────────────────────────────────────────────────────────

def test_top_hosts_sorted_by_visits(digest):
    counts = [h["visits"] for h in digest["top_hosts"]]
    assert counts == sorted(counts, reverse=True)


def test_searches_are_included(digest):
    assert "tomllib" in {s["term"] for s in digest["searches"]}


def test_downloads_are_included(digest):
    assert len(digest["downloads"]) == 1


def test_category_breakdown_present(digest):
    assert digest["categories"].get("ai-tools") == 3


def test_window_is_respected(conn):
    """지난 주 방문이 이번 주 집계에 섞이면 안 된다."""
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert all(h["host"] != "oldsite.test" for h in d["top_hosts"])


# ── 수집 건강성 — 장기 미실행은 영구 유실이다 ────────────────────────────────

def test_health_reports_last_run(conn):
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert "health" in d
    assert "profiles" in d["health"]


def test_health_warns_when_collection_is_stale(conn):
    """Chrome 은 오래된 방문을 스스로 지운다. 수집이 멈추면 영구 유실이다."""
    conn.execute("UPDATE sync_state SET last_run_utc = ?", ("2020-01-01T00:00:00+00:00",))
    conn.commit()
    d = build_digest(conn, start_us=US, end_us=US + WEEK, now_utc="2026-09-13T00:00:00+00:00")
    assert d["health"]["stale"] is True


# ── 렌더링 ───────────────────────────────────────────────────────────────────

def test_render_returns_markdown_with_headings(digest):
    md = render_markdown(digest)
    assert md.lstrip().startswith("#")
    assert "##" in md


def test_render_survives_empty_week():
    c = sqlite3.connect(":memory:")
    init_db(c)
    d = build_digest(c, start_us=US, end_us=US + WEEK)
    md = render_markdown(d)
    assert isinstance(md, str) and len(md) > 0
    c.close()


def test_render_does_not_contain_raw_credentials(conn):
    ingest_records(conn, [visit("https://example.com/cb?code=SENSITIVEVALUE", US + 80)])
    md = render_markdown(build_digest(conn, start_us=US, end_us=US + WEEK))
    assert "SENSITIVEVALUE" not in md


# ── 읽을 수 있는 리포트 (실데이터가 드러낸 결함) ──────────────────────────────

def test_host_without_a_hostname_is_not_listed(conn):
    """파싱 불가 URL 은 host 가 비어 있다. 리포트에 None 이 찍히면 안 된다.

    실데이터에서 'None (uncategorized) — 20 visits' 가 출력됐다.
    """
    ingest_records(conn, [visit("not-a-url-at-all", US + 90)])
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert all(h["host"] for h in d["top_hosts"]), "빈 host 가 목록에 있다"
    assert "None" not in render_markdown(d)


def test_top_hosts_is_capped(conn):
    """실데이터에서 130개 호스트가 전부 나열돼 사람이 읽을 수 없었다."""
    ingest_records(conn, [visit(f"https://h{i}.test/p", US + 1000 + i)
                          for i in range(60)])
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert len(d["top_hosts"]) <= 25


def test_top_hosts_limit_is_configurable(conn):
    ingest_records(conn, [visit(f"https://h{i}.test/p", US + 2000 + i)
                          for i in range(30)])
    d = build_digest(conn, start_us=US, end_us=US + WEEK, top_limit=5)
    assert len(d["top_hosts"]) == 5


def test_unknown_hosts_is_capped(conn):
    ingest_records(conn, [visit(f"https://u{i}.test/p", US + 3000 + i)
                          for i in range(60)])
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert len(d["unknown_hosts"]) <= 25


def test_digest_reports_how_many_were_omitted(conn):
    """잘랐다는 사실 자체를 알려야 한다 — 조용히 자르면 전체 규모를 오해한다."""
    ingest_records(conn, [visit(f"https://x{i}.test/p", US + 4000 + i)
                          for i in range(60)])
    d = build_digest(conn, start_us=US, end_us=US + WEEK, top_limit=10)
    assert d["totals"]["hosts"] > len(d["top_hosts"])
    assert "top_hosts_omitted" in d["totals"]
    assert d["totals"]["top_hosts_omitted"] == d["totals"]["hosts"] - 10


# ── 창 계산 (손으로 고친 버그 — 테스트가 없어서 못 잡았다) ────────────────────

def test_window_utc_matches_chrome_epoch(conn):
    """Chrome 은 1601-01-01 부터 센다. 오프셋을 빠뜨리면 2394년이 나오고,
    ISO 문자열로 비교하는 searches·downloads 가 조용히 0건이 된다.
    정수로 비교하는 visits 는 멀쩡해서 증상이 반쪽만 보인다.
    """
    from browsing.ingest import chrome_us_to_utc
    d = build_digest(conn, start_us=US, end_us=US + WEEK)
    assert d["window"]["start_utc"] == chrome_us_to_utc(US)
    assert d["window"]["end_utc"] == chrome_us_to_utc(US + WEEK)
    assert d["window"]["start_utc"].startswith("2025-")
