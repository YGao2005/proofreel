"""What a web run changes in its page for one recording.

The recorder holds the change on its own DevTools connection: Chrome undoes it when that connection ends, so a
recorder that stops or dies leaves the page as it was. Each change is a pair of DevTools commands: one that sets it,
one that clears it. A page sees `prefers-color-scheme: light` unless a condition says dark, so a recording does not
depend on the appearance setting of the host. The commands are saved in session.json (`emulate`), and the recorder runs them before its first frame, so
`start` returns when they hold.

The conditions that work on the web (`os = ["web"]` in their manifest) name their change here, one function each. The
function takes the condition's values and returns what to change: `media` (a list of (feature, value)), `device`
(the screen of a phone), `agent` (the user agent), and `network` (offline, latency in ms, bytes a second).
"""

import re

from . import Problem

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/17.5 Mobile/15E148 Safari/604.1")
UNITS = {"": 1000, "kbit": 1000, "mbit": 1_000_000}


def phone(values):
    return {"device": {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True}, "agent": IPHONE}


def dark(values):
    return {"media": [("prefers-color-scheme", "dark")]}


def offline(values):
    return {"network": {"offline": True}}


def slow_network(values):
    """The profile's round-trip latency and rate. DevTools has no jitter, and the page's own requests only are shaped."""
    latency = re.fullmatch(r"([\d.]+)ms", values["latency"])
    rate = re.fullmatch(r"([\d.]+)(kbit|mbit)", values["rate"])
    if not latency or not (rate or values["rate"] == "0"):
        raise Problem(f"slow-network on the web takes latency such as 300ms and rate such as 1mbit, not "
                      f"{values['latency']!r} and {values['rate']!r}.")
    bytes_a_second = float(rate[1]) * UNITS[rate[2]] / 8 if rate else -1
    return {"network": {"offline": False, "latency": float(latency[1]), "downloadThroughput": bytes_a_second,
                        "uploadThroughput": bytes_a_second}}


WEB = {"phone": phone, "dark": dark, "offline": offline, "slow-network": slow_network}


def commands(reduced_motion, records=()):
    """The (set, clear) pairs of DevTools commands for a recording: reduced motion, and each web condition."""
    changes = [{"media": [("prefers-color-scheme", "light"), *([("prefers-reduced-motion", "reduce")] if reduced_motion else [])]}]
    for record in records:
        if record["name"] not in WEB:
            raise Problem(f"Condition {record['name']} has no change for the web.")
        changes.append(WEB[record["name"]](record["values"]))
    media = list(dict(pair for change in changes for pair in change.get("media", [])).items())
    network = {}
    for change in changes:
        network.update(change.get("network", {}))
    pairs = []
    if media:
        pairs.append([["Emulation.setEmulatedMedia", {"features": [{"name": n, "value": v} for n, v in media]}],
                      ["Emulation.setEmulatedMedia", {"features": []}]])
    for change in changes:
        if device := change.get("device"):
            pairs.append([["Emulation.setDeviceMetricsOverride", device], ["Emulation.clearDeviceMetricsOverride", {}]])
            pairs.append([["Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}],
                          ["Emulation.setTouchEmulationEnabled", {"enabled": False}]])
        if agent := change.get("agent"):
            pairs.append([["Emulation.setUserAgentOverride", {"userAgent": agent}],
                          ["Emulation.setUserAgentOverride", {"userAgent": ""}]])
    if network:
        pairs.append([["Network.enable", {}], ["Network.disable", {}]])
        pairs.append([["Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1,
                                                            "uploadThroughput": -1, **network}],
                      ["Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1,
                                                            "uploadThroughput": -1}]])
    return pairs
