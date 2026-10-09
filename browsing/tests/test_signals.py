"""신호 검출 계약 테스트.

이 층은 **규칙만** 쓴다. LLM 을 부르지 않는다 — 비용 때문이기도 하고, 같은 입력에
같은 출력이 나와야 상위(triage)가 무엇을 판단했는지 추적할 수 있기 때문이다.

신호 4종의 기계적 정의가 여기 고정된다.

⚠ 합성 데이터만 쓴다.
"""

import sqlite3

import pytest

from browsing.ingest import init_db, ingest_records
from browsing.signals import Signal, detect_all, detect_dropped, detect_new_entry, detect_recurring, detect_unresolved, detect_korea_product, _chrome_us_from_iso

US = 13404038416000000
HOUR = 3_600_000_000
DAY = 86_400_000_000


def visit(url, us, profile="Default", title="T", from_key=None):
    return {"kind": "visit", "profile": profile, "url": url, "title": title,
            "visit_time_us": us, "transition": 0, "duration_us": 0,
            "from_visit_key": from_key}


def search(url, term, us, profile="Default"):
    return {"kind": "search", "profile": profile, "url": url, "term": term,
            "first_seen_us": us}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    yield c
    c.close()


def kinds(signals, kind):
    return [s for s in signals if s.kind == kind]


@pytest.mark.parametrize("first,last,days", [
    # Crossing KST midnight is still one UTC calendar day.
    ("2026-09-28T14:59:00Z", "2026-09-28T15:01:00Z", 1),
    # Crossing UTC midnight is two UTC days, even within one KST day.
    ("2026-09-28T23:59:00Z", "2026-09-29T00:01:00Z", 2),
])
def test_korea_product_distinct_days_are_utc(conn, first, last, days):
    first_us, last_us = _chrome_us_from_iso(first), _chrome_us_from_iso(last)
    url = "https://global.oliveyoung.com/product/detail/123"
    title = "Anua Heartleaf 77% Soothing Toner 250ml | OLIVE YOUNG Global"
    ingest_records(conn, [visit(url, us, title=title) for us in (first_us, last_us)])
    signals = detect_korea_product(conn, since_us=first_us, until_us=last_us + 1)
    assert len(signals) == 1
    assert signals[0].evidence["distinct_days"] == days
    assert signals[0].evidence["visit_count"] == 2
    assert signals[0].evidence["purchase_page_observed"] is False


# ── 신호 3: 새 진입 — 실증된 신호 ─────────────────────────────────────────────
#
# 2026-09-13 세션에서 이 신호만으로 이틀치 가입 서비스 6개를 전부 복원했다.

def test_new_entry_detects_signup_path(conn):
    ingest_records(conn, [
        visit("https://newservice.test/", US),
        visit("https://newservice.test/signup", US + 10),
    ])
    got = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)
    assert "newservice.test" in {s.host for s in got}


@pytest.mark.parametrize("path", ["/signup", "/register", "/login", "/auth/callback",
                                  "/onboarding", "/welcome", "/users/register"])
def test_new_entry_recognises_onboarding_paths(conn, path):
    ingest_records(conn, [visit(f"https://svc.test{path}", US)])
    got = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)
    assert "svc.test" in {s.host for s in got}


def test_new_entry_ignores_host_first_seen_before_window(conn):
    ingest_records(conn, [visit("https://old.test/signup", US - 10 * DAY)])
    got = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)
    assert "old.test" not in {s.host for s in got}


def test_new_entry_without_onboarding_path_is_not_a_signal(conn):
    """그냥 한 번 스쳐간 사이트는 '진입'이 아니다."""
    ingest_records(conn, [visit("https://random.test/article/1", US)])
    got = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)
    assert "random.test" not in {s.host for s in got}


# ── 신호 1: 미완결 탐색 ───────────────────────────────────────────────────────

def test_unresolved_flags_search_with_no_follow_through(conn):
    """검색만 하고 아무것도 안 열었다면 답을 못 찾은 것이다."""
    ingest_records(conn, [
        visit("https://search.test/s?q=how+to+x", US),
        search("https://search.test/s?q=how+to+x", "how to x", US),
    ])
    got = detect_unresolved(conn, since_us=US - DAY, until_us=US + DAY)
    assert "how to x" in {s.term for s in got}


def test_unresolved_flags_repeated_same_search(conn):
    """같은 것을 며칠에 걸쳐 다시 검색하면 아직 해결되지 않은 것이다."""
    ingest_records(conn, [
        visit("https://search.test/s?q=tomllib", US),
        search("https://search.test/s?q=tomllib", "tomllib", US),
        visit("https://search.test/s?q=tomllib", US + 2 * DAY),
        search("https://search.test/s?q=tomllib", "tomllib", US + 2 * DAY),
    ])
    got = detect_unresolved(conn, since_us=US - DAY, until_us=US + 5 * DAY)
    assert "tomllib" in {s.term for s in got}


def test_search_with_deep_follow_through_is_not_unresolved(conn):
    """검색 후 여러 페이지를 읽었다면 답을 찾았다고 본다."""
    ingest_records(conn, [
        visit("https://search.test/s?q=answered", US),
        search("https://search.test/s?q=answered", "answered", US),
        visit("https://docs.test/a", US + 60),
        visit("https://docs.test/b", US + 120),
        visit("https://docs.test/c", US + 180),
    ])
    got = detect_unresolved(conn, since_us=US - DAY, until_us=US + DAY)
    assert "answered" not in {s.term for s in got}


# ── 신호 2: 반복 재방문 ───────────────────────────────────────────────────────

