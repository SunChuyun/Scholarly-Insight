"""Deterministic tests: no internet connection or real rate-limit waits are needed."""

import unittest
from unittest.mock import Mock, patch

import requests

from backend import app as web
from backend import arxiv_client


def atom_feed(total=1, start=0, count=1):
    """Build small, synthetic arXiv responses for pagination and parsing tests."""
    entries = "".join(
        f"""
        <entry>
          <id>http://arxiv.org/abs/2601.{number:05d}v1</id>
          <title>A sample\n paper &amp; metadata</title>
          <author><name>Ana Example</name></author>
          <author><name>Ben Example</name></author>
          <summary>First line.\n Second line.</summary>
          <published>2026-01-01T12:00:00Z</published>
          <updated>2026-01-02T12:00:00Z</updated>
          <category term="cs.AI"/><category term="cs.CL"/>
          <link title="pdf" href="http://arxiv.org/pdf/2601.{number:05d}v1"/>
        </entry>"""
        for number in range(start, start + count)
    )
    return f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
        <opensearch:totalResults>{total}</opensearch:totalResults>
        <opensearch:startIndex>{start}</opensearch:startIndex>
        {entries}</feed>""".encode()


class ArxivClientTests(unittest.TestCase):
    def setUp(self):
        arxiv_client._last_request_started = None
        for target, name in (
            ("backend.arxiv_client.requests.get", "get"),
            ("backend.arxiv_client.time.sleep", "sleep"),
            ("backend.arxiv_client.time.monotonic", "clock"),
        ):
            patcher = patch(target)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.clock.return_value = 1000.0
        self.response = Mock(content=atom_feed())
        self.get.return_value = self.response

    def test_parses_paper_metadata_and_normalizes_whitespace(self):
        result = arxiv_client.search_papers("sample", 1)
        paper = result["items"][0]
        self.assertEqual(paper["id"], "2601.00000v1")
        self.assertEqual(paper["title"], "A sample paper & metadata")
        self.assertEqual(paper["authors"], ["Ana Example", "Ben Example"])
        self.assertEqual(paper["abstract"], "First line. Second line.")
        self.assertEqual(paper["categories"], ["cs.AI", "cs.CL"])
        self.assertEqual(paper["submitted_at"], "2026-01-01T12:00:00Z")
        self.assertEqual(paper["updated_at"], "2026-01-02T12:00:00Z")
        self.assertEqual(paper["abstract_url"], "https://arxiv.org/abs/2601.00000v1")
        self.assertEqual(paper["pdf_url"], "https://arxiv.org/pdf/2601.00000v1")

    def test_pages_use_twenty_result_windows_and_last_page_metadata(self):
        self.get.side_effect = [
            Mock(content=atom_feed(total=21, count=20)),
            Mock(content=atom_feed(total=21, start=20, count=1)),
        ]
        first = arxiv_client.search_papers("sample", 1)
        second = arxiv_client.search_papers("sample", 2)
        calls = self.get.call_args_list
        self.assertEqual(calls[0].kwargs["params"]["start"], 0)
        self.assertEqual(calls[1].kwargs["params"]["start"], 20)
        self.assertTrue(all(call.kwargs["params"]["max_results"] == 20 for call in calls))
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(len(second["items"]), 1)
        self.assertTrue(first["has_next"])
        self.assertFalse(first["has_previous"])
        self.assertFalse(second["has_next"])
        self.assertTrue(second["has_previous"])
        self.assertEqual(second["total_pages"], 2)
        self.assertTrue({p["id"] for p in first["items"]}.isdisjoint(
            {p["id"] for p in second["items"]}
        ))

    def test_multiple_terms_use_and_and_escape_query_syntax(self):
        arxiv_client.search_papers('machine learning"', 1)
        params = self.get.call_args.kwargs["params"]
        self.assertEqual(params["search_query"], 'all:"machine" AND all:"learning\\""')
        self.assertEqual(params["sortBy"], "relevance")

    def test_empty_results_have_zero_pages(self):
        self.response.content = atom_feed(total=0, count=0)
        result = arxiv_client.search_papers("unmatched", 1)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total_pages"], 0)
        self.assertFalse(result["has_next"])

    def test_missing_pdf_is_null(self):
        self.response.content = atom_feed().replace(
            b'<link title="pdf" href="http://arxiv.org/pdf/2601.00000v1"/>', b""
        )
        self.assertIsNone(arxiv_client.search_papers("sample", 1)["items"][0]["pdf_url"])

    def test_legacy_identifiers_keep_their_slash_and_version(self):
        self.response.content = atom_feed().replace(b"2601.00000v1", b"hep-th/9901001v2")
        self.assertEqual(
            arxiv_client.search_papers("sample", 1)["items"][0]["id"], "hep-th/9901001v2"
        )

    def test_invalid_and_error_feeds_are_not_reported_as_empty_results(self):
        invalid_responses = [
            b"not XML",
            b"<html>Service unavailable</html>",
            atom_feed().replace(b"/abs/2601.00000v1", b"/api/errors"),
            atom_feed().replace(b"<opensearch:totalResults>1</opensearch:totalResults>", b""),
            atom_feed(total=-1, count=0),
        ]
        for content in invalid_responses:
            with self.subTest(content=content):
                self.response.content = content
                with self.assertRaises(arxiv_client.ArxivError) as caught:
                    arxiv_client.search_papers("sample", 1)
                self.assertEqual(caught.exception.status_code, 502)

    def test_timeout_becomes_a_gateway_timeout(self):
        self.get.side_effect = requests.Timeout("Timed out")
        with self.assertRaises(arxiv_client.ArxivError) as caught:
            arxiv_client.search_papers("sample", 1)
        self.assertEqual(caught.exception.status_code, 504)

    def test_connection_failure_becomes_a_gateway_error(self):
        self.get.side_effect = requests.ConnectionError("Connection failed")
        with self.assertRaises(arxiv_client.ArxivError) as caught:
            arxiv_client.search_papers("sample", 1)
        self.assertEqual(caught.exception.status_code, 502)

    def test_upstream_rate_limit_becomes_service_unavailable(self):
        self.response.raise_for_status.side_effect = requests.HTTPError(
            "Too many requests", response=Mock(status_code=429)
        )
        with self.assertRaises(arxiv_client.ArxivError) as caught:
            arxiv_client.search_papers("sample", 1)
        self.assertEqual(caught.exception.status_code, 503)

    def test_request_starts_are_spaced_three_seconds_apart(self):
        self.clock.side_effect = [100.0, 101.0, 103.0]
        arxiv_client.search_papers("first", 1)
        arxiv_client.search_papers("second", 1)
        self.sleep.assert_called_once_with(2.0)


class SearchRouteTests(unittest.TestCase):
    def setUp(self):
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()
        patcher = patch("backend.app.search_papers")
        self.search = patcher.start()
        self.addCleanup(patcher.stop)
        self.search.return_value = {
            "query": "sample", "page": 1, "page_size": 20, "total": 0,
            "total_pages": 0, "has_previous": False, "has_next": False, "items": [],
        }

    def test_search_returns_json_and_defaults_to_page_one(self):
        response = self.client.get("/api/search", query_string={"q": "sample"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertEqual(response.json["page_size"], 20)
        self.assertEqual(response.json["items"], [])
        self.search.assert_called_once_with("sample", 1)

    def test_normalizes_keyword_and_accepts_page_two(self):
        response = self.client.get(
            "/api/search", query_string={"q": "  machine   learning  ", "page": "2"}
        )
        self.assertEqual(response.status_code, 200)
        self.search.assert_called_once_with("machine learning", 2)

    def test_missing_blank_and_overlong_queries_do_not_call_arxiv(self):
        for params in ({}, {"q": ""}, {"q": "   "}, {"q": "a" * 301}):
            with self.subTest(params=params):
                response = self.client.get("/api/search", query_string=params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["error"]["code"], "INVALID_QUERY")
        self.search.assert_not_called()

    def test_invalid_pages_do_not_call_arxiv(self):
        for page in ("0", "-1", "1.5", "abc", "", "1_0", "9" * 5000):
            with self.subTest(page=page[:20]):
                response = self.client.get("/api/search", query_string={"q": "sample", "page": page})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["error"]["code"], "INVALID_PAGE")
        self.search.assert_not_called()

    def test_upstream_errors_keep_their_status_and_json_shape(self):
        for status in (502, 503, 504):
            with self.subTest(status=status):
                self.search.side_effect = arxiv_client.ArxivError("Upstream failure.", status)
                response = self.client.get("/api/search?q=sample")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json["error"]["code"], "UPSTREAM_ERROR")

    def test_frontend_origin_can_read_the_search_response(self):
        response = self.client.get(
            "/api/search?q=sample", headers={"Origin": "http://localhost:5173"}
        )
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:5173")

    def test_get_preflight_is_supported(self):
        response = self.client.options("/api/search", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("GET", response.headers["Access-Control-Allow-Methods"])
        self.search.assert_not_called()

    def test_unknown_routes_and_unsupported_methods_return_json(self):
        for method, path, status in (("GET", "/", 404), ("POST", "/api/search", 405)):
            with self.subTest(method=method, path=path):
                response = self.client.open(path, method=method)
                self.assertEqual(response.status_code, status)
                self.assertIn("error", response.json)


class HealthRouteTests(unittest.TestCase):
    def setUp(self):
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def test_health_returns_ok_without_calling_arxiv(self):
        with (
            patch("backend.app.search_papers") as search,
            patch("backend.arxiv_client.requests.get") as upstream,
        ):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        search.assert_not_called()
        upstream.assert_not_called()

    def test_health_is_independent_of_search_failure(self):
        with patch(
            "backend.app.search_papers",
            side_effect=arxiv_client.ArxivError("Upstream unavailable.", 502),
        ) as search:
            self.assertEqual(self.client.get("/api/search?q=sample").status_code, 502)
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        search.assert_called_once_with("sample", 1)

    def test_health_allows_browser_get_and_preflight(self):
        origin = "http://localhost:5173"
        response = self.client.get("/api/health", headers={"Origin": origin})
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], origin)
        preflight = self.client.options("/api/health", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
        })
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["Access-Control-Allow-Origin"], origin)
        self.assertIn("GET", preflight.headers["Access-Control-Allow-Methods"])


if __name__ == "__main__":
    unittest.main()
