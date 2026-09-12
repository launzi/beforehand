"""
Host classification for browsing history pipeline.

Loads categorization rules from a base TOML file (public services) and an optional
local TOML file (private hosts). Provides efficient case-insensitive host lookup
with subdomain matching and most-specific-wins semantics.
"""

import tomllib
from pathlib import Path


def load_rules(base_path: Path, local_path: Path | None = None) -> dict:
    """
    Load and merge classification rules from base and optional local TOML files.

    Args:
        base_path: Path to the base rules file (required, tracked by git).
        local_path: Optional path to local rules file (git-ignored, may not exist).

    Returns:
        A dict mapping normalized host -> (category, sensitivity) for fast lookup.

    Raises:
        FileNotFoundError: If base_path does not exist.
        ValueError: If TOML is malformed or sensitivity value is invalid.
    """
    if not base_path.exists():
        raise FileNotFoundError(f"Base rules file not found: {base_path}")

    try:
        with open(base_path, "rb") as f:
            base_data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Failed to parse base TOML: {e}") from e

    base_map = _parse_rules(base_data, "base")

    local_map = {}
    if local_path is not None and local_path.exists():
        try:
            with open(local_path, "rb") as f:
                local_data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Failed to parse local TOML: {e}") from e
        local_map = _parse_rules(local_data, "local")

    # Local overrides base for duplicate hosts
    merged = {**base_map, **local_map}
    return merged


def _parse_rules(data: dict, source: str) -> dict:
    """Parse a TOML dict into a host->(category, sensitivity) mapping."""
    result = {}
    for category, config in data.items():
        if not isinstance(config, dict):
            raise ValueError(f"Category '{category}' in {source} is not a table")

        sensitivity = config.get("sensitivity", "none")
        if sensitivity not in ("none", "restricted"):
            raise ValueError(
                f"Invalid sensitivity '{sensitivity}' in category '{category}' ({source})"
            )

        hosts = config.get("hosts", [])
        if not isinstance(hosts, list):
            raise ValueError(f"Hosts in category '{category}' ({source}) is not a list")

        for host in hosts:
            if not isinstance(host, str):
                raise ValueError(f"Non-string host in category '{category}' ({source})")
            normalized = _normalize_host(host)
            if normalized:
                result[normalized] = (category, sensitivity)
    return result


def _normalize_host(host: str) -> str:
    """Lowercase, strip whitespace, remove port suffix."""
    host = host.strip().lower()
    if not host:
        return ""
    if ":" in host:
        host = host.split(":", 1)[0]
    return host


def classify_host(rules: dict, host: str | None) -> tuple[str, str]:
    """
    Classify a host into (category, sensitivity) using the loaded rules.

    Matching rules:
    - Case-insensitive, port stripped.
    - A rule host matches itself and any subdomain (label-by-label).
    - Most specific match wins (more labels).
    - No match or invalid input returns ("unknown", "none").

    Args:
        rules: The dict returned by load_rules().
        host: Hostname to classify (may be None, empty, or contain a port).

    Returns:
        (category, sensitivity) tuple.
    """
    if host is None:
        return ("unknown", "none")

    normalized = _normalize_host(host)
    if not normalized or normalized in (".", ".."):
        return ("unknown", "none")

    labels = normalized.split(".")
    # Check suffixes from most specific (full host) to least (TLD only)
    for i in range(len(labels)):
        suffix = ".".join(labels[i:])
        if suffix in rules:
            return rules[suffix]

    return ("unknown", "none")
