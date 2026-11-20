"""The privacy boundary: what may go into a session folder or reach a page. Standard library only, so a probe that
runs in another Python (the network probe's mitmproxy addon) can load this file by its path."""

import re
from urllib.parse import unquote, urlsplit

LONGEST = 120
EMAIL = re.compile(r"[^\s/@:]+@[^\s/@:]+\.[A-Za-z]{2,}")
TOKEN = re.compile(r"[A-Za-z0-9_\-+=]{20,}|\d{6,}")
QUERY = re.compile(r"\?[^\s\"'<>]*")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def url_label(method, url):
    """"GET host/path", or "host/path" with no method: never the user, password, query, or fragment. A path part
    that looks like an id, a token, or an email address shows as :id or :email."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host and parts.port:
        host += f":{parts.port}"
    path = "/".join(part(segment) for segment in (parts.path or "/").split("/"))
    where = (host + path if host else f"{parts.scheme}:{path}")[:LONGEST]
    return f"{method} {where}" if method else where


def part(segment):
    segment = unquote(segment.split(";", 1)[0])
    if EMAIL.search(segment):
        return ":email"
    if segment.isdigit() or (len(segment) >= 6 and any(c.isdigit() for c in segment)) or len(segment) >= 24:
        return ":id"
    return segment


def text(s):
    """Free text, such as an error message, with no query string, email address, token, long number, or control
    character, cut to LONGEST."""
    s = CONTROL.sub(" ", str(s))
    s = QUERY.sub("", s)
    s = EMAIL.sub(":email", s)
    return TOKEN.sub(":id", s)[:LONGEST]
