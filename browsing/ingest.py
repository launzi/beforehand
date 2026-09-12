"""
browsing.ingest — Idempotent ingestion layer for browsing history.

Normalizes Chrome history records into SQLite with content-addressed keys so that
re-ingesting the same data never creates duplicates. All URL-bearing fields pass
through scrub_url before storage. Counters reflect actual row-level changes.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Iterable
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 fallback (not needed for 3.12)
    from backports.zoneinfo import ZoneInfo  # type: ignore

from browsing.scrub import scrub_url

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
CHROME_EPOCH_OFFSET_US = 11_644_473_600_000_000  # microseconds 1601-01-01 -> 1970-01-01
KST = ZoneInfo("Asia/Seoul")

# ----------------------------------------------------------------------
# Timestamp conversion
# ----------------------------------------------------------------------
def chrome_us_to_utc(chrome_us: int) -> str:
    """
    Convert Chrome microseconds since 1601-01-01 UTC to ISO 8601 UTC string.

    Input 0 returns "1601-01-01T00:00:00+00:00" (the Chrome epoch) without crashing.
    """
    if chrome_us <= 0:
        return "1601-01-01T00:00:00+00:00"
    unix_us = chrome_us - CHROME_EPOCH_OFFSET_US
    # unix_us can be negative for very old dates; fromtimestamp handles that.
    dt = datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _chrome_us_to_kst(chrome_us: int) -> str:
    """Same instant expressed in Asia/Seoul (UTC+9)."""
    if chrome_us <= 0:
        return "1601-01-01T09:00:00+09:00"
    unix_us = chrome_us - CHROME_EPOCH_OFFSET_US
    dt_utc = datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc)
    dt_kst = dt_utc.astimezone(KST)
    return dt_kst.isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# Key derivation
# ----------------------------------------------------------------------
def _url_key(scrubbed_url: str) -> str:
    return hashlib.sha256(scrubbed_url.encode("utf-8")).hexdigest()


def _visit_key(profile: str, url_key: str, visit_time_us: int) -> str:
    return hashlib.sha256(f"{profile}|{url_key}|{visit_time_us}".encode("utf-8")).hexdigest()


def _search_key(profile: str, url_key: str, term: str) -> str:
    return hashlib.sha256(f"{profile}|{url_key}|{term}".encode("utf-8")).hexdigest()


def _download_key(profile: str, guid: str) -> str:
    return hashlib.sha256(f"{profile}|{guid}".encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# URL parsing helpers
# ----------------------------------------------------------------------
def _parse_host_path(url: str) -> tuple[str | None, str | None]:
    """Extract host and path from a scrubbed URL."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        path = parsed.path or "/"
        return host, path
    except Exception:
        return None, None


# ----------------------------------------------------------------------
# Schema initialization
# ----------------------------------------------------------------------
def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist. Safe to call repeatedly."""
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS urls (
            url_key      TEXT PRIMARY KEY,
            url          TEXT NOT NULL,
            host         TEXT,
            path         TEXT,
            title        TEXT,
            first_seen_utc TEXT,
            last_seen_utc  TEXT,
            scrub_status TEXT DEFAULT 'ok'
        );

        CREATE TABLE IF NOT EXISTS visits (
            visit_key           TEXT PRIMARY KEY,
            profile             TEXT NOT NULL,
            url_key             TEXT NOT NULL,
            visit_time_us       INTEGER NOT NULL,
            visit_time_utc      TEXT NOT NULL,
            visit_time_kst      TEXT NOT NULL,
            transition_core     INTEGER,
            transition_qualifiers INTEGER,
            duration_ms         INTEGER,
            from_visit_key      TEXT
        );

        CREATE TABLE IF NOT EXISTS searches (
            search_key      TEXT PRIMARY KEY,
            profile         TEXT,
            url_key         TEXT,
            term            TEXT NOT NULL,
            normalized_term TEXT,
            first_seen_utc  TEXT
        );

        CREATE TABLE IF NOT EXISTS downloads (
            download_key    TEXT PRIMARY KEY,
            profile         TEXT,
            target_path     TEXT,
            referrer_url_key TEXT,
            start_time_utc  TEXT,
            received_bytes  INTEGER,
            mime_type       TEXT,
            state           INTEGER
        );

        CREATE TABLE IF NOT EXISTS domains (
            host          TEXT PRIMARY KEY,
            category      TEXT,
            sensitivity   TEXT,
            label_source  TEXT
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            profile           TEXT PRIMARY KEY,
            last_visit_time_us INTEGER,
            last_run_utc      TEXT,
            last_rows         INTEGER
        );
    """)
    conn.commit()


