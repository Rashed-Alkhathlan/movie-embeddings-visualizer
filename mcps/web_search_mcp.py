"""web_research - MCP server with web-search and scraping tools.

Design principles
-----------------
- Tools are thin data-fetchers.  The LLM agent does synthesis/summarization.

- Jina Reader is the only HTTP dependency for scraping.  Its use is explicit
  and every public function that touches the network documents the fact.

- Sources are fetched concurrently so wall-clock time scales with the slowest
  single request, not the sum of all requests.

- Every network call has an explicit timeout and a bounded retry count.

- Input validation raises ValueError with actionable messages before any
  network I/O begins.

Run as MCP server:
    python web_search_mcp.py
Smoke-test without MCP runtime:
    python web_search_mcp.py --smoke-test
"""

from __future__ import annotations

import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except ModuleNotFoundError:

    class FastMCP:  # type: ignore[override]
        """Minimal stub so the module can be imported without the *mcp* package."""

        def __init__(self, _name: str) -> None:
            self._name = _name

        def tool(self):
            def decorator(func):
                return func
            return decorator

        def run(self, transport: str = "stdio") -> None:
            raise RuntimeError(
                "FastMCP is unavailable.  Install the 'mcp' package to run as an MCP "
                f"server.  Requested transport={transport!r}."
            )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JINA_READER_PREFIX = "https://r.jina.ai/"
JINA_TIMEOUT_SECONDS = 20.0
JINA_MAX_RETRIES = 2

DDGO_TIMEOUT_SECONDS = 10.0

DEFAULT_TRANSPORT = "stdio"
DEFAULT_MAX_RESULTS = 5
DEFAULT_MAX_SOURCES = 5
DEFAULT_PER_SOURCE_CHARS = 2000  # generous: the agent will compress as needed

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "web-research-mcp/1.0",
    # Ask Jina to return plain text rather than markdown for cleaner extraction.
    "X-Return-Format": "text",
    "X-Retain-Images": "none",
}


def _get(
    url: str,
    timeout: float,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Blocking GET with bounded retries.

    Synchronous on purpose: FastMCP invokes these tools from inside a running
    event loop, so asyncio.run() here would raise "cannot be called from a
    running event loop". Cross-URL concurrency lives in _fetch_concurrently.
    """
    transport = httpx.HTTPTransport(retries=JINA_MAX_RETRIES)
    merged_headers = {**_HEADERS, **(headers or {})}
    with httpx.Client(
        transport=transport, follow_redirects=True, headers=merged_headers
    ) as client:
        return client.get(url, params=params, timeout=timeout)


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------


def _domain(url: str) -> str:
    """Return the lowercase netloc of *url*, or '' on failure."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _canonical(url: str) -> str:
    """Normalise protocol-relative URLs to https."""
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _jina_url(url: str) -> str:
    """Return *url* wrapped in the Jina Reader proxy.  Idempotent."""
    url = _canonical(url)
    if url.startswith(JINA_READER_PREFIX):
        return url
    return f"{JINA_READER_PREFIX}{url}"


def _unwrap_ddg(url: str) -> str:
    """Resolve a DuckDuckGo redirect to the real destination URL.

    Returns a plain, un-proxied URL.  Non-DDG URLs are returned unchanged
    (after protocol normalisation).
    """
    url = _canonical(url)
    parsed = urlparse(url)
    if "duckduckgo.com" not in parsed.netloc:
        return url
    uddg = parse_qs(parsed.query).get("uddg")
    return unquote(uddg[0]) if uddg else url


# ---------------------------------------------------------------------------
# DuckDuckGo search  (no external scraping_tools dependency)
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|span|div)>',
    re.IGNORECASE | re.DOTALL,
)


def _strip_tags(html: str) -> str:
    return _HTML_TAG_RE.sub("", html).strip()


