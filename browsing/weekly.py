"""
Weekly digest layer for browsing-history pipeline.

Reads the database and produces a human-readable markdown report.
Never writes to the database.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def build_digest(
    conn: sqlite3.Connection,
    *,
    start_us: int,
    end_us: int,
    profile: str | None = None,
    include_restricted: bool = False,
    now_utc: str | None = None,
    top_limit: int = 25,
) -> dict[str, Any]:
    """
    Build a digest dictionary for the given time window.

    Args:
        conn: SQLite connection (read-only).
        start_us: Window start (inclusive), Chrome microseconds since epoch.
        end_us: Window end (exclusive), Chrome microseconds since epoch.
        profile: Optional profile filter.
        include_restricted: If False, exclude hosts with domains.sensitivity='restricted'.
        now_utc: ISO timestamp for "now" (default: current UTC time).
        top_limit: Maximum entries for capped lists.

    Returns:
        Plain dict with all digest sections.
    """
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row

    # Helper: build profile clause and params
    profile_clause = "AND v.profile = ?" if profile else ""
    profile_params = (profile,) if profile else ()

    # Restriction subquery (works with any alias for urls table)
    restricted_subq = "u.host NOT IN (SELECT host FROM domains WHERE sensitivity = 'restricted')"
    restrict_clause = "" if include_restricted else f"AND {restricted_subq}"

    # Convert Chrome microseconds to UTC ISO strings for window info.
    # ⚠ Chrome counts from 1601-01-01, not the Unix epoch. Dropping the 11644473600s
    #   offset yields year 2394 and every timestamp comparison silently matches nothing.
    #   Reuse the ingest layer's converter so the two can never drift apart.
    from browsing.ingest import chrome_us_to_utc as us_to_utc

    window_start_utc = us_to_utc(start_us)
    window_end_utc = us_to_utc(end_us)

    # ---------- TOTALS ----------
    # Current window visits.
    # host 가 NULL/빈 값인 행도 센다 — 이름을 못 붙일 뿐 방문은 일어났다.
    # 다만 restricted 로 분류된 호스트는 총계에서도 뺀다. 리포트는 파일로 남고
    # 공유되기 쉬우므로, 숫자만으로도 그 주의 금융·구직 활동량이 드러나면 안 된다.
    sql_visits = f"""
        SELECT COUNT(*)
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
        {profile_clause}
        {restrict_clause}
    """
    visits = cur.execute(sql_visits, (start_us, end_us) + profile_params).fetchone()[0]

    # Previous window (same length, immediately before)
    window_len = end_us - start_us
    prev_start = start_us - window_len
    prev_end = start_us
    sql_prev = f"""
        SELECT COUNT(*)
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
        {profile_clause}
    """
    prev_visits = cur.execute(sql_prev, (prev_start, prev_end) + profile_params).fetchone()[0]
    delta_visits = visits - prev_visits

    # Distinct hosts in current window (non-NULL, non-empty, respecting restriction)
    sql_hosts = f"""
        SELECT COUNT(DISTINCT u.host)
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
        {profile_clause}
        {restrict_clause}
    """
    hosts = cur.execute(sql_hosts, (start_us, end_us) + profile_params).fetchone()[0]

    # Searches in window
    sql_searches = f"""
        SELECT COUNT(*)
        FROM searches s
        JOIN urls u ON s.url_key = u.url_key
        WHERE s.first_seen_utc >= ? AND s.first_seen_utc < ?
        {profile_clause.replace('v.profile', 's.profile')}
        {restrict_clause}
    """
    searches = cur.execute(sql_searches, (window_start_utc, window_end_utc) + profile_params).fetchone()[0]

    # Downloads in window
    sql_downloads = f"""
        SELECT COUNT(*)
        FROM downloads d
        JOIN urls u ON d.referrer_url_key = u.url_key
        WHERE d.start_time_utc >= ? AND d.start_time_utc < ?
        {profile_clause.replace('v.profile', 'd.profile')}
        {restrict_clause}
    """
    downloads = cur.execute(sql_downloads, (window_start_utc, window_end_utc) + profile_params).fetchone()[0]

    # ---------- TOP HOSTS ----------
    sql_top = f"""
        SELECT u.host, d.category, COUNT(*) AS visits
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
        {profile_clause}
        {restrict_clause}
        GROUP BY u.host, d.category
        ORDER BY visits DESC
        LIMIT ?
    """
    top_rows = cur.execute(sql_top, (start_us, end_us) + profile_params + (top_limit,)).fetchall()
    top_hosts = [{"host": r["host"], "category": r["category"] or "uncategorized", "visits": r["visits"]} for r in top_rows]

    # ---------- NEW HOSTS ----------
    # Hosts whose FIRST EVER visit (across all time) falls in this window
    sql_new = f"""
        SELECT u.host, d.category, MIN(v.visit_time_utc) AS first_seen_utc, COUNT(*) AS visits
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
        {profile_clause}
        {restrict_clause}
        GROUP BY u.host, d.category
        HAVING MIN(v.visit_time_us) = (
            SELECT MIN(v2.visit_time_us)
            FROM visits v2
            JOIN urls u2 ON v2.url_key = u2.url_key
            WHERE u2.host = u.host
        )
        ORDER BY first_seen_utc
    """
    new_rows = cur.execute(sql_new, (start_us, end_us) + profile_params).fetchall()
    new_hosts = [
        {"host": r["host"], "category": r["category"] or "uncategorized", "first_seen_utc": r["first_seen_utc"], "visits": r["visits"]}
        for r in new_rows
    ]

    # ---------- DROPPED HOSTS ----------
    # Hosts visited in previous window but not in current window
    sql_dropped = f"""
        SELECT u.host, d.category, COUNT(*) AS prev_visits
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
        {profile_clause}
        {restrict_clause}
        AND u.host NOT IN (
            SELECT u2.host
            FROM visits v2
            JOIN urls u2 ON v2.url_key = u2.url_key
            WHERE v2.visit_time_us >= ? AND v2.visit_time_us < ?
              AND u2.host IS NOT NULL AND u2.host != ''
            {profile_clause}
            {restrict_clause}
        )
        GROUP BY u.host, d.category
        ORDER BY prev_visits DESC
    """
    dropped_rows = cur.execute(
        sql_dropped,
        (prev_start, prev_end) + profile_params + (start_us, end_us) + profile_params
    ).fetchall()
    dropped_hosts = [
        {"host": r["host"], "category": r["category"] or "uncategorized", "prev_visits": r["prev_visits"]}
        for r in dropped_rows
    ]

    # ---------- UNKNOWN HOSTS ----------
    # Hosts with no domains row, most-visited first
    sql_unknown = f"""
        SELECT u.host, COUNT(*) AS visits
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
          AND d.host IS NULL
        {profile_clause}
        {restrict_clause}
        GROUP BY u.host
        ORDER BY visits DESC
        LIMIT ?
    """
    unknown_rows = cur.execute(sql_unknown, (start_us, end_us) + profile_params + (top_limit,)).fetchall()
    unknown_hosts = [{"host": r["host"], "visits": r["visits"]} for r in unknown_rows]

    # ---------- CATEGORIES ----------
    sql_cat = f"""
        SELECT d.category, COUNT(*) AS visits
        FROM visits v
        JOIN urls u ON v.url_key = u.url_key
        LEFT JOIN domains d ON u.host = d.host
        WHERE v.visit_time_us >= ? AND v.visit_time_us < ?
          AND u.host IS NOT NULL AND u.host != ''
        {profile_clause}
        {restrict_clause}
        GROUP BY d.category
        ORDER BY visits DESC
    """
    cat_rows = cur.execute(sql_cat, (start_us, end_us) + profile_params).fetchall()
    categories = {r["category"] or "uncategorized": r["visits"] for r in cat_rows}

    # ---------- SEARCHES ----------
    sql_search_list = f"""
        SELECT s.term, s.first_seen_utc
        FROM searches s
        JOIN urls u ON s.url_key = u.url_key
        WHERE s.first_seen_utc >= ? AND s.first_seen_utc < ?
        {profile_clause.replace('v.profile', 's.profile')}
        {restrict_clause}
        ORDER BY s.first_seen_utc
    """
    search_rows = cur.execute(sql_search_list, (window_start_utc, window_end_utc) + profile_params).fetchall()
    searches_list = [{"term": r["term"], "first_seen_utc": r["first_seen_utc"]} for r in search_rows]

    # ---------- DOWNLOADS ----------
    sql_dl_list = f"""
        SELECT d.target_path, d.start_time_utc, d.mime_type
        FROM downloads d
        JOIN urls u ON d.referrer_url_key = u.url_key
        WHERE d.start_time_utc >= ? AND d.start_time_utc < ?
        {profile_clause.replace('v.profile', 'd.profile')}
        {restrict_clause}
        ORDER BY d.start_time_utc
    """
    dl_rows = cur.execute(sql_dl_list, (window_start_utc, window_end_utc) + profile_params).fetchall()
    downloads_list = [
        {"target_path": r["target_path"], "start_time_utc": r["start_time_utc"], "mime_type": r["mime_type"]}
        for r in dl_rows
    ]

    # ---------- HEALTH ----------
    sql_sync = "SELECT profile, last_run_utc FROM sync_state"
    if profile:
        sql_sync += " WHERE profile = ?"
        sync_rows = cur.execute(sql_sync, (profile,)).fetchall()
    else:
        sync_rows = cur.execute(sql_sync).fetchall()

    now_dt = datetime.fromisoformat(now_utc) if now_utc else datetime.now(timezone.utc)
    profiles_health = []
    stale = False
    for r in sync_rows:
        last_run = datetime.fromisoformat(r["last_run_utc"])
        days_since = (now_dt - last_run).days
        profiles_health.append({"profile": r["profile"], "last_run_utc": r["last_run_utc"], "days_since": days_since})
        if days_since > 3:
            stale = True

    # If no profiles in sync_state, not stale
    if not sync_rows:
        stale = False

    return {
        "totals": {
            "visits": visits,
            "hosts": hosts,
            "searches": searches,
            "downloads": downloads,
            "prev_visits": prev_visits,
            "delta_visits": delta_visits,
            "top_hosts_omitted": max(0, hosts - len(top_hosts)),
        },
        "top_hosts": top_hosts,
        "new_hosts": new_hosts,
        "dropped_hosts": dropped_hosts,
        "unknown_hosts": unknown_hosts,
        "categories": categories,
        "searches": searches_list,
        "downloads": downloads_list,
        "window": {
            "start_us": start_us,
            "end_us": end_us,
            "start_utc": window_start_utc,
            "end_utc": window_end_utc,
        },
        "health": {
            "profiles": profiles_health,
            "stale": stale,
        },
    }


def render_markdown(digest: dict[str, Any]) -> str:
    """
    Render a digest dictionary as human-readable markdown.

    Args:
        digest: Dictionary returned by build_digest().

    Returns:
        Markdown string starting with a single "# " title line.
    """
    lines = []
    t = digest["totals"]
    w = digest["window"]

    # Title
    lines.append(f"# Weekly Digest: {w['start_utc'][:10]} to {w['end_utc'][:10]}")
    lines.append("")

    # Window info
    lines.append(f"**Window:** {w['start_utc']} → {w['end_utc']}  ")
    lines.append(f"**Profiles:** {', '.join(p['profile'] for p in digest['health']['profiles']) or 'none'}")
    lines.append("")

    # Totals with delta
    lines.append("## Totals")
    lines.append(f"- Visits: **{t['visits']:,}** (prev {t['prev_visits']:,}, Δ {t['delta_visits']:+,})")
    lines.append(f"- Distinct hosts: **{t['hosts']:,}**")
    lines.append(f"- Searches: **{t['searches']:,}**")
    lines.append(f"- Downloads: **{t['downloads']:,}**")
    if t["top_hosts_omitted"]:
        lines.append(f"- *Top hosts list omits {t['top_hosts_omitted']:,} additional hosts*")
    lines.append("")

    # Categories
    if digest["categories"]:
        lines.append("## Categories")
        for cat, count in digest["categories"].items():
            lines.append(f"- {cat}: {count:,}")
        lines.append("")

    # Top hosts
    if digest["top_hosts"]:
        lines.append("## Top Hosts")
        for i, h in enumerate(digest["top_hosts"], 1):
            lines.append(f"{i}. {h['host']} ({h['category']}) — {h['visits']:,} visits")
        lines.append("")

    # New hosts
    if digest["new_hosts"]:
        lines.append("## New Hosts (first visit this week)")
        for h in digest["new_hosts"]:
            lines.append(f"- {h['host']} ({h['category']}) — first seen {h['first_seen_utc']}, {h['visits']:,} visits")
        lines.append("")

    # Dropped hosts
    if digest["dropped_hosts"]:
        lines.append("## Dropped Hosts (visited last week, not this week)")
        for h in digest["dropped_hosts"]:
            lines.append(f"- {h['host']} ({h['category']}) — {h['prev_visits']:,} visits last week")
        lines.append("")

    # Unknown hosts
    if digest["unknown_hosts"]:
        lines.append("## Unknown Hosts (no category assigned)")
        for h in digest["unknown_hosts"]:
            lines.append(f"- {h['host']} — {h['visits']:,} visits")
        lines.append("")

    # Searches
    if digest["searches"]:
        lines.append("## Searches")
        for s in digest["searches"]:
            lines.append(f"- {s['term']} — {s['first_seen_utc']}")
        lines.append("")

    # Downloads
    if digest["downloads"]:
        lines.append("## Downloads")
        for d in digest["downloads"]:
            mime = f" ({d['mime_type']})" if d["mime_type"] else ""
            lines.append(f"- {d['target_path']} — {d['start_time_utc']}{mime}")
        lines.append("")

    # Health
    lines.append("## Sync Health")
    h = digest["health"]
    if h["profiles"]:
        for p in h["profiles"]:
            status = " ⚠ STALE" if p["days_since"] > 3 else ""
            lines.append(f"- {p['profile']}: last run {p['last_run_utc']} ({p['days_since']} days ago){status}")
    else:
        lines.append("- No profiles recorded yet")
    lines.append(f"\n**Overall stale: {'YES' if h['stale'] else 'NO'}**")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
