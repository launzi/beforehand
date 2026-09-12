"""추출 계약 테스트 — Chrome SQLite → 레코드 스트림.

이 모듈의 급소는 **ingest 와의 계약 일치**다. 형식이 어긋나면 ingest 가 전부
skipped 로 세면서 파이프라인은 완주한다 — 조용한 유실이다.
그래서 마지막에 extract → ingest → query 왕복을 실제로 돌린다.

두 번째 급소는 **스크럽하지 않는 것**이다. 원본 보존이 재처리의 근거이므로
extract 는 원문을 그대로 내보내고 스크럽은 ingest 가 한다.

⚠ 합성 Chrome DB 만 쓴다. 실제 브라우징 기록을 읽지 않는다.
"""

import sqlite3

import pytest

from browsing.extract import extract_records

US = 13404038416000000
DAY = 86_400_000_000

CHROME_SCHEMA = """
CREATE TABLE urls(id INTEGER PRIMARY KEY AUTOINCREMENT, url LONGVARCHAR,
    title LONGVARCHAR, visit_count INTEGER DEFAULT 0 NOT NULL,
    typed_count INTEGER DEFAULT 0 NOT NULL, last_visit_time INTEGER NOT NULL,
    hidden INTEGER DEFAULT 0 NOT NULL);
CREATE TABLE visits(id INTEGER PRIMARY KEY AUTOINCREMENT, url INTEGER NOT NULL,
    visit_time INTEGER NOT NULL, from_visit INTEGER, external_referrer_url TEXT,
    transition INTEGER DEFAULT 0 NOT NULL, segment_id INTEGER,
    visit_duration INTEGER DEFAULT 0 NOT NULL);
CREATE TABLE keyword_search_terms(keyword_id INTEGER NOT NULL, url_id INTEGER NOT NULL,
    term LONGVARCHAR NOT NULL, normalized_term LONGVARCHAR NOT NULL);
CREATE TABLE downloads(id INTEGER PRIMARY KEY, guid VARCHAR NOT NULL,
    current_path LONGVARCHAR NOT NULL, target_path LONGVARCHAR NOT NULL,
    start_time INTEGER NOT NULL, received_bytes INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL, state INTEGER NOT NULL,
    referrer VARCHAR NOT NULL DEFAULT '', site_url VARCHAR NOT NULL DEFAULT '',
    tab_url VARCHAR NOT NULL DEFAULT '', mime_type VARCHAR(255) NOT NULL DEFAULT '');
"""


@pytest.fixture
def chrome_db(tmp_path):
    """실제 Chrome 스키마를 본뜬 합성 DB."""
    p = tmp_path / "History"
    c = sqlite3.connect(p)
    c.executescript(CHROME_SCHEMA)
    c.execute("INSERT INTO urls(id,url,title,last_visit_time) VALUES (1,?,?,?)",
              ("https://example.com/a?code=SENSITIVE", "Page A", US + 100))
    c.execute("INSERT INTO urls(id,url,title,last_visit_time) VALUES (2,?,?,?)",
              ("https://search.test/s?q=nemotron", "Search", US + DAY))
    # visit 1 -> visit 2 유입 체인
    c.execute("INSERT INTO visits(id,url,visit_time,from_visit,transition,visit_duration)"
              " VALUES (1,1,?,0,805306368,5000000)", (US,))
    c.execute("INSERT INTO visits(id,url,visit_time,from_visit,transition,visit_duration)"
              " VALUES (2,1,?,1,805306368,0)", (US + 100,))
    c.execute("INSERT INTO visits(id,url,visit_time,from_visit,transition,visit_duration)"
              " VALUES (3,2,?,0,805306368,0)", (US + DAY,))
    c.execute("INSERT INTO keyword_search_terms VALUES (1,2,?,?)",
              ("nemotron", "nemotron"))
    c.execute("INSERT INTO downloads(id,guid,current_path,target_path,start_time,"
              "received_bytes,total_bytes,state,referrer,mime_type)"
              " VALUES (1,'g-1','/tmp/f','/tmp/f.pdf',?,10,10,1,?,'application/pdf')",
              (US + 200, "https://example.com/cb?code=SENSITIVE"))
    c.commit()
    c.close()
    return p


def kinds(records, kind):
    return [r for r in records if r["kind"] == kind]


# ── 기본 추출 ────────────────────────────────────────────────────────────────

def test_extracts_all_visits(chrome_db):
    recs = list(extract_records(chrome_db, profile="Default"))
    assert len(kinds(recs, "visit")) == 3


def test_visit_record_matches_ingest_contract(chrome_db):
    v = kinds(list(extract_records(chrome_db, profile="Default")), "visit")[0]
    for key in ("kind", "profile", "url", "title", "visit_time_us",
                "transition", "duration_us", "from_visit_key"):
        assert key in v, f"ingest 계약에 필요한 {key} 가 없다"
    assert v["profile"] == "Default"


def test_urls_are_not_scrubbed_here(chrome_db):
    """원본 보존이 재처리의 근거다. 스크럽은 ingest 가 한다."""
    recs = list(extract_records(chrome_db, profile="Default"))
    assert any("code=SENSITIVE" in r["url"] for r in kinds(recs, "visit"))


