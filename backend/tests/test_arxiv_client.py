"""Verify arXiv parsing, pagination, failures, and request spacing offline."""

import unittest
from unittest.mock import Mock, patch

import requests

from backend.clients import arxiv as arxiv_client
from backend.tests.fixtures import atom_feed


class ArxivClientTests(unittest.TestCase):
    def setUp(self):
        arxiv_client._last_request_started = None
        for target, name in (
            ("backend.clients.arxiv.requests.get", "get"),
            ("backend.clients.arxiv.time.sleep", "sleep"),
            ("backend.clients.arxiv.time.monotonic", "clock"),
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



if __name__ == "__main__":
    unittest.main()
