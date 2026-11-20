"""The network probe's mitmproxy addon: one span line on stdout for each request that the run VM makes.

A span keeps the host, the method, the path through redact.url_label, the status, the size, and the times. It never
keeps a query string, a header value, or a body. Only the run VM (PROOFREEL_GUEST_IP) may use the proxy.
"""

import importlib.util
import json
import os
import sys
import time

spec = importlib.util.spec_from_file_location("proofreel_redact", os.environ["PROOFREEL_REDACT"])
redact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redact)


def seconds(value):
    return round(max(0.0, value), 4)


class Spans:
    def __init__(self, guest_ip, host_for_guest, bind, out=sys.stdout):
        self.guest_ip, self.host_for_guest, self.bind, self.out = guest_ip, host_for_guest, bind, out
        self.connections = set()

    def say(self, line):
        print(json.dumps(line), file=self.out, flush=True)

    def running(self):
        self.say({"ready": True})

    def client_connected(self, client):
        if client.peername[0] != self.guest_ip:
            client.error = "Only the run VM may use this proxy."

    def http_connect(self, flow):
        self.route(flow)

    def requestheaders(self, flow):
        self.route(flow)

    def route(self, flow):
        # WHY: the guest reaches the host at an address (QEMU's 10.0.2.2) that only the guest has.
        if flow.request.host == self.host_for_guest != self.bind:
            header = flow.request.host_header
            flow.request.host = self.bind
            flow.request.host_header = header

    def response(self, flow):
        self.span(flow)

    def error(self, flow):
        if flow.response is None:
            self.span(flow)

    def tls_failed_client(self, data):
        host = data.conn.sni or "unknown"
        self.say({"m": f"net/{redact.text(host)[:100]}", "d": 0, "ok": False,
                  "label": "TLS: the client did not trust the proxy's certificate"})

    def span(self, flow):
        request, response, server = flow.request, flow.response, flow.server_conn
        if request.method == "CONNECT" or request.pretty_host == "mitm.it":
            return
        end = response.timestamp_end if response and response.timestamp_end else time.time()
        start = request.timestamp_start
        phases = {}
        if server.id not in self.connections and server.timestamp_start and server.timestamp_tcp_setup:
            self.connections.add(server.id)
            start = min(start, server.timestamp_start)
            phases["connect"] = seconds(server.timestamp_tcp_setup - server.timestamp_start)
            ready = server.timestamp_tcp_setup
            if server.timestamp_tls_setup:
                phases["tls"] = seconds(server.timestamp_tls_setup - server.timestamp_tcp_setup)
                ready = server.timestamp_tls_setup
        else:
            ready = start
        line = {"m": f"net/{redact.text(request.pretty_host.lower())[:100]}", "t": round(end, 4),
                "d": seconds(end - start), "label": redact.url_label(request.method, request.pretty_url)}
        if response:
            phases["wait"] = seconds(response.timestamp_start - max(ready, request.timestamp_end or start))
            phases["receive"] = seconds(end - response.timestamp_start)
            line.update(ok=response.status_code < 400, phases=phases,
                        n={"status": response.status_code, "size": len(response.raw_content or b"")})
        else:
            line.update(ok=False, phases=phases, n={"error": redact.text(flow.error.msg if flow.error else "no answer")})
        self.say(line)


addons = [Spans(os.environ.get("PROOFREEL_GUEST_IP", "127.0.0.1"), os.environ.get("PROOFREEL_HOST_FOR_GUEST", ""),
                os.environ.get("PROOFREEL_BIND", "127.0.0.1"))]
