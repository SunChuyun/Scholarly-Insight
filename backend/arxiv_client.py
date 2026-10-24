"""Search arXiv and convert its Atom feed into JSON-ready data."""

import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests

API_URL = "https://export.arxiv.org/api/query"
PAGE_SIZE = 20
REQUEST_INTERVAL = 3.0
NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
_request_lock = threading.Lock()
_last_request_started = None


class ArxivError(Exception):
    """An upstream failure that can be returned as an HTTP error."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _text(element, path):
    return " ".join(element.findtext(path, default="", namespaces=NAMESPACES).split())


def search_papers(query, page):
    """Fetch one page; all whitespace-separated search terms must match."""
    terms = (term.replace("\\", "\\\\").replace('"', '\\"') for term in query.split())
    params = {
        "search_query": " AND ".join(f'all:"{term}"' for term in terms),
        "start": (page - 1) * PAGE_SIZE,
        "max_results": PAGE_SIZE,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    global _last_request_started
    try:
        # Keep a single connection and space request starts at least three seconds apart.
        with _request_lock:
            if _last_request_started is not None:
                delay = REQUEST_INTERVAL - (time.monotonic() - _last_request_started)
                if delay > 0:
                    time.sleep(delay)
            _last_request_started = time.monotonic()
            response = requests.get(
                API_URL,
                params=params,
                headers={"User-Agent": "ScholarlyInsight/0.1"},
                timeout=30,
            )
            response.raise_for_status()
    except requests.Timeout as exc:
        raise ArxivError("The request to arXiv timed out. Please try again.", 504) from exc
    except requests.RequestException as exc:
        status = 503 if getattr(exc.response, "status_code", None) == 429 else 502
        raise ArxivError("arXiv is temporarily unavailable. Please try again later.", status) from exc

    try:
        feed = ET.fromstring(response.content)
        if feed.tag != f"{{{NAMESPACES['atom']}}}feed":
            raise ValueError("Expected an Atom feed.")
        total = int(feed.findtext("opensearch:totalResults", namespaces=NAMESPACES))
        entries = feed.findall("atom:entry", NAMESPACES)
        if total < 0 or len(entries) > PAGE_SIZE:
            raise ValueError("Invalid result count.")

        items = []
        for entry in entries:
            identifier = urlparse(_text(entry, "atom:id"))
            title = _text(entry, "atom:title")
            if not identifier.path.startswith("/abs/") or not title:
                raise ValueError("Expected a paper entry.")
            paper_id = identifier.path.removeprefix("/abs/")
            if not paper_id:
                raise ValueError("Missing paper identifier.")
            pdf_url = next(
                (
                    link.get("href")
                    for link in entry.findall("atom:link", NAMESPACES)
                    if link.get("title") == "pdf"
                ),
                None,
            )
            items.append(
                {
                    "id": paper_id,
                    "title": title,
                    "authors": [
                        _text(author, "atom:name")
                        for author in entry.findall("atom:author", NAMESPACES)
                    ],
                    "abstract": _text(entry, "atom:summary"),
                    "submitted_at": _text(entry, "atom:published"),
                    "updated_at": _text(entry, "atom:updated"),
                    "categories": [
                        category.get("term")
                        for category in entry.findall("atom:category", NAMESPACES)
                        if category.get("term")
                    ],
                    "abstract_url": f"https://arxiv.org/abs/{paper_id}",
                    "pdf_url": pdf_url.replace("http://", "https://", 1) if pdf_url else None,
                }
            )
    except (ET.ParseError, TypeError, ValueError) as exc:
        raise ArxivError("arXiv returned an invalid search response.") from exc

    return {
        "query": query,
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": (total + PAGE_SIZE - 1) // PAGE_SIZE,
        "has_previous": page > 1,
        "has_next": page * PAGE_SIZE < total,
        "items": items,
    }