def test_duration_is_microseconds_not_converted(chrome_db):
    v = [r for r in kinds(list(extract_records(chrome_db, profile="Default")), "visit")
         if r["visit_time_us"] == US][0]
    assert v["duration_us"] == 5000000


# ── 워터마크 ─────────────────────────────────────────────────────────────────

def test_since_us_filters_older_visits(chrome_db):
    # 워터마크는 exclusive 이므로 US+DAY 를 받으려면 그보다 앞을 줘야 한다.
    recs = list(extract_records(chrome_db, profile="Default", since_us=US + DAY - 1))
    assert len(kinds(recs, "visit")) == 1


def test_since_us_is_exclusive(chrome_db):
    """워터마크는 '마지막으로 받은 시각'이므로 그 시각 자체는 다시 보내지 않는다."""
    recs = list(extract_records(chrome_db, profile="Default", since_us=US))
    times = [r["visit_time_us"] for r in kinds(recs, "visit")]
    assert US not in times


def test_no_since_returns_everything(chrome_db):
    recs = list(extract_records(chrome_db, profile="Default"))
    assert len(kinds(recs, "visit")) == 3


# ── 유입 체인 ────────────────────────────────────────────────────────────────

def test_from_visit_is_resolved_to_a_key_not_an_integer(chrome_db):
    """Chrome 내부 정수 id 를 그대로 넘기면 프로파일 재설치 후 다른 방문을 가리킨다."""
    recs = kinds(list(extract_records(chrome_db, profile="Default")), "visit")
    child = [r for r in recs if r["visit_time_us"] == US + 100][0]
    assert isinstance(child["from_visit_key"], str)
    assert len(child["from_visit_key"]) == 64      # sha256 hexdigest


def test_from_visit_zero_becomes_none(chrome_db):
    recs = kinds(list(extract_records(chrome_db, profile="Default")), "visit")
    root = [r for r in recs if r["visit_time_us"] == US][0]
    assert root["from_visit_key"] is None


def test_from_visit_resolves_even_when_parent_is_outside_the_window(chrome_db):
    """증분 창 밖의 부모도 원본 DB 에는 있으므로 해석할 수 있어야 한다."""
    recs = kinds(list(extract_records(chrome_db, profile="Default",
                                      since_us=US + 50)), "visit")
    child = [r for r in recs if r["visit_time_us"] == US + 100][0]
    assert child["from_visit_key"] is not None


# ── 검색어·다운로드 ──────────────────────────────────────────────────────────

def test_search_records_are_extracted(chrome_db):
    s = kinds(list(extract_records(chrome_db, profile="Default")), "search")
    assert len(s) == 1
    assert s[0]["term"] == "nemotron"


def test_search_record_carries_a_timestamp(chrome_db):
    """keyword_search_terms 에는 시각 컬럼이 없다. url 의 방문 시각으로 채운다."""
    s = kinds(list(extract_records(chrome_db, profile="Default")), "search")[0]
    assert isinstance(s["first_seen_us"], int)
    assert s["first_seen_us"] > 0


def test_download_records_are_extracted(chrome_db):
    d = kinds(list(extract_records(chrome_db, profile="Default")), "download")
    assert len(d) == 1
    assert d[0]["guid"] == "g-1"


def test_download_referrer_is_carried_unscrubbed(chrome_db):
    d = kinds(list(extract_records(chrome_db, profile="Default")), "download")[0]
    assert "code=SENSITIVE" in d["referrer"]


# ── 안전성 ───────────────────────────────────────────────────────────────────

def test_empty_database_yields_nothing(tmp_path):
    p = tmp_path / "Empty"
    c = sqlite3.connect(p)
    c.executescript(CHROME_SCHEMA)
    c.commit()
    c.close()
    assert list(extract_records(p, profile="Default")) == []


def test_missing_file_raises_clearly(tmp_path):
    with pytest.raises((FileNotFoundError, sqlite3.Error, ValueError)):
        list(extract_records(tmp_path / "nope", profile="Default"))


def test_source_database_is_not_modified(chrome_db):
    before = chrome_db.stat().st_mtime_ns
    list(extract_records(chrome_db, profile="Default"))
    assert chrome_db.stat().st_mtime_ns == before


# ── 왕복: 계약이 실제로 맞물리는가 ────────────────────────────────────────────

def test_extract_to_ingest_to_query_roundtrip(chrome_db):
    """형식이 어긋나면 ingest 가 조용히 skipped 로 세고 파이프라인은 완주한다."""
    from browsing.ingest import init_db, ingest_records
    from browsing.query import stats

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    recs = list(extract_records(chrome_db, profile="Default"))
    result = ingest_records(conn, recs)

    assert result.get("skipped", 0) == 0, f"skipped 가 있으면 계약 불일치: {result}"
    s = stats(conn)
    assert s["visits"] == 3
    assert s["searches"] == 1
    assert s["downloads"] == 1
    conn.close()


def test_roundtrip_scrubs_at_ingest_not_extract(chrome_db):
    from browsing.ingest import init_db, ingest_records

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    ingest_records(conn, list(extract_records(chrome_db, profile="Default")))
    stored = [r[0] for r in conn.execute("SELECT url FROM urls").fetchall()]
    assert all("SENSITIVE" not in u for u in stored)
    assert any("<redacted:" in u for u in stored)
    conn.close()