def _ddg_search(query: str, max_results: int) -> list[dict[str, str]]:
    """Scrape DuckDuckGo HTML search and return structured results.

    Each result is a dict with ``title``, ``url``, ``snippet``.
    Raises ``httpx.HTTPError`` on network failure.
    """
    resp = _get(
        "https://html.duckduckgo.com/html/",
        timeout=DDGO_TIMEOUT_SECONDS,
        params={"q": query, "kl": "wt-wt"},
        # DDG blocks requests that look like automated scrapers without a browser UA.
        headers={"User-Agent": "Mozilla/5.0 (compatible; web-search-mcp/1.0)"},
    )
    resp.raise_for_status()
    html = resp.text

    titles_urls = _DDG_RESULT_RE.findall(html)
    snippets = [_strip_tags(s) for s in _SNIPPET_RE.findall(html)]

    results: list[dict[str, str]] = []
    for i, (raw_url, raw_title) in enumerate(titles_urls):
        if len(results) >= max_results:
            break
        url = _unwrap_ddg(_strip_tags(raw_url).strip())
        title = _strip_tags(raw_title).strip()
        snippet = snippets[i] if i < len(snippets) else ""
        if not url or not url.startswith("http"):
            continue
        results.append({"title": title, "url": url, "snippet": snippet})

    return results


# ---------------------------------------------------------------------------
# Jina Reader scraping  (self-contained, explicit proxy use)
# ---------------------------------------------------------------------------


def _jina_fetch(url: str, max_chars: int) -> dict[str, Any]:
    """Fetch *url* via Jina Reader and return structured page data.

    Args:
        url:       Plain http/https URL (Jina prefix added internally).
        max_chars: Truncate body text to this length.  -1 = no limit.

    Returns:
        On success: ``{"success": True, "url", "domain", "title", "text"}``
        On failure: ``{"success": False, "url", "domain", "title": "", "text": "", "error"}``

    Never raises — all errors are captured into the returned dict.
    """
    proxied = _jina_url(url)
    try:
        resp = _get(proxied, timeout=JINA_TIMEOUT_SECONDS)
        resp.raise_for_status()
        raw = resp.text.strip()

        # Jina plain-text responses begin with metadata lines like:
        #   Title: <page title>
        #   URL Source: <canonical url>
        #   ...
        #   <body text>
        title = ""
        source_url = url
        lines = raw.splitlines()
        body_start = 0
        for i, line in enumerate(lines):
            if line.startswith("Title:"):
                title = line.removeprefix("Title:").strip()
            elif line.startswith("URL Source:"):
                source_url = line.removeprefix("URL Source:").strip()
            elif i > 0 and line.strip() and not line.startswith(("Title:", "URL Source:", "Markdown Content:")):
                body_start = i
                break

        body = "\n".join(lines[body_start:]).strip()
        if max_chars >= 0:
            body = body[:max_chars]

        return {
            "success": True,
            "url": source_url,
            "domain": _domain(source_url),
            "title": title,
            "text": body,
        }

    except httpx.TimeoutException:
        msg = f"Timed out after {JINA_TIMEOUT_SECONDS}s"
        log.warning("%s fetching %s", msg, proxied)
        return {"success": False, "url": url, "domain": _domain(url), "title": "", "text": "", "error": msg}
    except httpx.HTTPStatusError as exc:
        msg = f"HTTP {exc.response.status_code}"
        log.warning("%s from Jina for %s", msg, url)
        return {"success": False, "url": url, "domain": _domain(url), "title": "", "text": "", "error": msg}
    except Exception as exc:
        msg = str(exc)
        log.warning("Unexpected error fetching %s: %s", url, msg)
        return {"success": False, "url": url, "domain": _domain(url), "title": "", "text": "", "error": msg}


# ---------------------------------------------------------------------------
# Concurrent fetch
# ---------------------------------------------------------------------------


