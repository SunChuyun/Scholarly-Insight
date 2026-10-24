"""HTTP interface for the midterm paper search backend."""

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from backend.arxiv_client import ArxivError, search_papers

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False
CORS(app, resources={r"/api/(search|health)$": {"origins": "*", "methods": ["GET"]}})


def error_response(code, message, status):
    return jsonify({"error": {"code": code, "message": message}}), status


@app.get("/api/health")
def health():
    """Report backend reachability without contacting external services."""
    response = jsonify({"status": "ok"})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/search")
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


@app.errorhandler(HTTPException)
def handle_http_error(error):
    return error_response(error.name.upper().replace(" ", "_"), error.description, error.code)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
