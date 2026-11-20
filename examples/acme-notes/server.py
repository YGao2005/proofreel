import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).parent / "static"
NOTES = [{"id": 1, "title": "Welcome", "body": "Your first note in Acme Notes."},
         {"id": 2, "title": "Groceries", "body": "Milk, eggs, and bread."}]


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/notes":
            return self.send(200, NOTES)
        if url.path == "/api/tags":
            if os.environ.get("BROKEN") == "1":
                return self.send(500, {"error": "tags are down"})
            return self.send(200, ["work", "home"])
        if url.path == "/api/search":
            time.sleep(int(os.environ.get("SLOW_SEARCH_MS", "0")) / 1000)
            q = parse_qs(url.query).get("q", [""])[0].lower()
            return self.send(200, [n for n in NOTES if q in (n["title"] + n["body"]).lower()])
        name = {"/": "index.html"}.get(url.path, url.path.lstrip("/"))
        page = STATIC / name
        if page.is_file() and page.parent == STATIC:
            return self.send(200, page.read_bytes(), "text/html" if name.endswith(".html") else "text/javascript")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/notes":
            return self.send(404, {"error": "not found"})
        note = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        note = {"id": len(NOTES) + 1, "title": note.get("title", ""), "body": note.get("body", "")}
        NOTES.append(note)
        self.send(201, note)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8791"))
    print(f"Acme Notes on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