def test_recurring_detects_host_across_several_days(conn):
    ingest_records(conn, [visit("https://topic.test/p", US + i * DAY) for i in range(4)])
    got = detect_recurring(conn, since_us=US - DAY, until_us=US + 10 * DAY)
    assert "topic.test" in {s.host for s in got}


def test_many_visits_on_one_day_is_not_recurring(conn):
    """하루에 몰아본 것은 지속 관심이 아니다."""
    ingest_records(conn, [visit("https://binge.test/p", US + i * 60) for i in range(20)])
    got = detect_recurring(conn, since_us=US - DAY, until_us=US + 10 * DAY)
    assert "binge.test" not in {s.host for s in got}


def test_recurring_threshold_is_configurable(conn):
    ingest_records(conn, [visit("https://t.test/p", US + i * DAY) for i in range(3)])
    assert "t.test" in {s.host for s in detect_recurring(
        conn, since_us=US - DAY, until_us=US + 10 * DAY, min_days=3)}
    assert "t.test" not in {s.host for s in detect_recurring(
        conn, since_us=US - DAY, until_us=US + 10 * DAY, min_days=5)}


# ── 신호 4: 중단된 작업 ───────────────────────────────────────────────────────

def test_dropped_detects_host_that_stopped(conn):
    """며칠 연속 보던 것을 갑자기 안 본다면 끊긴 작업일 수 있다."""
    ingest_records(conn, [visit("https://project.test/p", US + i * DAY) for i in range(5)])
    got = detect_dropped(conn, now_us=US + 20 * DAY, quiet_days=7)
    assert "project.test" in {s.host for s in got}


def test_still_active_host_is_not_dropped(conn):
    ingest_records(conn, [visit("https://active.test/p", US + i * DAY) for i in range(5)])
    got = detect_dropped(conn, now_us=US + 5 * DAY, quiet_days=7)
    assert "active.test" not in {s.host for s in got}


def test_one_off_visit_is_not_dropped(conn):
    """한 번 들른 곳이 조용한 건 당연하다."""
    ingest_records(conn, [visit("https://once.test/p", US)])
    got = detect_dropped(conn, now_us=US + 30 * DAY, quiet_days=7)
    assert "once.test" not in {s.host for s in got}


# ── restricted 는 신호가 되지 않는다 ──────────────────────────────────────────

def test_restricted_host_produces_no_signal(conn):
    ingest_records(conn, [
        visit("https://mybank.test/", US),
        visit("https://mybank.test/login", US + 10),
    ])
    conn.execute("INSERT INTO domains(host, category, sensitivity, label_source)"
                 " VALUES ('mybank.test','finance','restricted','manual')")
    conn.commit()
    got = detect_all(conn, since_us=US - DAY, until_us=US + DAY, now_us=US + DAY)
    assert all(s.host != "mybank.test" for s in got)


def test_restricted_can_be_included_explicitly(conn):
    ingest_records(conn, [
        visit("https://mybank.test/", US),
        visit("https://mybank.test/signup", US + 10),
    ])
    conn.execute("INSERT INTO domains(host, category, sensitivity, label_source)"
                 " VALUES ('mybank.test','finance','restricted','manual')")
    conn.commit()
    got = detect_all(conn, since_us=US - DAY, until_us=US + DAY, now_us=US + DAY,
                     include_restricted=True)
    assert any(s.host == "mybank.test" for s in got)


# ── 신호의 형태 — 상위 계층이 의존한다 ────────────────────────────────────────

def test_signal_has_a_stable_key(conn):
    ingest_records(conn, [visit("https://svc.test/signup", US)])
    a = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)[0]
    b = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)[0]
    assert a.key == b.key, "같은 입력에 같은 키가 나와야 중복 제거가 가능하다"


def test_different_signals_have_different_keys(conn):
    ingest_records(conn, [
        visit("https://a.test/signup", US),
        visit("https://b.test/signup", US + 10),
    ])
    got = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)
    assert len({s.key for s in got}) == len(got)


def test_signal_carries_evidence(conn):
    """triage 가 판단할 근거를 신호가 들고 와야 한다. 다시 조회하게 만들지 않는다."""
    ingest_records(conn, [visit("https://svc.test/signup", US)])
    s = detect_new_entry(conn, since_us=US - DAY, until_us=US + DAY)[0]
    assert isinstance(s.evidence, dict)
    assert s.evidence


def test_signal_kind_is_one_of_the_four(conn):
    ingest_records(conn, [
        visit("https://svc.test/signup", US),
        visit("https://topic.test/p", US + 1 * DAY),
        visit("https://topic.test/p", US + 2 * DAY),
        visit("https://topic.test/p", US + 3 * DAY),
    ])
    got = detect_all(conn, since_us=US - DAY, until_us=US + 10 * DAY, now_us=US + 10 * DAY)
    assert {s.kind for s in got} <= {"new_entry", "unresolved", "recurring", "dropped"}


# ── 결정성·안전성 ────────────────────────────────────────────────────────────

def test_detection_is_deterministic(conn):
    ingest_records(conn, [visit(f"https://h{i}.test/signup", US + i * 60) for i in range(5)])
    a = [s.key for s in detect_all(conn, since_us=US - DAY, until_us=US + DAY, now_us=US + DAY)]
    b = [s.key for s in detect_all(conn, since_us=US - DAY, until_us=US + DAY, now_us=US + DAY)]
    assert a == b


def test_empty_database_yields_no_signals(conn):
    assert detect_all(conn, since_us=US, until_us=US + DAY, now_us=US + DAY) == []


def test_host_without_hostname_is_skipped(conn):
    ingest_records(conn, [visit("not-a-url", US)])
    got = detect_all(conn, since_us=US - DAY, until_us=US + DAY, now_us=US + DAY)
    assert all(s.host for s in got if s.host is not None)
