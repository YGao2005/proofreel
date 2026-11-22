"""Page performance from a Chromium, over its DevTools port: each tab's Performance.getMetrics once a second,
LCP, CLS, and INP, long animation frames, and the page's own User Timing marks and measures. With requests on (the
network probe on `web` runs this with requests and no vitals), each tab's Network events make one span line for each
request.

The probe attaches to each tab and adds observe.js to each document. Its PerformanceObservers call a binding with what
they saw and the page's clock at that moment, so each entry's t is on this probe's clock. A page URL goes into a line
only as redact.url_label: host and path.
"""

import json
import os
import time
import urllib.request
from pathlib import Path

from proofreel.redact import request_span, seconds as clamp, url_label

OBSERVE = (Path(__file__).parent / "observe.js").read_text()
BINDING = "__proofreel"
NAMES = 40
RATES = {"LayoutCount": "web/layouts", "RecalcStyleCount": "web/style-recalcs"}


def seconds(ms):
    return round(ms / 1000, 4)


def web(url):
    return url.startswith(("http:", "https:", "file:"))


class Requests:
    """The requests in flight in each tab. A span line is made when a request finishes, fails, or is redirected."""

    def __init__(self):
        self.flying = {}

    def feed(self, method, params, session, now):
        key = (session, params.get("requestId"))
        if method == "Network.requestWillBeSent":
            lines = self.end(key, params["timestamp"], now, redirect=params.get("redirectResponse"))
            if params["request"]["url"].startswith(("http:", "https:")):
                self.flying[key] = {"method": params["request"]["method"], "url": params["request"]["url"],
                                    "start": params["timestamp"], "response": None}
            return lines
        if key not in self.flying:
            return []
        if method == "Network.responseReceived":
            self.flying[key]["response"] = params["response"]
        elif method == "Network.loadingFinished":
            return self.end(key, params["timestamp"], now, size=params.get("encodedDataLength", 0))
        elif method == "Network.loadingFailed":
            if params.get("canceled"):
                del self.flying[key]
                return []
            return self.end(key, params["timestamp"], now, error=params.get("errorText", "").removeprefix("net::").removeprefix("ERR_").replace("_", " ").lower())
        return []

    def end(self, key, at, now, redirect=None, size=0, error=None):
        request = self.flying.pop(key, None)
        response = redirect or (request or {}).get("response")
        if not request:
            return []
        phases = self.phases(response["timing"], request["start"], at) if response and response.get("timing") else {}
        status = response["status"] if response and not error else None
        return [request_span(request["method"], request["url"], now, at - request["start"], status, size, phases,
                             error)]

    @staticmethod
    def phases(timing, start, at):
        """connect, tls, wait, and receive of a response's timing. Chrome gives ms from timing["requestTime"] (s), and
        -1 for a step that did not happen: a reused connection has no connect."""
        phases, step = {}, lambda name: timing[name] / 1000 if timing.get(name, -1) >= 0 else None
        first = next((t for t in (step("dnsStart"), step("connectStart")) if t is not None), None)
        if first is not None and step("connectEnd") is not None:
            secure = step("sslStart")
            phases["connect"] = clamp((secure if secure is not None else step("connectEnd")) - first)
            if secure is not None and step("sslEnd") is not None:
                phases["tls"] = clamp(step("sslEnd") - secure)
        if step("sendEnd") is not None and step("receiveHeadersEnd") is not None:
            phases["wait"] = clamp(step("receiveHeadersEnd") - step("sendEnd"))
            phases["receive"] = clamp(at - (timing["requestTime"] + step("receiveHeadersEnd")))
        return phases


