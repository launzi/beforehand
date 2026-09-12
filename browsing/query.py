"""
Query layer for the browsing-history pipeline.

Reads from a pre-populated SQLite database. Provides five public functions:
top_hosts, new_hosts, search_terms, timeline, stats.

All functions return plain dictionaries (not sqlite3.Row) and use
parameterised SQL. Restricted hosts (domains.sensitivity = 'restricted')
are excluded unless include_restricted=True. A host with no row in
domains is treated as category "unknown" and is NOT restricted.
"""

import datetime
import sqlite3
from typing import Any


def _chrome_us_to_utc(us: int) -> str:
    """Convert Chrome microseconds-since-1601 to UTC string 'YYYY-MM-DD HH:MM:SS.ffffff'."""
    # Chrome epoch: 1601-01-01 UTC
    base = datetime.datetime(1601, 1, 1)
    dt = base + datetime.timedelta(microseconds=us)
    # Format matches what the pipeline writes: space separator, microseconds padded to 6 digits
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _execute_dicts(conn: sqlite3.Connection, sql: str, params: tuple) -> list[dict]:
    """Execute SQL and return list of plain dicts."""
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _restricted_clause(include_restricted: bool) -> str:
    """
    Return a SQL fragment that excludes restricted hosts when include_restricted is False.
    The fragment assumes a left-joined `domains` table aliased as `d`.
    """
    if include_restricted:
        return ""
    # d.sensitivity IS NULL means no row in domains -> not restricted
    return " AND (d.sensitivity IS NULL OR d.sensitivity != 'restricted')"


def top_hosts(
    conn: sqlite3.Connection,
    *,
    since_us: int | None = None,
    until_us: int | None = None,
    profile: str | None = None,
    category: str | None = None,
    include_restricted: bool = False,
    limit: int = 50,
) -> list[dict]:
    """
    Most-visited hosts in the time window.

    Returns list of dicts: host, category, visits, last_seen_utc
    sorted by visits descending.
    """
    sql = """
        SELECT
            u.host,
            COALESCE(d.category, 'unknown') AS category,
            COUNT(*) AS visits,
            MAX(u.last_seen_utc) AS last_seen_utc
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE 1=1
    """
    params: list[Any] = []
    if since_us is not None:
        sql += " AND v.visit_time_us >= ?"
        params.append(since_us)
    if until_us is not None:
        sql += " AND v.visit_time_us < ?"
        params.append(until_us)
    if profile is not None:
        sql += " AND v.profile = ?"
        params.append(profile)
    if category is not None:
        sql += " AND COALESCE(d.category, 'unknown') = ?"
        params.append(category)
    sql += _restricted_clause(include_restricted)
    sql += """
        GROUP BY u.host, COALESCE(d.category, 'unknown')
        ORDER BY visits DESC
        LIMIT ?
    """
    params.append(limit)
    return _execute_dicts(conn, sql, tuple(params))


def new_hosts(
    conn: sqlite3.Connection,
    *,
    since_us: int,
    profile: str | None = None,
    include_restricted: bool = False,
    limit: int = 50,
) -> list[dict]:
    """
    Hosts whose first-seen URL appeared at or after `since_us`.

    Returns list of dicts: host, category, first_seen_utc, visits
    sorted by first_seen_utc descending (newest first).
    """
    since_utc = _chrome_us_to_utc(since_us)
    sql = """
        SELECT
            u.host,
            COALESCE(d.category, 'unknown') AS category,
            MIN(u.first_seen_utc) AS first_seen_utc,
            COUNT(v.visit_key) AS visits
        FROM urls u
        LEFT JOIN domains d ON u.host = d.host
        LEFT JOIN visits v ON v.url_key = u.url_key
    """
    params: list[Any] = []
    where = ["u.first_seen_utc >= ?"]
    params.append(since_utc)
    if profile is not None:
        where.append("v.profile = ?")
        params.append(profile)
    where.append(_restricted_clause(include_restricted).lstrip(" AND"))
    sql += " WHERE " + " AND ".join(where)
    sql += """
        GROUP BY u.host, COALESCE(d.category, 'unknown')
        ORDER BY first_seen_utc DESC
        LIMIT ?
    """
    params.append(limit)
    return _execute_dicts(conn, sql, tuple(params))


