"""
Reusable scraping helper functions for MCP tools.

This module is intentionally framework-agnostic: import and call these
functions directly from your own MCP tool definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_USER_AGENT = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class ScrapeResult:
	"""Normalized structure for high-level scrape helpers."""

	source: str
	title: str
	url: str
	snippet: str = ""
	extra: dict[str, Any] | None = None


def build_session(
	user_agent: str = DEFAULT_USER_AGENT,
	retries: int = 3,
	backoff_factor: float = 0.4,
) -> requests.Session:
	"""Create a requests session with retry behavior for transient failures."""
	session = requests.Session()
	retry = Retry(
		total=retries,
		read=retries,
		connect=retries,
		backoff_factor=backoff_factor,
		status_forcelist=(429, 500, 502, 503, 504),
		allowed_methods=("GET", "HEAD", "OPTIONS"),
		raise_on_status=False,
	)
	adapter = HTTPAdapter(max_retries=retry)
	session.mount("http://", adapter)
	session.mount("https://", adapter)
	session.headers.update(
		{
			"User-Agent": user_agent,
			"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
			"Accept-Language": "en-US,en;q=0.9",
		}
	)
	return session


def _safe_get(session: requests.Session, url: str, timeout: float = 20.0, **kwargs: Any) -> requests.Response:
	response = session.get(url, timeout=timeout, **kwargs)
	response.raise_for_status()
	return response


def fetch_html(
	url: str,
	*,
	session: requests.Session | None = None,
	timeout: float = 20.0,
	params: dict[str, Any] | None = None,
) -> str:
	"""Fetch page HTML and return decoded text."""
	close_after = session is None
	active_session = session or build_session()
	try:
		response = _safe_get(active_session, url, timeout=timeout, params=params)
		return response.text
	finally:
		if close_after:
			active_session.close()


def get_soup(
	url: str,
	*,
	session: requests.Session | None = None,
	timeout: float = 20.0,
	parser: str = "html.parser",
) -> BeautifulSoup:
	"""Fetch a URL and parse the response into BeautifulSoup."""
	html = fetch_html(url, session=session, timeout=timeout)
	return BeautifulSoup(html, parser)


def soup_from_html(html: str, parser: str = "html.parser") -> BeautifulSoup:
	"""Parse raw HTML content into BeautifulSoup."""
	return BeautifulSoup(html, parser)


def extract_text(
	soup: BeautifulSoup,
	selector: str | None = None,
	*,
	separator: str = " ",
	strip: bool = True,
) -> str:
	"""Extract cleaned text, optionally scoped to a CSS selector."""
	node = soup.select_one(selector) if selector else soup
	if node is None:
		return ""
	return node.get_text(separator=separator, strip=strip)


def extract_links(
	soup: BeautifulSoup,
	*,
	base_url: str | None = None,
	allowed_domains: Iterable[str] | None = None,
	unique: bool = True,
) -> list[str]:
	"""Extract href values from anchor tags with optional filtering."""
	links: list[str] = []
	seen: set[str] = set()
	normalized_domains = {d.lower() for d in allowed_domains or []}

	for anchor in soup.select("a[href]"):
		href = anchor.get("href", "").strip()
		if not href:
			continue

		url = urljoin(base_url, href) if base_url else href
		parsed = urlparse(url)

		if normalized_domains and parsed.netloc.lower() not in normalized_domains:
			continue

		if unique:
			if url in seen:
				continue
			seen.add(url)
		links.append(url)

	return links


def extract_metadata(soup: BeautifulSoup) -> dict[str, str]:
	"""Extract common page-level metadata (title, description, og tags)."""
	metadata: dict[str, str] = {}

	if soup.title and soup.title.string:
		metadata["title"] = soup.title.string.strip()

	for tag in soup.select("meta[name], meta[property]"):
		key = (tag.get("name") or tag.get("property") or "").strip().lower()
		value = (tag.get("content") or "").strip()
		if key and value and key not in metadata:
			metadata[key] = value

	return metadata


def extract_main_text(soup: BeautifulSoup) -> str:
	"""Heuristic extraction for article-like page body content."""
	preferred_selectors = [
		"article",
		"main",
		"[role='main']",
		"#content",
		".content",
		".post-content",
		".entry-content",
	]
	for selector in preferred_selectors:
		node = soup.select_one(selector)
		if node:
			return node.get_text(" ", strip=True)
	return soup.get_text(" ", strip=True)


def duckduckgo_search(
	query: str,
	*,
	max_results: int = 10,
	session: requests.Session | None = None,
	timeout: float = 20.0,
) -> list[ScrapeResult]:
	"""Search DuckDuckGo HTML and return normalized result items."""
	close_after = session is None
	active_session = session or build_session()
	try:
		search_url = "https://html.duckduckgo.com/html/"
		response = _safe_get(active_session, search_url, timeout=timeout, params={"q": query})
		soup = BeautifulSoup(response.text, "html.parser")
		results: list[ScrapeResult] = []
		for block in soup.select(".result"):
			link_node = block.select_one("a.result__a")
			if not link_node:
				continue

			title = link_node.get_text(" ", strip=True)
			url = link_node.get("href", "").strip()
			snippet_node = block.select_one(".result__snippet")
			snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
			if title and url:
				results.append(ScrapeResult(source="duckduckgo", title=title, url=url, snippet=snippet))
			if len(results) >= max_results:
				break
		return results
	finally:
		if close_after:
			active_session.close()


def wikipedia_summary(
	title: str,
	*,
	session: requests.Session | None = None,
	timeout: float = 20.0,
) -> ScrapeResult | None:
	"""Fetch summary info from Wikipedia's REST endpoint by page title."""
	close_after = session is None
	active_session = session or build_session()
	try:
		safe_title = quote_plus(title.replace(" ", "_"))
		endpoint = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}"
		response = _safe_get(active_session, endpoint, timeout=timeout)
		data = response.json()
		page_title = data.get("title") or title
		page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
		snippet = data.get("extract", "")
		if not page_url:
			return None
		return ScrapeResult(
			source="wikipedia",
			title=page_title,
			url=page_url,
			snippet=snippet,
			extra={"type": data.get("type", "")},
		)
	except requests.RequestException:
		return None
	finally:
		if close_after:
			active_session.close()