class Browser:
    """One DevTools connection: the tabs it attached to, and the lines their messages make. Commands that a message
    calls for wait in outbox."""

    def __init__(self, since, vitals=True, requests=False):
        self.since, self.outbox, self.tabs, self.named, self.sent = since, [], {}, set(), 0
        self.vitals, self.requests = vitals, Requests() if requests else None
        self.send("Target.setDiscoverTargets", {"discover": True})

    def send(self, method, params=None, session=None):
        self.sent += 1
        self.outbox.append(json.dumps({"id": self.sent, "method": method, "params": params or {},
                                       **({"sessionId": session} if session else {})}))

    def tick(self):
        """Read the metrics of each tab that shows a web page."""
        for session, tab in self.tabs.items():
            if self.vitals and tab["shown"] and web(tab["url"]):
                self.send("Performance.getMetrics", session=session)

    def feed(self, message, now):
        """The lines that one message makes, at now on the probe's clock."""
        method, params, session = message.get("method"), message.get("params", {}), message.get("sessionId")
        if method == "Target.targetCreated" and params["targetInfo"]["type"] == "page":
            self.send("Target.attachToTarget", {"targetId": params["targetInfo"]["targetId"], "flatten": True})
        elif method == "Target.attachedToTarget":
            info, session = params["targetInfo"], params["sessionId"]
            self.tabs[session] = {"target": info["targetId"], "url": info["url"], "counts": None, "shown": False}
            steps = [("Performance.enable", {}), ("Runtime.addBinding", {"name": BINDING}),
                     ("Page.addScriptToEvaluateOnNewDocument", {"source": OBSERVE}),
                     ("Runtime.evaluate", {"expression": OBSERVE})] if self.vitals else []
            for step, args in steps + ([("Network.enable", {})] if self.requests else []):
                self.send(step, args, session)
        elif method == "Target.targetInfoChanged":
            for tab in self.tabs.values():
                if tab["target"] == params["targetInfo"]["targetId"]:
                    tab["url"] = params["targetInfo"]["url"]
        elif method == "Target.detachedFromTarget":
            self.tabs.pop(params["sessionId"], None)
        elif self.requests and (method or "").startswith("Network.") and session in self.tabs:
            return self.requests.feed(method, params, session, now)
        elif method == "Runtime.bindingCalled" and params.get("name") == BINDING and session in self.tabs:
            # WHY: the page's own scripts can call the binding too.
            try:
                return self.entries(self.tabs[session], json.loads(params["payload"]), now)
            except (ValueError, KeyError, TypeError, AttributeError):
                return []
        elif "metrics" in message.get("result", {}) and session in self.tabs:
            return self.metrics(self.tabs[session], message["result"]["metrics"], now)
        return []

    def entries(self, tab, seen, now):
        """observe.js's entries. at is page time in ms, so an entry ended (seen["now"] - at) ms before now. Entries
        from before the probe started are not kept."""
        lines, label = [], url_label(None, seen["url"])
        for e in seen["found"]:
            kind, t = e["k"], round(now - (seen["now"] - e["at"]) / 1000, 4)
            if kind == "shown":
                tab["shown"] = e["v"]
                continue
            if t < self.since:
                continue
            if kind in ("lcp", "inp", "cls"):
                line = {"m": f"web/{kind}", "v": round(e["v"], 4 if kind == "cls" else 1)}
            elif kind == "interaction":
                line = {"m": "web/interaction", "d": seconds(e["d"]), "event": e["name"][:40]}
            elif kind == "frame":
                script = e["name"][:200]
                line = {"m": "web/long-frame", "d": seconds(e["d"]), "blocking": seconds(e["blocking"]),
                        "script": url_label(None, script) if "://" in script else script}
            elif kind in ("mark", "measure"):
                line = {"m": self.series(f"web/{kind}", e["name"]), "name": e["name"][:200],
                        **({"d": seconds(e["d"])} if kind == "measure" else {})}
            else:
                continue
            lines.append({**line, "t": t, "label": label})
        return lines

    def series(self, group, name):
        """A series for each User Timing name, up to NAMES of them; the rest share <group>/other."""
        m = f"{group}/{name[:80] or '(blank)'}"
        if m not in self.named and len(self.named) < NAMES:
            self.named.add(m)
        return m if m in self.named else f"{group}/other"

    def metrics(self, tab, metrics, now):
        """The heap and node count, and layouts and style recalcs a second since the last read of the same document."""
        values = {item["name"]: item["value"] for item in metrics}
        before, tab["counts"] = tab["counts"], values
        lines = [{"m": "web/heap", "v": round(values["JSHeapUsedSize"] / 1e6, 2)}, {"m": "web/nodes", "v": values["Nodes"]}]
        took = before and values["Timestamp"] - before["Timestamp"]
        if took and all(values[name] >= before[name] for name in RATES):
            lines += [{"m": m, "v": round((values[name] - before[name]) / took, 1)} for name, m in RATES.items()]
        return [{**line, "t": round(now, 4), "label": url_label(None, tab["url"])} for line in lines]


def say(line):
    print(json.dumps(line), flush=True)


def version(port):
    """(the browser's DevTools WebSocket URL on the port, its version), or None while it does not listen."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as answer:
            found = json.load(answer)
        return f"ws://127.0.0.1:{port}/devtools/{found['webSocketDebuggerUrl'].split('/devtools/', 1)[1]}", found["Browser"]
    except (OSError, ValueError, KeyError, IndexError):
        return None


def main(vitals=True, requests=False):
    """Read the browser's DevTools port, PROOFREEL_TUNNEL, until the probe is stopped."""
    port = os.environ.get("PROOFREEL_TUNNEL")
    if not port:
        return say({"unavailable": "This probe needs a run VM: proofreel vm up <state>."})
    try:
        import websocket
    except ImportError:
        return say({"unavailable": "The browser probe needs websocket-client: pip install websocket-client"})
    since, waited = time.monotonic(), False
    while True:
        found = version(port)
        try:
            connection = websocket.create_connection(found[0], timeout=5, suppress_origin=True) if found else None
        except (OSError, websocket.WebSocketException):
            connection = None
        if not connection:
            if not waited:
                say({"meta": {"waiting": "for the browser's DevTools port; open pages with open or browse"}})
                waited = True
            time.sleep(1)
            continue
        say({"meta": {"browser": found[1]}})
        say({"ready": True})
        connection.settimeout(0.25)
        browser, due = Browser(since, vitals, requests), 0.0
        try:
            while True:
                if time.monotonic() >= due:
                    browser.tick()
                    due = time.monotonic() + 1
                for command in browser.outbox:
                    connection.send(command)
                browser.outbox.clear()
                try:
                    raw = connection.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                for line in browser.feed(json.loads(raw), time.monotonic()):
                    say(line)
        except (OSError, ValueError, websocket.WebSocketException):
            connection.close()
            time.sleep(1)


if __name__ == "__main__":
    main()
