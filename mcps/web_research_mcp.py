from __future__ import annotations

import re
import sys
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    class FastMCP:  # type: ignore[override]
        """Minimal fallback to allow local smoke tests without mcp package."""

        def __init__(self, _name: str) -> None:
            self._name = _name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self, transport: str = "stdio") -> None:
            raise RuntimeError(
                "FastMCP is unavailable. Install the 'mcp' package to run as MCP server. "
                f"Requested transport={transport!r}."
            )

from scraping_tools import duckduckgo_search, scrape_url

mcp = FastMCP("web_research")


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return url
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _unwrap_duckduckgo_redirect(url: str) -> str:
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    if "duckduckgo.com" not in parsed.netloc:
        return normalized
    qs = parse_qs(parsed.query)
    uddg = qs.get("uddg")
    if not uddg:
        return normalized
    return unquote(uddg[0])


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _sentences(text: str, limit: int = 3) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    chunks = re.split(r"(?<=[\.!?؟])\s+", cleaned)
    picked = [chunk.strip() for chunk in chunks if chunk.strip()]
    return picked[: max(limit, 0)]


def _keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[\w\u0600-\u06FF]{4,}", text.lower())
    stop = {
        "that",
        "this",
        "with",
        "from",
        "have",
        "will",
        "their",
        "about",
        "there",
        "would",
        "which",
        "what",
        "when",
        "where",
        "على",
        "الى",
        "إلى",
        "هذا",
        "هذه",
        "ذلك",
        "التي",
        "الذي",
        "وقد",
        "كانت",
        "يكون",
    }
    freq: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
    return [k for k, _ in ranked[: max(limit, 0)]]


@mcp.tool()
def web_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """Search the web and return a ranked list of result links.

    Use this tool when you need to discover relevant webpages for a query.
    This tool only returns search results (titles, URLs, snippets) and does NOT fetch page content.
    If you need the contents of a webpage, use get_web_page_info instead.
    """
    raw = duckduckgo_search(query, max_results=max_results)
    results: list[dict[str, Any]] = []

    for idx, item in enumerate(raw, start=1):
        url = _unwrap_duckduckgo_redirect(item.url)
        results.append(
            {
                "rank": idx,
                "title": item.title,
                "url": url,
                "domain": _domain(url),
                "snippet": _clean_text(item.snippet),
                "source_engine": "duckduckgo",
            }
        )

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


@mcp.tool()
def fetch_web_page(url: str, max_text_chars: int = 3000) -> dict[str, Any]:
    """Fetch and analyze a single webpage by URL.

    Use this tool when you already have a webpage URL and need its contents.
    Returns extracted text, metadata, important sentences, and outgoing links.

    Input must be a valid webpage URL.
    Do NOT pass search queries to this tool.
    """
    
    normalized_url = _unwrap_duckduckgo_redirect(url)

    try:
        data = scrape_url(normalized_url)

        text = _clean_text(data.get("main_text", ""))
        if max_text_chars > 0:
            text = text[:max_text_chars]

        return {
            "success": True,
            "url": data.get("url", normalized_url),
            "domain": _domain(normalized_url),
            "metadata": data.get("metadata", {}),
            "text": text,
            "highlights": _sentences(text, limit=4),
            "links": data.get("links", [])[:30],
        }

    except Exception as e:
        return {
            "success": False,
            "url": normalized_url,
            "error": str(e),
            "text": "",
            "highlights": [],
            "links": [],
        }


@mcp.tool()
def research_topic(query: str, max_sources: int = 5, per_source_chars: int = 2200) -> dict[str, Any]:
    """Perform full web research on a topic.

    This tool automatically:
    1. Searches the web for relevant pages
    2. Fetches multiple pages
    3. Extracts text and key highlights
    4. Produces summarized key points with citations.

    Use this tool when the user asks for a researched explanation or summary of a topic.

    Do NOT use this tool if you only need search results or a single webpage.
    """
    search = web_search(query, max_results=max_sources)
    sources: list[dict[str, Any]] = []
    combined_text_parts: list[str] = []

    for item in search.get("results", [])[: max_sources]:
        try:
            page = fetch_web_page(item["url"], max_text_chars=per_source_chars)
            text = page.get("text", "")
            combined_text_parts.append(text)
            sources.append(
                {
                    "id": f"S{item['rank']}",
                    "title": item["title"],
                    "url": item["url"],
                    "domain": item["domain"],
                    "snippet": item.get("snippet", ""),
                    "highlights": page.get("highlights", []),
                    "metadata": page.get("metadata", {}),
                }
            )
        except Exception as exc:
            sources.append(
                {
                    "id": f"S{item['rank']}",
                    "title": item["title"],
                    "url": item["url"],
                    "domain": item["domain"],
                    "snippet": item.get("snippet", ""),
                    "error": str(exc),
                }
            )

    combined_text = _clean_text(" ".join(combined_text_parts))
    summary_points = _sentences(combined_text, limit=8)

    return {
        "query": query,
        "source_count": len(sources),
        "summary": {
            "key_points": summary_points,
            "top_keywords": _keywords(combined_text, limit=10),
        },
        "sources": sources,
        "citation_guide": "Cite with source ids like S1, S2, S3.",
    }


@mcp.tool()
def research_multiple_topics(queries: list[str], max_sources_per_query: int = 4) -> dict[str, Any]:
    """Research multiple topics or questions at once.

    Runs research_topic separately for each query and returns results grouped by query.

    Use this tool when the user asks about several different topics or questions in one request.
    """
    outputs: list[dict[str, Any]] = []
    for q in queries:
        outputs.append(research_topic(q, max_sources=max_sources_per_query))

    return {
        "queries": queries,
        "count": len(outputs),
        "results": outputs,
    }

# Note: The following smoke test is designed to run without the full MCP environment, allowing for quick local testing of the core functionality. 
# It can be invoked with the --smoke-test flag when running this script directly.

def _smoke_test() -> None:
    print("[smoke] web_search('latest ai model benchmarks')")
    search = web_search("latest ai model benchmarks", max_results=5)
    print(f"  count={search.get('count')}")

    results = search.get("results", [])
    if results:
        first = results[0]
        print(f"  first_title={str(first.get('title', ''))[:100]}")
        print(f"  first_url={first.get('url')}")

        print("[smoke] fetch_web_page(first_url)")
        page = fetch_web_page(first["url"], max_text_chars=1200)
        print(f"  page_domain={page.get('domain')}")
        print(f"  highlights_count={len(page.get('highlights', []))}")

    print("[smoke] research_topic('ai coding agents')")
    research = research_topic("ai coding agents", max_sources=3, per_source_chars=1200)
    print(f"  source_count={research.get('source_count')}")
    print(f"  key_points={len(research.get('summary', {}).get('key_points', []))}")

    print("[smoke] research_multiple_topics([...])")
    multi = research_multiple_topics(["python web scraping", "mcp protocol"], max_sources_per_query=2)
    print(f"  multi_count={multi.get('count')}")
    print("[smoke] done")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        _smoke_test()
    else:
        main()
