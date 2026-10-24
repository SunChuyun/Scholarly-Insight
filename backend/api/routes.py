"""Public search and health endpoints."""

from flask import Blueprint, jsonify, request

from backend.api.errors import error_response
from backend.clients.arxiv import ArxivError, search_papers

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/health")
def health():
    """Report backend reachability without contacting external services."""
    response = jsonify({"status": "ok"})
    response.headers["Cache-Control"] = "no-store"
    return response


@api.get("/search")
def search():
    """Return up to 20 matching papers for a keyword query and page number."""
    query = " ".join(request.args.get("q", "").split())
    if not query or len(query) > 300:
        return error_response("INVALID_QUERY", "q must contain between 1 and 300 characters.", 400)

    page_text = request.args.get("page", "1")
    try:
        if not page_text.isascii() or not page_text.isdecimal():
            raise ValueError
        page = int(page_text)
        if page < 1:
            raise ValueError
    except ValueError:
        return error_response("INVALID_PAGE", "page must be a positive integer.", 400)

    try:
        return jsonify(search_papers(query, page))
    except ArxivError as exc:
        return error_response("UPSTREAM_ERROR", str(exc), exc.status_code)
