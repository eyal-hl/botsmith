"""Async HTTP data fetcher with caching and domain whitelist."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlparse

import httpx

from bot import config
from bot.core import cache

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


def _check_domain(url: str) -> bool:
    """Verify URL domain is on the whitelist."""
    parsed = urlparse(url)
    domain = parsed.hostname or ""
    return domain in config.DOMAIN_WHITELIST


def _cache_key(url: str, params: dict, headers: dict) -> str:
    """Generate a stable cache key for a request."""
    raw = f"{url}|{sorted(params.items())}|{sorted(headers.items())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _get_ttl(url: str) -> int:
    """Get cache TTL for a given URL based on its domain."""
    domain = urlparse(url).hostname or ""
    return config.CACHE_TTLS.get(domain, config.CACHE_TTLS["default"])


async def fetch(
    url: str,
    method: str = "GET",
    params: dict | None = None,
    headers: dict | None = None,
    body: dict | None = None,
    timeout: int = 15,
    use_cache: bool = True,
) -> dict | list | str:
    """Fetch data from a URL with caching and domain whitelist enforcement."""
    params = params or {}
    headers = headers or {}

    if not _check_domain(url):
        raise ValueError(
            f"Domain not in whitelist: {urlparse(url).hostname}. "
            f"Allowed: {', '.join(sorted(config.DOMAIN_WHITELIST))}"
        )

    # Inject football API key if needed
    if "api.football-data.org" in url and config.FOOTBALL_API_KEY:
        headers.setdefault("X-Auth-Token", config.FOOTBALL_API_KEY)

    # Check cache
    key = _cache_key(url, params, headers)
    if use_cache:
        cached = await cache.get(key)
        if cached is not None:
            logger.debug("Cache hit for %s", url)
            return cached

    # Fetch
    client = get_client()
    try:
        if method.upper() == "GET":
            response = await client.get(
                url, params=params, headers=headers, timeout=timeout
            )
        else:
            response = await client.post(
                url,
                params=params,
                headers=headers,
                json=body,
                timeout=timeout,
            )

        response.raise_for_status()

        # Parse response
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            data = response.json()
        else:
            data = response.text

        # Cache the result
        if use_cache:
            ttl = _get_ttl(url)
            await cache.set(key, data, ttl)

        return data

    except httpx.HTTPStatusError as e:
        logger.error("HTTP %d from %s: %s", e.response.status_code, url, e)
        raise
    except httpx.TimeoutException:
        logger.error("Timeout fetching %s", url)
        raise
    except Exception as e:
        logger.error("Error fetching %s: %s", url, e)
        raise


async def close() -> None:
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
