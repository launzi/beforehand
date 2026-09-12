"""
Pluggable search and LLM provider registry.

Default search: tavily (requires TAVILY_API_KEY)
Default LLM:    nebius (requires NEBIUS_API_KEY)

All network calls and credential lookups are isolated in *_raw_* and *_resolve_key*
methods so tests can monkeypatch them without touching the network.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Any

# ----------------------------------------------------------------------
# Public exception
# ----------------------------------------------------------------------
class ProviderError(Exception):
    """Raised for configuration errors, bad arguments, and provider failures."""
    pass


# ----------------------------------------------------------------------
# Search providers
# ----------------------------------------------------------------------
class _SearchProvider:
    """Base class — not meant to be instantiated directly."""
    name: str

    def _resolve_key(self) -> str | None:
        raise NotImplementedError

    def _raw_search(self, query: str, limit: int) -> dict:
        raise NotImplementedError

    def search(self, query: str, limit: int = 5) -> list[dict]:
        # Validate before any network activity
        if not query or not query.strip():
            raise ProviderError("search query must not be blank")

        key = self._resolve_key()
        if not key:
            raise ProviderError(f"missing API key for {self.name}")

        raw = self._raw_search(query.strip(), limit)
        return self._normalise(raw)

    def _normalise(self, raw: dict) -> list[dict]:
        raise NotImplementedError


class _TavilySearch(_SearchProvider):
    name = "tavily"
    _ENDPOINT = "https://api.tavily.com/search"

    def _resolve_key(self) -> str | None:
        return os.getenv("TAVILY_API_KEY")

    def _raw_search(self, query: str, limit: int) -> dict:
        payload = json.dumps({"query": query, "max_results": limit}).encode()
        req = urllib.request.Request(
            self._ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._resolve_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise ProviderError(f"tavily HTTP {e.code}") from e

    def _normalise(self, raw: dict) -> list[dict]:
        results = raw.get("results", [])
        out = []
        for r in results:
            title = r.get("title") or ""
            url = r.get("url") or ""
            snippet = r.get("content") or ""
            out.append({"title": title, "url": url, "snippet": snippet})
        return out


class _SerperSearch(_SearchProvider):
    name = "serper"
    _ENDPOINT = "https://google.serper.dev/search"

    def _resolve_key(self) -> str | None:
        return os.getenv("SERPER_API_KEY")

    def _raw_search(self, query: str, limit: int) -> dict:
        payload = json.dumps({"q": query, "num": limit}).encode()
        req = urllib.request.Request(
            self._ENDPOINT,
            data=payload,
            headers={
                "X-API-KEY": self._resolve_key(),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise ProviderError(f"serper HTTP {e.code}") from e

    def _normalise(self, raw: dict) -> list[dict]:
        organic = raw.get("organic", [])
        out = []
        for r in organic:
            title = r.get("title") or ""
            url = r.get("link") or ""
            snippet = r.get("snippet") or ""
            out.append({"title": title, "url": url, "snippet": snippet})
        return out


# ----------------------------------------------------------------------
# LLM provider (Nebius)
# ----------------------------------------------------------------------
class _NebiusLLM:
    name = "nebius"
    _CHAT_ENDPOINT = "https://api.tokenfactory.nebius.com/v1/chat/completions"
    _MODELS_ENDPOINT = "https://api.tokenfactory.nebius.com/v1/models"

    # Valid tiers that map to Nemotron model variants
    _VALID_TIERS = ("nano", "super", "lightning", "ultra")

    # Process-wide cache for model list
    _models_cache: list[dict] | None = None

    def _resolve_key(self) -> str | None:
        return os.getenv("NEBIUS_API_KEY")

    def _raw_models(self) -> list[dict]:
        """Fetch model list once per process; tests monkeypatch this."""
        if self._models_cache is not None:
            return self._models_cache

        req = urllib.request.Request(
            self._MODELS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._resolve_key()}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            raise ProviderError(f"nebius models HTTP {e.code}") from e

        models = data.get("data", []) if isinstance(data, dict) else data
        if not isinstance(models, list):
            models = []
        self._models_cache = models
        return models

    def _resolve_model_id(self, tier: str) -> str:
        """Pick the shortest model id containing both 'nemotron' and the tier word."""
        if tier not in self._VALID_TIERS:
            raise ProviderError(f"unknown tier '{tier}'; valid: {self._VALID_TIERS}")

        models = self._raw_models()
        candidates = []
        for m in models:
            mid = m.get("id", "") if isinstance(m, dict) else ""
            if "nemotron" in mid.lower() and tier in mid.lower():
                candidates.append(mid)

        if not candidates:
            raise ProviderError(f"no model found for tier '{tier}'")

        # Shortest id wins (e.g. "nvidia/nemotron-3-nano" over "nvidia/nemotron-3-nano-latest")
        return min(candidates, key=len)

    def _raw_complete(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
    ) -> dict:
        """Perform the chat completion call. Tests monkeypatch this."""
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            self._CHAT_ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._resolve_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise ProviderError(f"nebius HTTP {e.code}") from e

    def complete(
        self,
        prompt: str,
        *,
        tier: str = "nano",
        system: str | None = None,
        max_tokens: int = 2000,
    ) -> str:
        # 1. Validate arguments
        if not prompt or not prompt.strip():
            raise ProviderError("prompt must not be blank")

        # 2. Resolve key BEFORE any network call (including model lookup)
        key = self._resolve_key()
        if not key:
            raise ProviderError("missing NEBIUS_API_KEY")

        # 3. Resolve tier -> model id (may call _raw_models)
        model_id = self._resolve_model_id(tier)

        # 4. Build messages with optional /no_think suppression
        messages: list[dict] = []
        if tier in ("nano", "super", "lightning"):
            # Prepend system message with /no_think to suppress reasoning
            no_think_msg = "/no_think"
            if system:
                no_think_msg = f"{system}\n\n{no_think_msg}"
            messages.append({"role": "system", "content": no_think_msg})
        elif system:
            messages.append({"role": "system", "content": system})

        messages.append({"role": "user", "content": prompt.strip()})

        # 5. Perform the request
        raw = self._raw_complete(model=model_id, messages=messages, max_tokens=max_tokens)

        # 6. Extract answer and handle Nemotron "length" finish_reason
        try:
            choice = raw["choices"][0]
            finish_reason = choice.get("finish_reason")
            message = choice["message"]
            content = message.get("content", "")
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("malformed nebius response") from e

        if finish_reason == "length" and not content.strip():
            raise ProviderError(f"nemotron finish_reason=length (tier={tier}, model={model_id})")

        return content


# ----------------------------------------------------------------------
# Registry & factory functions
# ----------------------------------------------------------------------
_SEARCH_REGISTRY: dict[str, _SearchProvider] = {
    "tavily": _TavilySearch(),
    "serper": _SerperSearch(),
}

_LLM_REGISTRY: dict[str, _NebiusLLM] = {
    "nebius": _NebiusLLM(),
}

_DEFAULT_SEARCH = "tavily"
_DEFAULT_LLM = "nebius"


def get_search(name: str | None = None) -> _SearchProvider:
    """Return a search provider instance. Default is 'tavily'."""
    key = name or _DEFAULT_SEARCH
    try:
        return _SEARCH_REGISTRY[key]
    except KeyError:
        raise ProviderError(
            f"unknown search provider '{key}'; available: {list(_SEARCH_REGISTRY)}"
        ) from None


def get_llm(name: str | None = None) -> _NebiusLLM:
    """Return an LLM provider instance. Default is 'nebius'."""
    key = name or _DEFAULT_LLM
    try:
        return _LLM_REGISTRY[key]
    except KeyError:
        raise ProviderError(
            f"unknown LLM provider '{key}'; available: {list(_LLM_REGISTRY)}"
        ) from None


def list_search() -> list[str]:
    """Return the list of registered search provider names."""
    return list(_SEARCH_REGISTRY)


def list_llm() -> list[str]:
    """Return the list of registered LLM provider names."""
    return list(_LLM_REGISTRY)
