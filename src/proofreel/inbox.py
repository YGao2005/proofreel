"""The review inbox: one local queue of review pages, and the way a decision gets back to the agent.

An item is one JSON file in ~/.proofreel/inbox. `add` queues a page. The person decides in the inbox page, which
a small server on 127.0.0.1 shows. `wait` and `check` read the decision from the file, so they need no server.
"""

import hmac
import http.server
import json
import mimetypes
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from importlib import resources
from pathlib import Path
from urllib.parse import unquote

from . import HOME, Problem, page, session

FOLDER = HOME / "inbox"
PORT = 8790
POLL = 1
MAX_BODY = 65536
RANGE = re.compile(r"bytes=(\d+)-(\d*)")
ASSETS = resources.files("proofreel")
APPROVE = "merge by your repo's rules"
VERDICTS = ("approve", "approve_next", "needs_work", "reject")


def url(port=PORT):
    return f"http://127.0.0.1:{port}"


def git(*args):
    try:
        done = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def here():
    """The repo and branch of the current folder."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    return {"repo": Path(common).parent.name if common else "", "branch": git("branch", "--show-current")}


def path_of(id):
    return FOLDER / f"{id}.json"


def load(id):
    if not re.fullmatch(r"[a-z0-9-]+", id) or not path_of(id).exists():
        raise Problem(f"No inbox item {id}. `proofreel inbox list` shows the items.")
    return json.loads(path_of(id).read_text())


def save(item):
    FOLDER.mkdir(parents=True, exist_ok=True)
    page.atomic(path_of(item["id"]), json.dumps(item))


def items():
    """Every item, oldest first."""
    found = [json.loads(p.read_text()) for p in FOLDER.glob("*.json")] if FOLDER.exists() else []
    return sorted(found, key=lambda item: item["added"])


def verdict_of(folder):
    """The verdict of the newest suite run (or newest run) in a review folder. None for a page that is not one."""
    runs = page.load_runs(folder)
    if not runs:
        return None
    newest = page.suite_of(runs[-1])
    verdicts = {r["verdict"] for r in runs if not newest or page.suite_of(r) == newest}
    return "problem" if "problem" in verdicts else "works" if "works" in verdicts else "shown"


def title_of(file):
    runs = page.load_runs(file.parent)
    return (runs[-1].get("suite") or runs[-1])["title"] if runs else file.stem if file.name != "index.html" else file.parent.name


def add(target, title=None, from_="", pr=None, on_approve=""):
    """Queue a review page (a review folder, or an HTML file). Returns the item."""
    file = Path(target).resolve()
    file = file / "index.html" if file.is_dir() else file
    if not file.is_file():
        raise Problem(f"{target} is not a review folder or an HTML page.")
    title = title or title_of(file)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "item"
    item = {"id": f"{slug}-{secrets.token_hex(2)}", "title": title, "page": str(file), "from": from_, "pr": pr,
            "commit": session.revision(), "on_approve": on_approve, "verdict": verdict_of(file.parent),
            "added": int(time.time()), **here()}
    save(item)
    return item


def message(item, verdict, text):
    """What the agent reads."""
    match verdict:
        case "approve": return f"Approved: {item['title']}. Then: {item['on_approve'] or APPROVE}."
        case "approve_next": return f"Approved: {item['title']}. Next mission: {text}"
        case "needs_work": return f"Needs work: {text}"
        case _: return f"Rejected: {text or 'no reason given'}. Close the branch."


def decide(id, verdict, text=""):
    """Record the decision of the person. Returns the item. Problem when it is not valid or already made."""
    item, text = load(id), text.strip()
    if verdict not in VERDICTS:
        raise Problem(f"Unknown decision {verdict}.")
    if item.get("decision"):
        raise Problem(f"{id} has a decision already.")
    if verdict in ("approve_next", "needs_work") and not text:
        raise Problem("This decision needs a text.")
    item = {**item, "decision": {"verdict": verdict, "text": message(item, verdict, text), "at": int(time.time())}}
    save(item)
    return item


def pick(item):
    """Mark a decision as read by the agent, and return its text."""
    if not item.get("picked"):
        save({**item, "picked": {"at": int(time.time())}})
    return item["decision"]["text"]


def wait(id, timeout=None):
    """The decision text of an item, once there is one. None when timeout seconds pass first."""
    end = None if timeout is None else time.time() + timeout
    while not (item := load(id)).get("decision"):
        if end is not None and time.time() >= end:
            return None
        time.sleep(POLL)
    return pick(item)


def check(only_here=False):
    """The decision texts that no agent has read yet (of this repo and branch with only_here)."""
    place = here()
    return [pick(i) for i in items() if i.get("decision") and not i.get("picked")
            and (not only_here or (i["repo"], i["branch"]) == (place["repo"], place["branch"]))]


def listing():
    return [f"{i['id']}  {'picked up' if i.get('picked') else 'decided' if i.get('decision') else 'waiting'}  "
            f"{i['title']}  {i['from']}" for i in items()]


def hosts():
    """The extra host names the person opened, one per line in the hosts file."""
    path = FOLDER / "hosts"
    return sorted(set(path.read_text().split())) if path.exists() else []


def set_hosts(names):
    """Replace the extra host names. An empty list closes them all. Problem for a name that is not a plain host."""
    names = sorted({n.strip().lower() for n in names if n.strip()})
    for name in names:
        if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", name):
            raise Problem(f"{name} is not a plain host name. Use the name only, like box.example.ts.net.")
    FOLDER.mkdir(parents=True, exist_ok=True)
    page.atomic(FOLDER / "hosts", "\n".join(names))
    return names


def token():
    """The secret of this install. The inbox page carries it, and a decision needs it."""
    path = FOLDER / "token"
    if not path.exists():
        FOLDER.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as out:
                out.write(secrets.token_hex(16))
    return path.read_text().strip()


def document(secret):
    """The inbox page: the design tokens and base rules of the review page, the inbox's own styles and markup, and its script."""
    tokens = ASSETS.joinpath("page.css").read_text().split("\n.wrap {", 1)[0]
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Review inbox</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="inbox-token" content="{secret}">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{tokens}</style>
{ASSETS.joinpath('inbox.html').read_text()}
<script>{ASSETS.joinpath('inbox.js').read_text()}</script>
"""


def public(item):
    return {**{k: v for k, v in item.items() if k != "page"}, "url": f"/item/{item['id']}/{Path(item['page']).name}"}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body=b"", kind="text/plain; charset=utf-8", **headers):
        body = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        for name, value in {"Content-Type": kind, "Content-Length": len(body), "X-Content-Type-Options": "nosniff",
                            "Cache-Control": "no-store", **headers}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def reply(self, status, data):
        self.send(status, json.dumps(data), "application/json")

    def local(self):
        """Only a request that names this server as its host: a page on another name cannot reach it."""
        port = self.server.server_port
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{port}", f"localhost:{port}") or re.fullmatch(r"(.+?)(:\d+)?", host)[1] in self.server.hosts

    def origin_ok(self):
        port = self.server.server_port
        origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        origins |= {f"{scheme}://{h}" for h in self.server.hosts for scheme in ("http", "https")}
        return (self.headers.get("Origin") or "").lower() in origins

    def do_GET(self):
        if not self.local():
            return self.send(403, "Wrong host.")
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self.send(200, document(self.server.secret), "text/html; charset=utf-8")
        if path == "/items":
            return self.reply(200, [public(i) for i in items()])
        if match := re.fullmatch(r"/item/([a-z0-9-]+)/(.+)", path):
            return self.serve_file(*match.groups())
        self.send(404, "Not found.")

    def serve_file(self, id, name):
        try:
            folder = Path(load(id)["page"]).parent.resolve()
        except Problem:
            return self.send(404, "Not found.")
        file = (folder / unquote(name)).resolve()
        if not file.is_relative_to(folder) or not file.is_file():
            return self.send(404, "Not found.")
        size, start, end, status = file.stat().st_size, 0, file.stat().st_size - 1, 200
        if ranged := RANGE.fullmatch(self.headers.get("Range", "")):
            start, end, status = int(ranged[1]), min(int(ranged[2] or end), end), 206
            if start > end:
                return self.send(416, "", **{"Content-Range": f"bytes */{size}"})
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.send_response(status)
        for header, value in {"Content-Type": kind, "Content-Length": end - start + 1, "Accept-Ranges": "bytes",
                              "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox allow-scripts",
                              **({"Content-Range": f"bytes {start}-{end}/{size}"} if status == 206 else {})}.items():
            self.send_header(header, value)
        self.end_headers()
        try:
            with open(file, "rb") as source:
                source.seek(start)
                left = end - start + 1
                while left and (chunk := source.read(min(left, 1 << 16))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self.local() or self.path != "/decide":
            return self.send(404, "Not found.")
        if not self.origin_ok() or not hmac.compare_digest(self.headers.get("X-Inbox-Token", ""), self.server.secret):
            return self.reply(403, {"error": "Not allowed."})
        try:
            size = int(self.headers.get("Content-Length", ""))
            body = json.loads(self.rfile.read(size)) if 0 < size <= MAX_BODY else {}
            with self.server.lock:
                item = decide(body["id"], body["verdict"], str(body.get("text", "")))
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"error": "Bad request."})
        except Problem as problem:
            return self.reply(409, {"error": str(problem)})
        self.reply(200, public(item))


def server(port=PORT):
    """The inbox server, bound to this machine only. Problem when the port is taken."""
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        raise Problem(f"The inbox port {port} is in use ({error.strerror}). Is the inbox running? `proofreel inbox stop` ends it.") from None
    httpd.secret, httpd.lock, httpd.daemon_threads, httpd.hosts = token(), threading.Lock(), True, hosts()
    return httpd


def serve(also=None):
    """Run the inbox server. also (a list of host names) replaces the extra hosts and restarts a running server."""
    if also is not None:
        set_hosts(also)
        if stop():
            for _ in range(50):
                if not running():
                    break
                time.sleep(0.1)
    httpd = server()
    if httpd.hosts:
        print(f"Also open to: {', '.join(httpd.hosts)}", flush=True)
    (FOLDER / "server.pid").write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=httpd.shutdown).start())
    try:
        httpd.serve_forever()
    finally:
        (FOLDER / "server.pid").unlink(missing_ok=True)


def running(port=PORT):
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def ensure_server():
    """Start the inbox server, detached, when it does not run."""
    if running():
        return
    FOLDER.mkdir(parents=True, exist_ok=True)
    with open(FOLDER / "server.log", "a") as log:
        subprocess.Popen([sys.executable, "-m", "proofreel.inbox"], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
    for _ in range(50):
        if running():
            return
        time.sleep(0.1)
    raise Problem(f"The inbox server did not start. See {FOLDER / 'server.log'}.")


def stop():
    """End the inbox server. Returns False when it did not run."""
    pidfile = FOLDER / "server.pid"
    if not pidfile.exists():
        return False
    try:
        os.kill(int(pidfile.read_text()), signal.SIGTERM)
    except ProcessLookupError:
        pidfile.unlink()
        return False
    return True


if __name__ == "__main__":
    try:
        serve()
    except Problem as problem:
        sys.exit(f"proofreel: {problem}")