# ----------------------------------------------------------------------
# Watermark access
# ----------------------------------------------------------------------
def get_watermark(conn: sqlite3.Connection, profile: str) -> int | None:
    """
    Return the maximum visit_time_us ever seen for `profile`, or None if never seen.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT last_visit_time_us FROM sync_state WHERE profile = ?",
        (profile,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


# ----------------------------------------------------------------------
# Ingestion
# ----------------------------------------------------------------------
def ingest_records(
    conn: sqlite3.Connection, records: Iterable[dict]
) -> dict:
    """
    Ingest a batch of records. Returns counters reflecting actual row changes.
    """
    # Snapshot row counts before
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM urls")
    urls_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM visits")
    visits_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM searches")
    searches_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM downloads")
    downloads_before = cur.fetchone()[0]

    counters = {
        "visits": 0,
        "urls": 0,
        "searches": 0,
        "downloads": 0,
        "deduped": 0,
        "skipped": 0,
    }

    # Track max visit_time_us per profile for watermark update
    profile_max_visit_us: dict[str, int] = {}

    for rec in records:
        kind = rec.get("kind")
        if kind not in ("visit", "search", "download"):
            counters["skipped"] += 1
            continue

        try:
            if kind == "visit":
                _ingest_visit(conn, rec, counters, profile_max_visit_us)
            elif kind == "search":
                _ingest_search(conn, rec, counters)
            elif kind == "download":
                _ingest_download(conn, rec, counters)
        except (KeyError, TypeError, ValueError):
            # Invalid/missing fields — count and continue
            counters["skipped"] += 1

    # Snapshot row counts after
    cur.execute("SELECT COUNT(*) FROM urls")
    urls_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM visits")
    visits_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM searches")
    searches_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM downloads")
    downloads_after = cur.fetchone()[0]

    counters["urls"] = urls_after - urls_before
    counters["visits"] = visits_after - visits_before
    counters["searches"] = searches_after - searches_before
    counters["downloads"] = downloads_after - downloads_before

    # Update sync_state watermarks
    if profile_max_visit_us:
        run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        total_rows = sum(
            counters[k] for k in ("visits", "urls", "searches", "downloads")
        )
        for profile, max_us in profile_max_visit_us.items():
            cur.execute(
                """
                INSERT INTO sync_state (profile, last_visit_time_us, last_run_utc, last_rows)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile) DO UPDATE SET
                    last_visit_time_us = CASE
                        WHEN excluded.last_visit_time_us > sync_state.last_visit_time_us
                        THEN excluded.last_visit_time_us
                        ELSE sync_state.last_visit_time_us
                    END,
                    last_run_utc = excluded.last_run_utc,
                    last_rows = excluded.last_rows
                """,
                (profile, max_us, run_utc, total_rows),
            )
        conn.commit()

    return counters


# ----------------------------------------------------------------------
# Per-kind ingestion helpers
# ----------------------------------------------------------------------
def _ingest_visit(
    conn: sqlite3.Connection,
    rec: dict,
    counters: dict,
    profile_max_visit_us: dict[str, int],
) -> None:
    # Validate required fields
    profile = rec["profile"]
    raw_url = rec["url"]
    visit_time_us = rec["visit_time_us"]
    transition = rec["transition"]
    duration_us = rec["duration_us"]
    # Optional
    title = rec.get("title")
    from_visit_key = rec.get("from_visit_key")

    # Scrub URL
    scrubbed_url, scrub_status = scrub_url(raw_url)
    ukey = _url_key(scrubbed_url)
    host, path = _parse_host_path(scrubbed_url)
    visit_time_utc = chrome_us_to_utc(visit_time_us)
    visit_time_kst = _chrome_us_to_kst(visit_time_us)
    vkey = _visit_key(profile, ukey, visit_time_us)
    transition_core = transition & 0xFF
    transition_qualifiers = transition & ~0xFF
    duration_ms = duration_us // 1000

    cur = conn.cursor()

    # Upsert urls (DO UPDATE to refresh title and widen first/last_seen)
    cur.execute(
        """
        INSERT INTO urls (url_key, url, host, path, title, first_seen_utc, last_seen_utc, scrub_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url_key) DO UPDATE SET
            title = CASE WHEN excluded.title IS NOT NULL AND excluded.title != ''
                         THEN excluded.title ELSE urls.title END,
            first_seen_utc = MIN(urls.first_seen_utc, excluded.first_seen_utc),
            last_seen_utc = MAX(urls.last_seen_utc, excluded.last_seen_utc),
            scrub_status = excluded.scrub_status
        """,
        (ukey, scrubbed_url, host, path, title, visit_time_utc, visit_time_utc, scrub_status),
    )

    # Insert visit (DO NOTHING on conflict)
    cur.execute(
        """
        INSERT INTO visits (visit_key, profile, url_key, visit_time_us, visit_time_utc,
                            visit_time_kst, transition_core, transition_qualifiers,
                            duration_ms, from_visit_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(visit_key) DO NOTHING
        """,
        (
            vkey,
            profile,
            ukey,
            visit_time_us,
            visit_time_utc,
            visit_time_kst,
            transition_core,
            transition_qualifiers,
            duration_ms,
            from_visit_key,
        ),
    )

    # Detect dedup via rowcount (0 means key existed)
    if cur.rowcount == 0:
        counters["deduped"] += 1

    # Track max visit_time_us for watermark
    prev = profile_max_visit_us.get(profile)
    if prev is None or visit_time_us > prev:
        profile_max_visit_us[profile] = visit_time_us


def _ingest_search(conn: sqlite3.Connection, rec: dict, counters: dict) -> None:
    profile = rec["profile"]
    raw_url = rec["url"]
    term = rec["term"]
    first_seen_us = rec["first_seen_us"]

    scrubbed_url, scrub_status = scrub_url(raw_url)
    ukey = _url_key(scrubbed_url)
    host, path = _parse_host_path(scrubbed_url)
    first_seen_utc = chrome_us_to_utc(first_seen_us)
    normalized_term = term.strip().lower()
    skey = _search_key(profile, ukey, term)

    cur = conn.cursor()

    # Upsert urls
    cur.execute(
        """
        INSERT INTO urls (url_key, url, host, path, title, first_seen_utc, last_seen_utc, scrub_status)
        VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
        ON CONFLICT(url_key) DO UPDATE SET
            first_seen_utc = MIN(urls.first_seen_utc, excluded.first_seen_utc),
            last_seen_utc = MAX(urls.last_seen_utc, excluded.last_seen_utc),
            scrub_status = excluded.scrub_status
        """,
        (ukey, scrubbed_url, host, path, first_seen_utc, first_seen_utc, scrub_status),
    )

    # Insert search
    cur.execute(
        """
        INSERT INTO searches (search_key, profile, url_key, term, normalized_term, first_seen_utc)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(search_key) DO NOTHING
        """,
        (skey, profile, ukey, term, normalized_term, first_seen_utc),
    )

    if cur.rowcount == 0:
        counters["deduped"] += 1


def _ingest_download(conn: sqlite3.Connection, rec: dict, counters: dict) -> None:
    profile = rec["profile"]
    guid = rec["guid"]
    target_path = rec["target_path"]
    start_time_us = rec["start_time_us"]
    received_bytes = rec["received_bytes"]
    # Optional
    referrer = rec.get("referrer")
    mime_type = rec.get("mime_type")
    state = rec.get("state")

    dkey = _download_key(profile, guid)
    start_time_utc = chrome_us_to_utc(start_time_us)

    referrer_url_key = None
    if referrer:
        scrubbed_referrer, _ = scrub_url(referrer)
        referrer_url_key = _url_key(scrubbed_referrer)

    cur = conn.cursor()

    # Insert download
    cur.execute(
        """
        INSERT INTO downloads (download_key, profile, target_path, referrer_url_key,
                               start_time_utc, received_bytes, mime_type, state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(download_key) DO NOTHING
        """,
        (
            dkey,
            profile,
            target_path,
            referrer_url_key,
            start_time_utc,
            received_bytes,
            mime_type,
            state,
        ),
    )

    if cur.rowcount == 0:
        counters["deduped"] += 1
