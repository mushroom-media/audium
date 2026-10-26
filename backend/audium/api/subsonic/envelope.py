"""The subsonic-response envelope, as JSON or XML, and the protocol's error codes.

Handlers return plain dicts; XML is derived from the same dicts (scalars become attributes,
dicts and lists of dicts become child elements, a "value" key becomes the element text), so
there is only one model to maintain.
"""

import json
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi.responses import Response

from audium import __version__

API_VERSION = "1.16.1"
XML_NAMESPACE = "http://subsonic.org/restapi"

# Error codes from the Subsonic spec (plus the OpenSubsonic apiKey ones).
GENERIC = 0
MISSING_PARAMETER = 10
WRONG_CREDENTIALS = 40
TOKEN_AUTH_NOT_SUPPORTED = 41
AUTH_MECHANISM_NOT_SUPPORTED = 42
CONFLICTING_AUTH = 43
INVALID_API_KEY = 44
NOT_AUTHORIZED = 50
NOT_FOUND = 70


class SubsonicError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def ok(payload: dict, fmt: str) -> Response:
    return _render({"status": "ok", **_header(), **payload}, fmt)


def failed(error: SubsonicError, fmt: str) -> Response:
    # Always HTTP 200: Subsonic clients read the status from the body.
    return _render({"status": "failed", **_header(), "error": {"code": error.code, "message": error.message}}, fmt)


def _header() -> dict:
    return {"version": API_VERSION, "type": "audium", "serverVersion": __version__, "openSubsonic": True}


def _render(body: dict, fmt: str) -> Response:
    if fmt == "json":
        return Response(json.dumps({"subsonic-response": body}, ensure_ascii=False), media_type="application/json")
    root = Element("subsonic-response", xmlns=XML_NAMESPACE)
    _fill(root, body)
    return Response(tostring(root, encoding="utf-8", xml_declaration=True), media_type="application/xml")


def _fill(el: Element, data: dict) -> None:
    for key, value in data.items():
        if value is None:
            continue
        if key == "value":
            el.text = _scalar(value)
        elif isinstance(value, dict):
            _fill(SubElement(el, key), value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _fill(SubElement(el, key), item)
                else:
                    SubElement(el, key).text = _scalar(item)
        else:
            el.set(key, _scalar(value))


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
