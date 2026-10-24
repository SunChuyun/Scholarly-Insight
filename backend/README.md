# Backend development guide

Internal setup, implementation notes, API behavior, and verification for the current Flask backend. See the [project README](../README.md) for the overall application and roadmap.

## Environment and startup

Create the `scholar` Conda environment using the [project quick start](../README.md#quick-start). From the repository root:

```bash
conda activate scholar
python -m pip install -r requirements.txt
python -m backend.app
```

The development server listens at `http://127.0.0.1:8000`; stop it with `Ctrl+C`. Run the module from the repository root, not from `backend/` or `backend/tests/`, so Python can resolve the `backend` package. Dependencies remain in the root requirements file.

## Implementation notes

| Module | Responsibility |
| --- | --- |
| [`__init__.py`](__init__.py) | `create_app()` configures Flask, CORS, the API Blueprint, and application-wide HTTP error handling. |
| [`app.py`](app.py) | Creates the application object and starts the development server when run as a module. |
| [`api/routes.py`](api/routes.py) | `search()` validates inputs and calls the arXiv client; `health()` reports reachability. |
| [`api/errors.py`](api/errors.py) | `error_response()` and `handle_http_error()` produce consistent JSON errors. |
| [`clients/arxiv.py`](clients/arxiv.py) | `search_papers()` builds queries, fetches a page, parses Atom/XML, and normalizes upstream failures. |

Keyword terms are combined with AND and ranked by arXiv relevance. Pagination uses `start = (page - 1) * 20`; only the requested page is fetched. The client serializes requests, spaces their starts by at least three seconds, and sets a 30-second HTTP timeout.

The request limiter is shared within one Python process. Multiple processes, instances, or future background jobs require coordinated upstream access. There is currently no database, authentication, cache, scheduler, or frontend implementation.

## API reference

### Search

```http
GET /api/search?q=transformer&page=1
```

| Parameter | Rules |
| --- | --- |
| `q` | Required; 1-300 characters after whitespace normalization. |
| `page` | Positive integer; defaults to 1. Page size is fixed at 20. |

A successful response contains `query`, `page`, `page_size`, `total`, `total_pages`, `has_previous`, `has_next`, and `items`. An empty search result is still HTTP 200, for example:

```json
{
  "query": "unmatched-example",
  "page": 1,
  "page_size": 20,
  "total": 0,
  "total_pages": 0,
  "has_previous": false,
  "has_next": false,
  "items": []
}
```

Each item contains `id`, `title`, `authors`, `abstract`, `submitted_at`, `updated_at`, `categories`, `abstract_url`, and `pdf_url`. Authors and categories are arrays; `pdf_url` may be `null`. IDs retain their arXiv version. `submitted_at` is the first arXiv submission time, not a journal publication date. Matching, ranking, and availability are controlled by arXiv.

Errors use this shape:

```json
{"error": {"code": "INVALID_PAGE", "message": "page must be a positive integer."}}
```

| Status | Meaning |
| --- | --- |
| 400 | Invalid keyword or page parameter. |
| 404 / 405 | Unknown route or unsupported method; also returned as JSON. |
| 502 | Upstream connection/HTTP failure or malformed upstream data. |
| 503 | arXiv rate limiting. |
| 504 | arXiv timeout. |

### Health

```http
GET /api/health
```

A reachable backend returns HTTP 200, `Cache-Control: no-store`, and `{"status": "ok"}`. This checks that the backend can respond; it does not contact arXiv, run automated tests, or prove that every feature works.

Both endpoints allow cross-origin GET requests, with OPTIONS preflight support. They are public and require no API key.

## Automated testing

Run the full suite from the repository root:

```bash
python -m unittest discover -s backend/tests -v
```

Run either area independently:

```bash
python -m unittest backend.tests.test_api -v
python -m unittest backend.tests.test_arxiv_client -v
```

Tests use synthetic feeds from [`tests/fixtures.py`](tests/fixtures.py). They do not start the development server, call the real arXiv API, or wait for the real request interval. API tests create a fresh application with `create_app()` for each test.

| Check | Code exercised | Logic and purpose |
| --- | --- | --- |
| Application wiring | `create_app()`, `search()`, `search_papers()` | Check independent Flask settings and run an HTTP request through the real client/parser with a mocked upstream response. |
| Inputs and HTTP responses | `search()`, `error_response()`, `handle_http_error()` | Check normalized keywords, page forwarding, invalid inputs, JSON fields, and 400/404/405/502/503/504 errors. |
| Reachability | `health()` | Check status, body, no-store caching, and independence from arXiv or a failed search. |
| Browser integration | `create_app()` CORS configuration | Check Origin headers and OPTIONS preflight for search and health. |
| Query and metadata | `search_papers()`, `_text()` | Check AND queries, escaping, relevance, parsed fields, whitespace, legacy IDs, and missing PDF links. |
| Pagination | `search_papers()` | Check 20-item offsets, last-page flags, distinct page items, and zero-result totals. |
| Upstream failures | `search_papers()` | Simulate timeouts, connection errors, HTTP 429, and invalid feeds; verify their mapped errors. |
| Request spacing | `search_papers()` | Use a simulated clock to verify the remaining wait needed between request starts. |

HTTP and integration checks are in [`tests/test_api.py`](tests/test_api.py); upstream-client checks are in [`tests/test_arxiv_client.py`](tests/test_arxiv_client.py). Automated tests are for development and future CI; they do not run on browser refresh.

## Manual verification

Start the server, then open these URLs in a browser:

| URL | Expected behavior |
| --- | --- |
| `http://127.0.0.1:8000/api/health` | HTTP 200 with `{"status": "ok"}`. |
| `http://127.0.0.1:8000/api/search?q=transformer&page=1` | A real arXiv search with up to 20 papers and pagination fields. |
| `http://127.0.0.1:8000/api/search?q=transformer&page=2` | The next result window. |
| `http://127.0.0.1:8000/api/search` | HTTP 400 with `INVALID_QUERY`. |
| `http://127.0.0.1:8000/api/search?q=transformer&page=0` | HTTP 400 with `INVALID_PAGE`. |

Real searches depend on arXiv availability; a healthy backend can still return an upstream error. After any future deployment, the same endpoint paths can be checked using the deployed base URL. The current command starts a development server; deployment configuration is deferred.