def arxiv_search(
	query: str,
	*,
	max_results: int = 5,
	session: requests.Session | None = None,
	timeout: float = 25.0,
) -> list[ScrapeResult]:
	"""Search arXiv via Atom API and return normalized entries."""
	close_after = session is None
	active_session = session or build_session()
	try:
		params = {
			"search_query": f"all:{query}",
			"start": 0,
			"max_results": max_results,
			"sortBy": "relevance",
		}
		endpoint = "https://export.arxiv.org/api/query"
		response = _safe_get(active_session, endpoint, timeout=timeout, params=params)
		soup = BeautifulSoup(response.text, "xml")

		results: list[ScrapeResult] = []
		for entry in soup.find_all("entry"):
			title_node = entry.find("title")
			summary_node = entry.find("summary")
			id_node = entry.find("id")
			if not title_node or not id_node:
				continue
			title = title_node.get_text(" ", strip=True)
			summary = summary_node.get_text(" ", strip=True) if summary_node else ""
			results.append(
				ScrapeResult(
					source="arxiv",
					title=title,
					url=id_node.get_text(strip=True),
					snippet=summary,
				)
			)
		return results
	finally:
		if close_after:
			active_session.close()


def scrape_url(
	url: str,
	*,
	session: requests.Session | None = None,
	timeout: float = 20.0,
) -> dict[str, Any]:
	"""One-call helper to fetch a page and return common scrape outputs."""
	close_after = session is None
	active_session = session or build_session()
	try:
		soup = get_soup(url, session=active_session, timeout=timeout)
		return {
			"url": url,
			"metadata": extract_metadata(soup),
			"main_text": extract_main_text(soup),
			"links": extract_links(soup, base_url=url),
		}
	finally:
		if close_after:
			active_session.close()


def find_by_title(
	title: str,
	*,
	max_results: int = 5,
	include_wikipedia: bool = True,
	include_arxiv: bool = True,
) -> dict[str, Any]:
	"""High-level title search that combines multiple sources."""
	with build_session() as session:
		results: dict[str, Any] = {
			"query": title,
			"duckduckgo": duckduckgo_search(title, max_results=max_results, session=session),
		}

		if include_wikipedia:
			results["wikipedia"] = wikipedia_summary(title, session=session)

		if include_arxiv:
			results["arxiv"] = arxiv_search(title, max_results=max_results, session=session)

		return results


__all__ = [
	"DEFAULT_USER_AGENT",
	"ScrapeResult",
	"build_session",
	"fetch_html",
	"get_soup",
	"soup_from_html",
	"extract_text",
	"extract_links",
	"extract_metadata",
	"extract_main_text",
	"duckduckgo_search",
	"wikipedia_summary",
	"arxiv_search",
	"scrape_url",
	"find_by_title",
]
