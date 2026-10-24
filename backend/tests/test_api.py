"""Verify HTTP contracts and application integration without external requests."""

import unittest
from unittest.mock import Mock, patch

from backend import create_app
from backend.clients import arxiv as arxiv_client
from backend.tests.fixtures import atom_feed


class SearchRouteTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        patcher = patch("backend.api.routes.search_papers")
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
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_health_returns_ok_without_calling_arxiv(self):
        with (
            patch("backend.api.routes.search_papers") as search,
            patch("backend.clients.arxiv.requests.get") as upstream,
        ):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        search.assert_not_called()
        upstream.assert_not_called()

    def test_health_is_independent_of_search_failure(self):
        with patch(
            "backend.api.routes.search_papers",
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


class ApplicationIntegrationTests(unittest.TestCase):
    def test_factories_create_independent_application_settings(self):
        first = create_app()
        second = create_app()
        first.config["TESTING"] = True
        self.assertFalse(second.testing)
        for app in (first, second):
            with self.subTest(app=app.name):
                self.assertEqual(app.test_client().get("/api/health").json, {"status": "ok"})

    def test_search_runs_through_the_client_and_parser(self):
        app = create_app()
        app.config["TESTING"] = True
        response_data = Mock(content=atom_feed(total=21, start=20, count=1))
        with (
            patch("backend.clients.arxiv._last_request_started", None),
            patch("backend.clients.arxiv.requests.get", return_value=response_data) as upstream,
        ):
            response = app.test_client().get(
                "/api/search", query_string={"q": "  machine   learning  ", "page": "2"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["query"], "machine learning")
        self.assertEqual(response.json["page"], 2)
        self.assertEqual(response.json["total_pages"], 2)
        self.assertFalse(response.json["has_next"])
        self.assertEqual(response.json["items"][0]["id"], "2601.00020v1")
        upstream.assert_called_once()
        self.assertEqual(upstream.call_args.kwargs["params"]["start"], 20)
        self.assertEqual(
            upstream.call_args.kwargs["params"]["search_query"],
            'all:"machine" AND all:"learning"',
        )


if __name__ == "__main__":
    unittest.main()
