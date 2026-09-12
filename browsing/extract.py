"""
Extraction layer for Chrome browsing history.

Reads the SQLite history database in read-only mode and emits normalized
records for the ingest layer.  The public API is a single generator function
`extract_records`.
"""

import sqlite3
import hashlib
from typing import Iterator

from browsing.scrub import scrub_url


def extract_records(db_path: str, *, profile: str, since_us: int | None = None) -> Iterator[dict]:
    """
    Yield visit, search, and download records from a Chrome History file.

    Parameters
    ----------
    db_path: Path to the SQLite database (e.g. ".../History").
    profile: Logical profile name, used in from_visit_key hashing.
    since_us: Exclusive watermark on visits.visit_time.  Only visits with
              visit_time > since_us are emitted.  None means no filtering.

    Yields
    ------
    dict records matching the ingest layer contract exactly.

    Raises
    ------
    FileNotFoundError or sqlite3.Error if the database cannot be opened read-only.
    """
    # Read-only URI connection; guarantees we never modify the file or its mtime.
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row

        # ------------------------------------------------------------------
        # Pre-compute helper maps used by searches (and potentially visits).
        # ------------------------------------------------------------------
        # Earliest visit_time per url_id across the *entire* visits table.
        min_visit_time: dict[int, int] = {}
        for row in conn.execute("SELECT url, MIN(visit_time) FROM visits GROUP BY url"):
            min_visit_time[row[0]] = row[1]

        # Fallback: urls.last_visit_time per url_id.
        last_visit_time: dict[int, int] = {}
        for row in conn.execute("SELECT id, last_visit_time FROM urls"):
            last_visit_time[row[0]] = row[1]

        # ------------------------------------------------------------------
        # VISITS
        # ------------------------------------------------------------------
        # Join visits -> urls (current) and LEFT JOIN parent visit -> its url.
        # The parent's visit_time is needed for the from_visit_key hash.
        if since_us is not None:
            visit_sql = """
                SELECT v.visit_time, v.from_visit, v.transition, v.visit_duration,
                       u.url AS current_url, u.title AS current_title,
                       pu.url AS parent_url, p.visit_time AS parent_visit_time
                FROM visits v
                JOIN urls u ON v.url = u.id
                LEFT JOIN visits p ON v.from_visit = p.id
                LEFT JOIN urls pu ON p.url = pu.id
                WHERE v.visit_time > ?
            """
            visit_params = (since_us,)
        else:
            visit_sql = """
                SELECT v.visit_time, v.from_visit, v.transition, v.visit_duration,
                       u.url AS current_url, u.title AS current_title,
                       pu.url AS parent_url, p.visit_time AS parent_visit_time
                FROM visits v
                JOIN urls u ON v.url = u.id
                LEFT JOIN visits p ON v.from_visit = p.id
                LEFT JOIN urls pu ON p.url = pu.id
            """
            visit_params = ()

        for row in conn.execute(visit_sql, visit_params):
            # Resolve from_visit_key using the *parent's* scrubbed URL and visit_time.
            from_visit_key = None
            if row["from_visit"] and row["parent_url"] is not None and row["parent_visit_time"] is not None:
                scrubbed_parent_url, _ = scrub_url(row["parent_url"])
                url_key = hashlib.sha256(scrubbed_parent_url.encode("utf-8")).hexdigest()
                hash_input = f"{profile}|{url_key}|{row['parent_visit_time']}"
                from_visit_key = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            yield {
                "kind": "visit",
                "profile": profile,
                "url": row["current_url"],
                "title": row["current_title"],
                "visit_time_us": row["visit_time"],
                "transition": row["transition"],
                "duration_us": row["visit_duration"] if row["visit_duration"] is not None else 0,
                "from_visit_key": from_visit_key,
            }

        # ------------------------------------------------------------------
        # SEARCHES
        # ------------------------------------------------------------------
        # keyword_search_terms has no timestamp; derive first_seen_us from visits.
        for row in conn.execute(
            "SELECT kst.url_id, kst.term, u.url "
            "FROM keyword_search_terms kst "
            "JOIN urls u ON kst.url_id = u.id"
        ):
            url_id = row[0]
            first_seen = min_visit_time.get(url_id)
            if first_seen is None:
                first_seen = last_visit_time.get(url_id, 0)

            yield {
                "kind": "search",
                "profile": profile,
                "url": row[2],
                "term": row[1],
                "first_seen_us": first_seen,
            }

        # ------------------------------------------------------------------
        # DOWNLOADS
        # ------------------------------------------------------------------
        # Emit all downloads; their identity keys make re-ingestion idempotent.
        for row in conn.execute(
            "SELECT guid, target_path, referrer, start_time, received_bytes, mime_type, state "
            "FROM downloads"
        ):
            yield {
                "kind": "download",
                "profile": profile,
                "guid": row[0],
                "target_path": row[1],
                "referrer": row[2],
                "start_time_us": row[3],
                "received_bytes": row[4],
                "mime_type": row[5],
                "state": row[6],
            }
