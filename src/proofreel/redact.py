"""The privacy boundary: the part of a URL that may go into a session folder. Standard library only."""

from urllib.parse import urlsplit

LONGEST = 120


def url_label(method, url):
    """"GET host/path", or "host/path" with no method: never the user, password, query, or fragment."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host and parts.port:
        host += f":{parts.port}"
    where = (host + (parts.path or "/") if host else f"{parts.scheme}:{parts.path}")[:LONGEST]
    return f"{method} {where}" if method else where
