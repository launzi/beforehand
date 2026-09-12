"""
Ingest layer for browsing-history pipeline.

Normalizes Chrome history records into SQLite with idempotent upserts.
All URL-bearing fields are scrubbed before storage to prevent leaks.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from typing import Iterable

from browsing.scrub import scrub_url


# Chrome epoch: microseconds since 1601-01-01 UTC
CHROME_EPOCH_OFFSET_SECONDS = 11644473600
KST_OFFSET = timedelta(hours=9)


def chrome_us_to_utc(chrome_us: int) -> str:
    """Convert Chrome microseconds since 1601-01-01 to ISO 8601 UTC string."""
    if chrome_us == 0:
        return "1601-01-01T00:00:00+00:00"
    # Convert microseconds to seconds since Unix epoch
    unix_seconds = chrome_us / 1_000_000 - CHROME_EPOCH_OFFSET_SECONDS
    dt = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _chrome_us_to_kst(chrome_us: int) -> str:
    """Convert Chrome microseconds to ISO 8601 Asia/Seoul (UTC+9) string."""
    if chrome_us == 0:
        return "1601-01-01T09:00:00+09:00"
    unix_seconds = chrome_us / 1_000_000 - CHROME_EPOCH_OFFSET_SECONDS
    dt_utc = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    dt_kst = dt_utc + KST_OFFSET
    return dt_kst.isoformat(timespec="seconds")


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _parse_host_path(url: str) -> tuple[str | None, str | None]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or None
        path = parsed.path or None
        return host, path
    except Exception:
        return None, None


def init_db(conn: sqlite3.Connection) -> None:
    """Create schema tables if they do not exist. Safe to call repeatedly."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS urls (
            url_key TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            host TEXT,
            path TEXT,
            title TEXT,
            first_seen_utc TEXT,
            last_seen_utc TEXT,
            scrub_status TEXT DEFAULT 'ok'
        );

        CREATE TABLE IF NOT EXISTS visits (
            visit_key TEXT PRIMARY KEY,
            profile TEXT NOT NULL,
            url_key TEXT NOT NULL,
            visit_time_us INTEGER NOT NULL,
            visit_time_utc TEXT NOT NULL,
            visit_time_kst TEXT NOT NULL,
            transition_core INTEGER,
            transition_qualifiers INTEGER,
            duration_ms INTEGER,
            from_visit_key TEXT
        );

        CREATE TABLE IF NOT EXISTS searches (
            search_key TEXT PRIMARY KEY,
            profile TEXT,
            url_key TEXT,
            term TEXT NOT NULL,
            normalized_term TEXT,
            first_seen_utc TEXT
        );

        CREATE TABLE IF NOT EXISTS downloads (
            download_key TEXT PRIMARY KEY,
            profile TEXT,
            target_path TEXT,
            referrer_url_key TEXT,
            start_time_utc TEXT,
            received_bytes INTEGER,
            mime_type TEXT,
            state INTEGER
        );

        CREATE TABLE IF NOT EXISTS domains (
            host TEXT PRIMARY KEY,
            category TEXT,
            sensitivity TEXT,
            label_source TEXT
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            profile TEXT PRIMARY KEY,
            last_visit_time_us INTEGER,
            last_run_utc TEXT,
            last_rows INTEGER
        );
    """)


def _validate_visit(rec: dict) -> bool:
    required = ("profile", "url", "visit_time_us", "transition", "duration_us")
    return all(k in rec for k in required) and isinstance(rec["visit_time_us"], int)


def _validate_search(rec: dict) -> bool:
    required = ("profile", "url", "term", "first_seen_us")
    return all(k in rec for k in required) and isinstance(rec["first_seen_us"], int)


def _validate_download(rec: dict) -> bool:
    required = ("profile", "guid", "target_path", "start_time_us", "received_bytes")
    return all(k in rec for k in required) and isinstance(rec["start_time_us"], int)


def ingest_records(conn: sqlite3.Connection, records: Iterable[dict]) -> dict:
    """Ingest records, upsert into tables, update watermark. Return counters."""
    counters = {"visits": 0, "urls": 0, "searches": 0, "downloads": 0, "skipped": 0}
    profile_max_visit_us: dict[str, int] = {}
    profiles_touched: set[str] = set()

    for rec in records:
        kind = rec.get("kind")
        if kind == "visit":
            if not _validate_visit(rec):
                counters["skipped"] += 1
                continue

            profile = rec["profile"]
            raw_url = rec["url"]
            title = rec.get("title")
            visit_time_us = rec["visit_time_us"]
            transition = rec["transition"]
            duration_us = rec["duration_us"]
            from_visit_key = rec.get("from_visit_key")

            scrubbed_url, scrub_status = scrub_url(raw_url)
            url_key = _sha256_hex(scrubbed_url)
            host, path = _parse_host_path(scrubbed_url)
            visit_time_utc = chrome_us_to_utc(visit_time_us)
            visit_time_kst = _chrome_us_to_kst(visit_time_us)
            transition_core = transition & 0xFF
            transition_qualifiers = transition & ~0xFF
            duration_ms = duration_us // 1000
            visit_key = _sha256_hex(f"{profile}|{url_key}|{visit_time_us}")

            # Upsert urls
            cur = conn.execute(
                """
                INSERT INTO urls (url_key, url, host, path, title, first_seen_utc, last_seen_utc, scrub_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_key) DO UPDATE SET
                    title = CASE WHEN excluded.title IS NOT NULL AND excluded.title != '' THEN excluded.title ELSE urls.title END,
                    first_seen_utc = CASE WHEN excluded.first_seen_utc < urls.first_seen_utc THEN excluded.first_seen_utc ELSE urls.first_seen_utc END,
                    last_seen_utc = CASE WHEN excluded.last_seen_utc > urls.last_seen_utc THEN excluded.last_seen_utc ELSE urls.last_seen_utc END,
                    scrub_status = excluded.scrub_status
                """,
                (url_key, scrubbed_url, host, path, title, visit_time_utc, visit_time_utc, scrub_status),
            )
            if cur.rowcount > 0:
                counters["urls"] += 1

            # Insert visit (idempotent)
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO visits
                (visit_key, profile, url_key, visit_time_us, visit_time_utc, visit_time_kst,
                 transition_core, transition_qualifiers, duration_ms, from_visit_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visit_key,
                    profile,
                    url_key,
                    visit_time_us,
                    visit_time_utc,
                    visit_time_kst,
                    transition_core,
                    transition_qualifiers,
                    duration_ms,
                    from_visit_key,
                ),
            )
            if cur.rowcount > 0:
                counters["visits"] += 1

            # Track watermark
            profiles_touched.add(profile)
            if profile not in profile_max_visit_us or visit_time_us > profile_max_visit_us[profile]:
                profile_max_visit_us[profile] = visit_time_us

        elif kind == "search":
            if not _validate_search(rec):
                counters["skipped"] += 1
                continue

            profile = rec["profile"]
            raw_url = rec["url"]
            term = rec["term"]
            first_seen_us = rec["first_seen_us"]

            scrubbed_url, scrub_status = scrub_url(raw_url)
            url_key = _sha256_hex(scrubbed_url)
            normalized_term = term.strip().lower()
            search_key = _sha256_hex(f"{profile}|{url_key}|{term}")
            first_seen_utc = chrome_us_to_utc(first_seen_us)

            # Ensure url exists
            conn.execute(
                """
                INSERT OR IGNORE INTO urls (url_key, url, host, path, first_seen_utc, last_seen_utc, scrub_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url_key,
                    scrubbed_url,
                    *_parse_host_path(scrubbed_url),
                    first_seen_utc,
                    first_seen_utc,
                    scrub_status,
                ),
            )

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO searches
                (search_key, profile, url_key, term, normalized_term, first_seen_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (search_key, profile, url_key, term, normalized_term, first_seen_utc),
            )
            if cur.rowcount > 0:
                counters["searches"] += 1

            profiles_touched.add(profile)

        elif kind == "download":
            if not _validate_download(rec):
                counters["skipped"] += 1
                continue

            profile = rec["profile"]
            guid = rec["guid"]
            target_path = rec["target_path"]
            referrer = rec.get("referrer")
            start_time_us = rec["start_time_us"]
            received_bytes = rec["received_bytes"]
            mime_type = rec.get("mime_type")
            state = rec.get("state")

            referrer_url_key = None
            if referrer:
                scrubbed_referrer, _ = scrub_url(referrer)
                referrer_url_key = _sha256_hex(scrubbed_referrer)

            download_key = _sha256_hex(f"{profile}|{guid}")
            start_time_utc = chrome_us_to_utc(start_time_us)

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO downloads
                (download_key, profile, target_path, referrer_url_key, start_time_utc,
                 received_bytes, mime_type, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    download_key,
                    profile,
                    target_path,
                    referrer_url_key,
                    start_time_utc,
                    received_bytes,
                    mime_type,
                    state,
                ),
            )
            if cur.rowcount > 0:
                counters["downloads"] += 1

            profiles_touched.add(profile)

        else:
            counters["skipped"] += 1
            continue

    # Update sync_state for touched profiles
    if profiles_touched:
        last_run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for profile in profiles_touched:
            max_us = profile_max_visit_us.get(profile)
            if max_us is None:
                # No visits for this profile in this batch; just update last_run_utc and last_rows
                conn.execute(
                    """
                    INSERT INTO sync_state (profile, last_visit_time_us, last_run_utc, last_rows)
                    VALUES (?, NULL, ?, 0)
                    ON CONFLICT(profile) DO UPDATE SET
                        last_run_utc = excluded.last_run_utc,
                        last_rows = 0
                    """,
                    (profile, last_run_utc),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sync_state (profile, last_visit_time_us, last_run_utc, last_rows)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(profile) DO UPDATE SET
                        last_visit_time_us = CASE WHEN excluded.last_visit_time_us > sync_state.last_visit_time_us
                                                  THEN excluded.last_visit_time_us
                                                  ELSE sync_state.last_visit_time_us END,
                        last_run_utc = excluded.last_run_utc,
                        last_rows = excluded.last_rows
                    """,
                    (profile, max_us, last_run_utc, counters["visits"]),
                )

    conn.commit()
    return counters


def get_watermark(conn: sqlite3.Connection, profile: str) -> int | None:
    """Return last_visit_time_us for profile, or None if never seen."""
    row = conn.execute(
        "SELECT last_visit_time_us FROM sync_state WHERE profile = ?",
        (profile,),
    ).fetchone()
    return row[0] if row else None
