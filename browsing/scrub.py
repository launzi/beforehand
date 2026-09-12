"""
URL scrubber for browsing-history pipeline.
Removes credential-like query parameters while keeping the URL readable
and keeping search terms intact.
"""

from urllib.parse import urlparse, urlunparse, parse_qsl, quote
import re


def scrub_url(url: str) -> tuple[str, str]:
    """Return (scrubbed_url, status) where status is "ok" or "failed"."""
    # Coerce non-str input to str
    url_str = str(url)

    # Parse URL — catch narrowly around the parsing step only
    try:
        parsed = urlparse(url_str)
    except ValueError:
        # Parsing failed: remove query string from original URL and return failed
        q_idx = url_str.find('?')
        if q_idx == -1:
            return (url_str, "failed")
        # Preserve fragment if present
        frag_idx = url_str.find('#', q_idx)
        if frag_idx != -1:
            return (url_str[:q_idx] + url_str[frag_idx:], "failed")
        return (url_str[:q_idx], "failed")

    # No query string: not a failure, return unchanged
    if not parsed.query:
        return (url_str, "ok")

    # Whitelist (exact match)
    whitelist = {"q", "query", "search_query", "keyword", "s", "wd", "page", "tab"}

    # Blacklist (substring, case-insensitive)
    blacklist = {
        "code", "state", "token", "access_token", "id_token", "refresh_token",
        "auth", "session", "secret", "password", "passwd", "pwd", "key",
        "apikey", "api_key", "sig", "signature", "credential", "assertion",
        "nonce", "_hsenc", "_hsmi"
    }

    # Parse query string preserving parameter order
    params = parse_qsl(parsed.query, keep_blank_values=True)

    # Process each parameter independently per the evaluation order
    scrubbed_params = []
    for name, value in params:
        # Rule 1: whitelist exact match or starts with "utm_"
        if name in whitelist or name.startswith("utm_"):
            scrubbed_params.append((name, value))
            continue

        # Rule 2: blacklist substring (case-insensitive)
        name_lower = name.lower()
        if any(bl in name_lower for bl in blacklist):
            masked = f"<redacted:{len(value)}>"
            scrubbed_params.append((name, masked))
            continue

        # Rule 3: value length >= 40 and only [A-Za-z0-9+/=_-]
        if len(value) >= 40 and re.fullmatch(r'[A-Za-z0-9+/=_-]+', value):
            masked = f"<redacted:{len(value)}>"
            scrubbed_params.append((name, masked))
            continue

        # Rule 4: keep the parameter
        scrubbed_params.append((name, value))

    # Rebuild query string: percent-encode names and normal values,
    # but insert masked values literally (no encoding of < > :)
    query_parts = []
    for name, value in scrubbed_params:
        enc_name = quote(name, safe='')
        if value.startswith("<redacted:") and value.endswith(">"):
            # Masked value — insert literally
            query_parts.append(f"{enc_name}={value}")
        else:
            enc_value = quote(value, safe='')
            query_parts.append(f"{enc_name}={enc_value}")

    new_query = "&".join(query_parts)

    # Reconstruct full URL preserving scheme, netloc, path, params, fragment
    scrubbed = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))

    return (scrubbed, "ok")
