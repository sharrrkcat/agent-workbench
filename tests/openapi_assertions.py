"""Validate real workbench HTTP responses against the served contract."""

import json

from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator, FormatChecker
from starlette.routing import Match


def response_validator(document, path, method, status):
    responses = document["paths"][path][method]["responses"]
    response = responses.get(str(status), responses.get("default"))
    assert response is not None, f"Undocumented HTTP status: {method.upper()} {path} -> {status}"
    content = response.get("content", {})
    assert "application/json" in content, f"Undocumented JSON response: {method.upper()} {path} -> {status}"
    schema = content["application/json"]["schema"]
    return Draft202012Validator({**schema, "components": document["components"]}, format_checker=FormatChecker())


def validate_workbench_response(app, response, validators):
    if not hasattr(getattr(app, "state", None), "runtime_state"):
        return None
    media_type = response.headers.get("content-type", "").split(";", 1)[0]
    if media_type not in {"application/json", "text/event-stream"}:
        return None
    scope = {"type": "http", "method": response.request.method, "path": response.request.url.path, "root_path": ""}
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema or route.matches(scope)[0] != Match.FULL:
            continue
        # The attachment endpoint can serve JSON *files*, whose bytes are not API JSON.
        if route.path == "/api/attachments/{attachment_id:path}" and response.status_code < 400:
            return None
        key = (route.path_format, scope["method"].lower(), response.status_code)
        if media_type == "text/event-stream":
            document = app.openapi()
            media = document["paths"][key[0]][key[1]]["responses"][str(key[2])]["content"][media_type]
            assert response.text.endswith("data: [DONE]\n\n")
            assert response.text.count("data: [DONE]") == 1
            for line in response.text.splitlines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    payload = json.loads(line[6:])
                    schema = media["x-event-schemas"]["error" if "error" in payload else "chunk"]
                    Draft202012Validator({**schema, "components": document["components"]}).validate(payload)
            return key
        cache_key = (id(app), *key)
        if cache_key not in validators:
            validators[cache_key] = response_validator(app.openapi(), *key)
        errors = sorted(validators[cache_key].iter_errors(response.json()), key=lambda error: str(error.path))
        assert not errors, f"{key}: " + "; ".join(error.message for error in errors)
        return key
    return None