def search_terms(
    conn: sqlite3.Connection,
    *,
    grep: str | None = None,
    since_us: int | None = None,
    until_us: int | None = None,
    profile: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Search terms with optional substring filter and time window.

    Returns list of dicts: term, first_seen_utc, count
    sorted by first_seen_utc descending.
    """
    sql = """
        SELECT
            s.term,
            MIN(s.first_seen_utc) AS first_seen_utc,
            COUNT(*) AS count
        FROM searches s
        WHERE 1=1
    """
    params: list[Any] = []
    if grep is not None:
        sql += " AND s.term LIKE ?"
        params.append(f"%{grep}%")
    if since_us is not None:
        sql += " AND s.first_seen_utc >= ?"
        params.append(_chrome_us_to_utc(since_us))
    if until_us is not None:
        sql += " AND s.first_seen_utc < ?"
        params.append(_chrome_us_to_utc(until_us))
    if profile is not None:
        sql += " AND s.profile = ?"
        params.append(profile)
    sql += """
        GROUP BY s.term
        ORDER BY first_seen_utc DESC
        LIMIT ?
    """
    params.append(limit)
    return _execute_dicts(conn, sql, tuple(params))


def timeline(
    conn: sqlite3.Connection,
    host: str,
    *,
    since_us: int | None = None,
    until_us: int | None = None,
    profile: str | None = None,
    include_restricted: bool = False,
    limit: int = 200,
) -> list[dict]:
    """
    Chronological visits for a host and its subdomains.

    Returns list of dicts: visit_time_utc, url, title
    sorted by visit_time_utc ascending.
    """
    # Host matching: exact host OR subdomain (label-wise, so ".host" suffix)
    host_pattern = f"%.{host}"
    sql = """
        SELECT
            v.visit_time_utc,
            u.url,
            u.title
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE (u.host = ? OR u.host LIKE ?)
    """
    params: list[Any] = [host, host_pattern]
    if since_us is not None:
        sql += " AND v.visit_time_us >= ?"
        params.append(since_us)
    if until_us is not None:
        sql += " AND v.visit_time_us < ?"
        params.append(until_us)
    if profile is not None:
        sql += " AND v.profile = ?"
        params.append(profile)
    sql += _restricted_clause(include_restricted)
    sql += """
        ORDER BY v.visit_time_us ASC
        LIMIT ?
    """
    params.append(limit)
    return _execute_dicts(conn, sql, tuple(params))


def stats(
    conn: sqlite3.Connection,
    *,
    since_us: int | None = None,
    until_us: int | None = None,
    profile: str | None = None,
    include_restricted: bool = False,
) -> dict:
    """
    Aggregate counts and time bounds for the current filter.

    Returns dict with keys:
    visits, hosts, searches, downloads, first_utc, last_utc
    """
    # Base WHERE clause for visits (used for visits, hosts, first/last)
    visit_where = ["1=1"]
    visit_params: list[Any] = []
    if since_us is not None:
        visit_where.append("v.visit_time_us >= ?")
        visit_params.append(since_us)
    if until_us is not None:
        visit_where.append("v.visit_time_us < ?")
        visit_params.append(until_us)
    if profile is not None:
        visit_where.append("v.profile = ?")
        visit_params.append(profile)
    # Restricted exclusion for visits and hosts
    restricted_sql = _restricted_clause(include_restricted)
    if restricted_sql:
        visit_where.append(restricted_sql.lstrip(" AND"))

    where_sql = " AND ".join(visit_where)

    # Visits count
    visits_sql = f"SELECT COUNT(*) FROM visits v JOIN urls u ON v.url_key = u.url_key LEFT JOIN domains d ON u.host = d.host WHERE {where_sql}"
    visits = conn.execute(visits_sql, tuple(visit_params)).fetchone()[0]

    # Distinct hosts
    hosts_sql = f"SELECT COUNT(DISTINCT u.host) FROM visits v JOIN urls u ON v.url_key = u.url_key LEFT JOIN domains d ON u.host = d.host WHERE {where_sql}"
    hosts = conn.execute(hosts_sql, tuple(visit_params)).fetchone()[0]

    # First/last visit UTC
    fl_sql = f"SELECT MIN(v.visit_time_utc), MAX(v.visit_time_utc) FROM visits v JOIN urls u ON v.url_key = u.url_key LEFT JOIN domains d ON u.host = d.host WHERE {where_sql}"
    first_utc, last_utc = conn.execute(fl_sql, tuple(visit_params)).fetchone()

    # Searches count (filter by time on searches.first_seen_utc, profile, and restricted via url host)
    search_where = ["1=1"]
    search_params: list[Any] = []
    if since_us is not None:
        search_where.append("s.first_seen_utc >= ?")
        search_params.append(_chrome_us_to_utc(since_us))
    if until_us is not None:
        search_where.append("s.first_seen_utc < ?")
        search_params.append(_chrome_us_to_utc(until_us))
    if profile is not None:
        search_where.append("s.profile = ?")
        search_params.append(profile)
    # Restricted exclusion for searches
    if not include_restricted:
        search_where.append("(d.sensitivity IS NULL OR d.sensitivity != 'restricted')")
    search_sql = f"""
        SELECT COUNT(*)
        FROM searches s
        JOIN urls u ON s.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE {" AND ".join(search_where)}
    """
    searches = conn.execute(search_sql, tuple(search_params)).fetchone()[0]

    # Downloads count (filter by start_time_utc, profile, and restricted via referrer host)
    dl_where = ["1=1"]
    dl_params: list[Any] = []
    if since_us is not None:
        dl_where.append("dl.start_time_utc >= ?")
        dl_params.append(_chrome_us_to_utc(since_us))
    if until_us is not None:
        dl_where.append("dl.start_time_utc < ?")
        dl_params.append(_chrome_us_to_utc(until_us))
    if profile is not None:
        dl_where.append("dl.profile = ?")
        dl_params.append(profile)
    if not include_restricted:
        dl_where.append("(d.sensitivity IS NULL OR d.sensitivity != 'restricted')")
    dl_sql = f"""
        SELECT COUNT(*)
        FROM downloads dl
        LEFT JOIN urls u ON dl.referrer_url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE {" AND ".join(dl_where)}
    """
    downloads = conn.execute(dl_sql, tuple(dl_params)).fetchone()[0]

    return {
        "visits": visits,
        "hosts": hosts,
        "searches": searches,
        "downloads": downloads,
        "first_utc": first_utc,
        "last_utc": last_utc,
    }
