"""Consistent JSON errors for route validation and HTTP failures."""

from flask import jsonify


def error_response(code, message, status):
    return jsonify({"error": {"code": code, "message": message}}), status



def handle_http_error(error):
    return error_response(error.name.upper().replace(" ", "_"), error.description, error.code)