def _fetch_concurrently(urls: list[str], max_chars: int) -> list[dict[str, Any]]:
    """Fetch all *urls* concurrently.  Order of results matches order of *urls*.

    Uses a thread pool rather than asyncio so it is safe to call from within
    FastMCP's running event loop.
    """
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(len(urls), 8)) as pool:
        return list(pool.map(lambda url: _jina_fetch(url, max_chars), urls))


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def _require_query(query: str) -> str:
    q = query.strip()
    if not q:
        raise ValueError("query must not be empty")
    return q


def _require_range(name: str, value: int, lo: int, hi: int) -> int:
    if not (lo <= value <= hi):
        raise ValueError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("web_search")


@mcp.tool()
def web_search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> dict[str, Any]:
    """Find relevant URLs for a query. Returns titles, URLs, and snippets only — no page content.

    Call this first when you need to discover sources. Then call fetch_web_page on
    specific results, or call research_topic to do both in one step.

    - max_results: 1–20. Use 3–5 for focused queries, up to 10 for broad surveys.
    - Results are ranked by relevance. Prefer results with matching domains/titles
      before fetching.
    """
    
    query = _require_query(query)
    _require_range("max_results", max_results, 1, 20)

    raw = _ddg_search(query, max_results)
    results = [
        {
            "rank": idx,
            "title": item["title"],
            "url": item["url"],
            "domain": _domain(item["url"]),
            "snippet": item["snippet"],
        }
        for idx, item in enumerate(raw, start=1)
    ]
    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
def fetch_web_page(url: str, max_text_chars: int = DEFAULT_PER_SOURCE_CHARS) -> dict[str, Any]:
    """Fetch and extract the text content of a single URL via Jina Reader.

    Use when you have a specific URL and need its content. Do not use for discovery —
    call web_search first if you don't have a URL yet.

    - max_text_chars: cap on returned body text. Use -1 for no limit (large pages may
      exceed context). 800–2000 is usually sufficient for factual extraction.
    - Returns success=False with an error string on timeout or HTTP error. Always
      check the success field before using text.
    - title and url in the response reflect the canonical page values, which may
      differ from the URL you passed in.
    """

    url = url.strip()
    if not url:
        raise ValueError("url must not be empty")
    return _jina_fetch(url, max_text_chars)


@mcp.tool()
def research_topic(
    query: str,
    max_sources: int = DEFAULT_MAX_SOURCES,
    per_source_chars: int = DEFAULT_PER_SOURCE_CHARS,
) -> dict[str, Any]:
    """Search and fetch multiple sources on a topic in one call. Returns raw source
    text per result — you synthesize the answer from the returned text fields.

    Use this instead of calling web_search + fetch_web_page in a loop. Do not use
    if you only need one specific page (use fetch_web_page) or only need URLs
    (use web_search).

    - max_sources: 1–10. Use 3–5 for most questions, up to 10 for comparative or
      contested topics where source diversity matters.
    - per_source_chars: applied per source. Lower (600–800) for skimming many sources,
      higher (2000+) for deep extraction from fewer.
    - Sources are fetched concurrently. Failed fetches appear with error set and
      text empty — skip them or note the failure.
    - successful_count tells you how many sources have usable text.
    """

    query = _require_query(query)
    _require_range("max_sources", max_sources, 1, 10)

    search_results = web_search(query, max_results=max_sources)
    items = search_results["results"]

    pages = _fetch_concurrently([item["url"] for item in items], per_source_chars)

    sources: list[dict[str, Any]] = []
    for item, page in zip(items, pages):
        source: dict[str, Any] = {
            "id": str(item["rank"]),
            "title": page.get("title") or item["title"],
            "url": item["url"],
            "domain": item["domain"],
            "snippet": item["snippet"],
            "text": page.get("text", ""),
        }
        if not page["success"]:
            source["error"] = page.get("error", "unknown error")
        sources.append(source)

    return {
        "query": query,
        "source_count": len(sources),
        "successful_count": sum(1 for s in sources if "error" not in s),
        "sources": sources,
    }


