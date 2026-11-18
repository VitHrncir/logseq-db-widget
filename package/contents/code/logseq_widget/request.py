"""Reading a request from the widget, and checking its fields."""

import json
import urllib.parse

from .errors import HelperError


REQUEST_ENV = "LOGSEQ_WIDGET_REQUEST"


def decode_request(arg):
    text = arg if arg.lstrip().startswith("{") else urllib.parse.unquote(arg)
    req = json.loads(text)
    if not isinstance(req, dict):
        raise ValueError("request must be a JSON object")
    return req


def require_text(req, key="text"):
    text = req.get(key)
    if not isinstance(text, str) or not text.strip():
        raise HelperError("Nothing to add.")
    return text.strip()


def require_id(req):
    value = req.get("id")
    if isinstance(value, bool) or not isinstance(value, int):
        raise HelperError("Missing or invalid block id.")
    return value
