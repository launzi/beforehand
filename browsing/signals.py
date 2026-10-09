"""
Rule-based signal detection over a browsing-history database.

This module implements the original four deterministic detectors plus quote candidates that propose candidate signals
from raw browsing data. No language models are used; all logic is expressed in
parameterised SQL and Python rules. The same input always yields the same output.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

# ----------------------------------------------------------------------
# Constants & helpers
# ----------------------------------------------------------------------

# Chrome timestamps are microseconds since 1601-01-01 UTC.
_CHROME_EPOCH_DELTA_US = 11_644_473_600_000_000  # microseconds between 1601 and 1970

_ONBOARDING_PREFIXES = (
    "/signup",
    "/sign-up",
    "/register",
    "/login",
    "/auth",
    "/onboarding",
    "/welcome",
    "/users/register",
)

_FOLLOW_THROUGH_WINDOW_US = 30 * 60 * 1_000_000  # 30 minutes
_MIN_FOLLOW_THROUGH_VISITS = 3
_MIN_REPEAT_SEARCH_DAYS = 2


def _chrome_us_from_iso(iso_str: str) -> int:
    """Convert an ISO-8601 UTC string to Chrome microseconds."""
    # Python 3.11+ fromisoformat handles 'Z' and offsets.
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    unix_us = int(dt.timestamp() * 1_000_000)
    return unix_us + _CHROME_EPOCH_DELTA_US


def _kst_date_from_us(us: int) -> str:
    """Return YYYY-MM-DD in KST (UTC+9) for a Chrome-microsecond timestamp."""
    unix_us = us - _CHROME_EPOCH_DELTA_US
    dt_utc = datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc)
    dt_kst = dt_utc + timedelta(hours=9)
    return dt_kst.date().isoformat()


def _is_onboarding_path(path: str | None) -> bool:
    if not path:
        return False
    low = path.lower()
    return any(prefix in low for prefix in _ONBOARDING_PREFIXES)


def _make_key(kind: str, identifier: str) -> str:
    """Stable SHA-256 hexdigest for deduplication."""
    return hashlib.sha256(f"{kind}|{identifier}".encode()).hexdigest()


def _restricted_host_clause(include_restricted: bool) -> str:
    """SQL fragment for the restricted-host filter."""
    if include_restricted:
        return ""  # no restriction
    return "AND (d.sensitivity IS NULL OR d.sensitivity != 'restricted')"


# ----------------------------------------------------------------------
# Public dataclass
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    kind: str  # new_entry | unresolved | recurring | dropped | korea_product
    key: str  # stable content hash
    host: str | None
    term: str | None
    evidence: dict
    first_us: int
    last_us: int


# ----------------------------------------------------------------------
# Detectors
# ----------------------------------------------------------------------


def detect_new_entry(
    conn: sqlite3.Connection,
    *,
    since_us: int,
    until_us: int,
    profile: str | None = None,
    include_restricted: bool = False,
) -> list[Signal]:
    """Hosts whose first visit falls in the window and show an onboarding path."""
    sql = f"""
        SELECT u.host, v.visit_time_us, u.path
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
          {_restricted_host_clause(include_restricted)}
        ORDER BY u.host, v.visit_time_us
    """
    params = (since_us, until_us)
    if profile is not None:
        sql = sql.replace("WHERE v.visit_time_us", "WHERE v.profile = ? AND v.visit_time_us")
        params = (profile, since_us, until_us)

    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute(sql, params).fetchall()

    # Group by host
    by_host: dict[str, list[tuple[int, str | None]]] = {}
    for row in rows:
        by_host.setdefault(row["host"], []).append((row["visit_time_us"], row["path"]))

    signals: list[Signal] = []
    for host, visits in by_host.items():
        first_us = visits[0][0]
        if not (since_us <= first_us < until_us):
            continue  # earliest visit not in window
        onboarding_paths = sorted({p for _, p in visits if _is_onboarding_path(p)})
        if not onboarding_paths:
            continue
        last_us = visits[-1][0]
        evidence = {
            "onboarding_paths": onboarding_paths,
            "first_visit_us": first_us,
            "visit_count": len(visits),
        }
        signals.append(
            Signal(
                kind="new_entry",
                key=_make_key("new_entry", host),
                host=host,
                term=None,
                evidence=evidence,
                first_us=first_us,
                last_us=last_us,
            )
        )
    signals.sort(key=lambda s: (s.kind, s.key))
    return signals


def detect_unresolved(
    conn: sqlite3.Connection,
    *,
    since_us: int,
    until_us: int,
    profile: str | None = None,
    include_restricted: bool = False,
) -> list[Signal]:
    """Search terms with poor follow-through or repeated across days."""
    # Fetch searches in window
    sql_searches = """
        SELECT s.search_key, s.profile, s.url_key, s.term, s.normalized_term, s.first_seen_utc
        FROM searches s
        WHERE 1=1
    """
    params: list = []
    if profile is not None:
        sql_searches += " AND s.profile = ?"
        params.append(profile)
    # We'll filter by time in Python after converting first_seen_utc
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    search_rows = cur.execute(sql_searches, params).fetchall()

    # Convert and filter by window
    searches_in_window = []
    for row in search_rows:
        try:
            search_us = _chrome_us_from_iso(row["first_seen_utc"])
        except ValueError:
            continue
        if since_us <= search_us < until_us:
            searches_in_window.append((row, search_us))

    if not searches_in_window:
        return []

    # Get search hosts for follow-through exclusion
    search_url_keys = {row["url_key"] for row, _ in searches_in_window}
    host_by_url_key: dict[str, str] = {}
    if search_url_keys:
        placeholders = ",".join("?" * len(search_url_keys))
        sql_hosts = f"SELECT url_key, host FROM urls WHERE url_key IN ({placeholders})"
        for row in cur.execute(sql_hosts, tuple(search_url_keys)).fetchall():
            host_by_url_key[row["url_key"]] = row["host"]

    # Fetch all visits for relevant profiles in the extended window (for follow-through)
    profiles_involved = {row["profile"] for row, _ in searches_in_window}
    visit_start = since_us
    visit_end = until_us + _FOLLOW_THROUGH_WINDOW_US
    placeholders = ",".join("?" * len(profiles_involved))
    sql_visits = f"""
        SELECT v.visit_time_us, v.profile, u.host
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.profile IN ({placeholders})
          AND v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
          {_restricted_host_clause(include_restricted)}
    """
    visit_params = tuple(profiles_involved) + (visit_start, visit_end)
    visit_rows = cur.execute(sql_visits, visit_params).fetchall()

    # Index visits by profile for fast lookup
    visits_by_profile: dict[str, list[tuple[int, str]]] = {}
    for row in visit_rows:
        visits_by_profile.setdefault(row["profile"], []).append((row["visit_time_us"], row["host"]))

    # Analyse each search
    by_term: dict[str, dict] = {}
    for row, search_us in searches_in_window:
        norm = row["normalized_term"]
        term = row["term"]
        prof = row["profile"]
        search_host = host_by_url_key.get(row["url_key"])

        # Follow-through visits: same profile, within 30 min, different host
        follow = 0
        for v_us, v_host in visits_by_profile.get(prof, []):
            if search_us < v_us <= search_us + _FOLLOW_THROUGH_WINDOW_US:
                if v_host != search_host:
                    follow += 1

        # Distinct search days (KST date of first_seen_utc)
        try:
            dt = datetime.fromisoformat(row["first_seen_utc"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_kst = dt.astimezone(timezone(timedelta(hours=9)))
            day = dt_kst.date().isoformat()
        except ValueError:
            day = None

        entry = by_term.setdefault(
            norm,
            {
                "term": term,
                "searches": 0,
                "follow_through_counts": [],
                "days": set(),
            },
        )
        entry["searches"] += 1
        entry["follow_through_counts"].append(follow)
        if day:
            entry["days"].add(day)

    signals: list[Signal] = []
    for norm, data in by_term.items():
        low_follow = any(c < _MIN_FOLLOW_THROUGH_VISITS for c in data["follow_through_counts"])
        repeat_days = len(data["days"]) >= _MIN_REPEAT_SEARCH_DAYS
        if not (low_follow or repeat_days):
            continue

        # For first_us/last_us use the first/last search in window for this term
        term_searches = [(row, us) for row, us in searches_in_window if row["normalized_term"] == norm]
        term_searches.sort(key=lambda x: x[1])
        first_us = term_searches[0][1]
        last_us = term_searches[-1][1]

        evidence = {
            "term": data["term"],
            "search_count": data["searches"],
            "follow_through_counts": data["follow_through_counts"],
            "distinct_days": len(data["days"]),
            "low_follow_through": low_follow,
            "repeat_across_days": repeat_days,
        }
        signals.append(
            Signal(
                kind="unresolved",
                key=_make_key("unresolved", norm),
                host=None,
                term=norm,
                evidence=evidence,
                first_us=first_us,
                last_us=last_us,
            )
        )
    signals.sort(key=lambda s: (s.kind, s.key))
    return signals


def detect_recurring(
    conn: sqlite3.Connection,
    *,
    since_us: int,
    until_us: int,
    profile: str | None = None,
    include_restricted: bool = False,
    min_days: int = 3,
) -> list[Signal]:
    """Hosts visited on at least min_days distinct calendar days in the window."""
    sql = f"""
        SELECT u.host, v.visit_time_us
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
          {_restricted_host_clause(include_restricted)}
    """
    params = (since_us, until_us)
    if profile is not None:
        sql = sql.replace("WHERE v.visit_time_us", "WHERE v.profile = ? AND v.visit_time_us")
        params = (profile, since_us, until_us)

    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute(sql, params).fetchall()

    by_host: dict[str, set[str]] = {}
    first_last: dict[str, tuple[int, int]] = {}
    for row in rows:
        host = row["host"]
        us = row["visit_time_us"]
        day = _kst_date_from_us(us)
        if host not in by_host:
            by_host[host] = set()
        by_host[host].add(day)
        if host not in first_last:
            first_last[host] = (us, us)
        else:
            f, l = first_last[host]
            first_last[host] = (min(f, us), max(l, us))

    signals: list[Signal] = []
    for host, days in by_host.items():
        if len(days) < min_days:
            continue
        first_us, last_us = first_last[host]
        evidence = {
            "distinct_days": len(days),
            "total_visits": sum(1 for row in rows if row["host"] == host),
            "first_day": min(days),
            "last_day": max(days),
        }
        signals.append(
            Signal(
                kind="recurring",
                key=_make_key("recurring", host),
                host=host,
                term=None,
                evidence=evidence,
                first_us=first_us,
                last_us=last_us,
            )
        )
    signals.sort(key=lambda s: (s.kind, s.key))
    return signals


def detect_dropped(
    conn: sqlite3.Connection,
    *,
    now_us: int,
    quiet_days: int = 7,
    min_active_days: int = 3,
    profile: str | None = None,
    include_restricted: bool = False,
) -> list[Signal]:
    """Hosts with ≥ min_active_days distinct active days but zero visits in last quiet_days."""
    quiet_start_us = now_us - quiet_days * 24 * 3600 * 1_000_000

    sql = f"""
        SELECT u.host, v.visit_time_us
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
          {_restricted_host_clause(include_restricted)}
    """
    params = (now_us,)
    if profile is not None:
        sql = sql.replace("WHERE v.visit_time_us", "WHERE v.profile = ? AND v.visit_time_us")
        params = (profile, now_us)

    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    rows = cur.execute(sql, params).fetchall()

    by_host: dict[str, set[str]] = {}
    last_visit: dict[str, int] = {}
    first_visit: dict[str, int] = {}
    for row in rows:
        host = row["host"]
        us = row["visit_time_us"]
        day = _kst_date_from_us(us)
        if host not in by_host:
            by_host[host] = set()
        by_host[host].add(day)
        if host not in last_visit or us > last_visit[host]:
            last_visit[host] = us
        if host not in first_visit or us < first_visit[host]:
            first_visit[host] = us

    signals: list[Signal] = []
    for host, days in by_host.items():
        if len(days) < min_active_days:
            continue
        last_us = last_visit[host]
        if last_us >= quiet_start_us:
            continue  # visited during quiet period
        days_quiet = (now_us - last_us) // (24 * 3600 * 1_000_000)
        evidence = {
            "active_days": len(days),
            "last_visit_us": last_us,
            "days_quiet": days_quiet,
        }
        signals.append(
            Signal(
                kind="dropped",
                key=_make_key("dropped", host),
                host=host,
                term=None,
                evidence=evidence,
                first_us=first_visit[host],
                last_us=last_us,
            )
        )
    signals.sort(key=lambda s: (s.kind, s.key))
    return signals


def detect_korea_product(conn, *, since_us, until_us, profile=None, include_restricted=False):
    """Repeated product visits with no later transaction page observed on that host.

    This is a quote candidate, never proof the visitor could not buy.
    """
    from browsing.web.korea_quote import korea_product_title
    import re
    sql = f"""SELECT u.url_key, u.host, u.path, u.title, v.visit_time_us
        FROM visits v JOIN urls u ON v.url_key=u.url_key
        LEFT JOIN domains d ON u.host=d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
        {_restricted_host_clause(include_restricted)}
    """
    params = [since_us, until_us]
    if profile is not None:
        sql += " AND v.profile = ?"
        params.append(profile)
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    rows = cursor.execute(sql, params).fetchall()
    groups = {}
    for row in rows:
        product = korea_product_title(row["host"], row["path"], row["title"])
        if product:
            groups.setdefault((row["host"], row["url_key"], product), []).append(row["visit_time_us"])
    result = []
    for (host, key, product), times in groups.items():
        if len(times) < 2:
            continue
        if any(r["host"] == host and r["visit_time_us"] >= min(times)
               and re.search(r"/(?:checkout|orders?|payment|purchase)(?:/|$|[.?])", r["path"] or "", re.I) for r in rows):
            continue
        result.append(Signal("korea_product", _make_key("korea_product", key), host, product,
                             {"product": product, "visit_count": len(times),
                              # Chrome's epoch is UTC midnight; integer day buckets stay exact.
                              "distinct_days": len({t // 86_400_000_000 for t in times}),
                              "purchase_page_observed": False},
                             min(times), max(times)))
    return sorted(result, key=lambda s: (s.kind, s.key))


def detect_all(
    conn: sqlite3.Connection,
    *,
    since_us: int,
    until_us: int,
    now_us: int,
    profile: str | None = None,
    include_restricted: bool = False,
) -> list[Signal]:
    """Run the original four detectors plus Korea quote candidates; return a sorted list."""
    all_signals: list[Signal] = []
    all_signals.extend(
        detect_new_entry(
            conn,
            since_us=since_us,
            until_us=until_us,
            profile=profile,
            include_restricted=include_restricted,
        )
    )
    all_signals.extend(
        detect_unresolved(
            conn,
            since_us=since_us,
            until_us=until_us,
            profile=profile,
            include_restricted=include_restricted,
        )
    )
    all_signals.extend(
        detect_recurring(
            conn,
            since_us=since_us,
            until_us=until_us,
            profile=profile,
            include_restricted=include_restricted,
        )
    )
    all_signals.extend(
        detect_dropped(
            conn,
            now_us=now_us,
            profile=profile,
            include_restricted=include_restricted,
        )
    )
    all_signals.extend(detect_korea_product(conn, since_us=since_us, until_us=until_us,
        profile=profile, include_restricted=include_restricted))
    all_signals.sort(key=lambda s: (s.kind, s.key))
    return all_signals


# SPEC_FEEDBACK: none