@mcp.tool()
def research_multiple_topics(
    queries: list[str],
    max_sources_per_query: int = 4,
    per_source_chars: int = DEFAULT_PER_SOURCE_CHARS,
) -> dict[str, Any]:
    """Research several distinct questions in one call, deduplicating fetches across
    queries. If the same URL ranks for two queries it is fetched once.

    Use when the user asks multiple separate questions that each require web research.
    Do not use to break a single question into sub-queries — use research_topic instead.

    - queries: each entry is treated as an independent research_topic call.
    - Results are grouped by query in the same order as the input list.
    - Check successful_count per query result to assess coverage before answering.
    """

    if not queries:
        raise ValueError("queries must not be empty")
    _require_range("max_sources_per_query", max_sources_per_query, 1, 10)

    # Phase 1: search all queries (sequential — each is fast)
    all_search: list[dict[str, Any]] = [
        web_search(_require_query(q), max_results=max_sources_per_query)
        for q in queries
    ]

    # Phase 2: collect unique URLs then fetch all concurrently
    url_order: list[str] = []
    seen: set[str] = set()
    for sr in all_search:
        for item in sr["results"]:
            if item["url"] not in seen:
                seen.add(item["url"])
                url_order.append(item["url"])

    pages_by_url: dict[str, dict[str, Any]] = dict(
        zip(url_order, _fetch_concurrently(url_order, per_source_chars))
    )

    # Phase 3: assemble per-query results from the shared page cache
    results: list[dict[str, Any]] = []
    for q, sr in zip(queries, all_search):
        sources: list[dict[str, Any]] = []
        for item in sr["results"]:
            page = pages_by_url[item["url"]]
            source: dict[str, Any] = {
                "id": str(item["rank"]),
                "title": page.get("title") or item["title"],
                "url": item["url"],
                "domain": item["domain"],
                "snippet": item["snippet"],
                "text": page.get("text", ""),
            }
            if not page["success"]:
                source["error"] = page.get("error", "unknown error")
            sources.append(source)

        results.append({
            "query": q,
            "source_count": len(sources),
            "successful_count": sum(1 for s in sources if "error" not in s),
            "sources": sources,
        })

    return {"queries": queries, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Smoke test (no MCP runtime required)
# ---------------------------------------------------------------------------


def _smoke_test() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    log.info("── web_search ──────────────────────────────────────────────")
    search = web_search("latest ai model benchmarks", max_results=3)
    log.info("count=%d", search["count"])
    for r in search["results"]:
        log.info("  [%d] %-30s %s", r["rank"], r["domain"], r["title"][:70])

    if search["results"]:
        first_url = search["results"][0]["url"]
        log.info("── fetch_web_page ──────────────────────────────────────────")
        log.info("url=%s", first_url)
        page = fetch_web_page(first_url, max_text_chars=600)
        status = "✓" if page["success"] else f"✗ {page.get('error')}"
        log.info("status=%s  title=%s  chars=%d", status, page.get("title", "")[:60], len(page.get("text", "")))

    log.info("── research_topic ──────────────────────────────────────────")
    r = research_topic("ai coding agents 2025", max_sources=3, per_source_chars=600)
    log.info("source_count=%d  successful=%d", r["source_count"], r["successful_count"])
    for s in r["sources"]:
        status = "✓" if "error" not in s else f"✗ {s['error']}"
        log.info("  [%s] %-30s %s", s["id"], s["domain"], status)

    log.info("── research_multiple_topics ────────────────────────────────")
    m = research_multiple_topics(
        ["python async patterns", "mcp protocol overview"],
        max_sources_per_query=2,
        per_source_chars=400,
    )
    for qr in m["results"]:
        log.info("  query=%-35r sources=%d ok=%d", qr["query"], qr["source_count"], qr["successful_count"])

    log.info("── done ────────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        _smoke_test()
    else:
        mcp.run(transport=DEFAULT_TRANSPORT)