"""Drive a headless Chrome over the DevTools protocol as a person drives a screen, and read its text from the page.

The address of a browser screen is `cdp://host:port`. Coordinates are CSS pixels of the viewport (1440x900, device
scale 1). The screen is the first tab. `WebScreen` has the interface of screen.Screen; `lines()` gives the visible
text lines with boxes in the shape that OCR gives (see screen.read_text), taken from the page, so reading text is exact.
"""

import base64
import http.client
import json
import time
import urllib.request
from pathlib import Path

import websocket

from . import Problem
from .screen import Keyboard

SCHEME = "cdp://"
LINES = (Path(__file__).parent / "lines.js").read_text()
BUTTONS = {1: ("left", 1), 2: ("middle", 4), 3: ("right", 2)}
MODIFIERS = {"alt": 1, "option": 1, "ctrl": 2, "control": 2, "meta": 4, "command": 4, "cmd": 4, "shift": 8}
KEYS = {"enter": ("Enter", "Enter", 13), "return": ("Enter", "Enter", 13), "tab": ("Tab", "Tab", 9),
        "escape": ("Escape", "Escape", 27), "esc": ("Escape", "Escape", 27), "backspace": ("Backspace", "Backspace", 8),
        "delete": ("Delete", "Delete", 46), "space": (" ", "Space", 32), "up": ("ArrowUp", "ArrowUp", 38),
        "down": ("ArrowDown", "ArrowDown", 40), "left": ("ArrowLeft", "ArrowLeft", 37),
        "right": ("ArrowRight", "ArrowRight", 39), "home": ("Home", "Home", 36), "end": ("End", "End", 35),
        "pageup": ("PageUp", "PageUp", 33), "pagedown": ("PageDown", "PageDown", 34), "shift": ("Shift", "ShiftLeft", 16),
        "ctrl": ("Control", "ControlLeft", 17), "control": ("Control", "ControlLeft", 17), "alt": ("Alt", "AltLeft", 18),
        "option": ("Alt", "AltLeft", 18), "meta": ("Meta", "MetaLeft", 91), "command": ("Meta", "MetaLeft", 91),
        **{f"f{n}": (f"F{n}", f"F{n}", 111 + n) for n in range(1, 13)}}
EDITS = {"a": "selectAll", "c": "copy", "x": "cut", "v": "paste", "z": "undo"}


def keystroke(name):
    """(modifier bits, key, code, virtual key code, text) of a key or a combo such as command-a."""
    parts = name.split("-") if name != "-" else ["-"]
    last, bits = parts[-1].lower() if len(parts[-1]) > 1 else parts[-1], 0
    for part in parts[:-1]:
        if part.lower() not in MODIFIERS:
            raise Problem(f"Unknown key {part!r} in {name!r}. Modifiers: {', '.join(MODIFIERS)}.")
        bits |= MODIFIERS[part.lower()]
    if last in KEYS:
        key, code, vk = KEYS[last]
        return bits, key, code, vk, " " if last == "space" else "\r" if key == "Enter" else ""
    if len(last) != 1:
        raise Problem(f"Unknown key {last!r}. Use a letter, a symbol, or one of: {', '.join(KEYS)}.")
    letter = last.isalpha() and last.isascii()
    key = last.upper() if letter and bits & 8 else last
    return bits, key, f"Key{last.upper()}" if letter else "", ord(last.upper()) if last.isalnum() else 0, \
        "" if bits & 7 else key


class WebScreen(Keyboard):
    def __init__(self, address, password=None, keys=None):
        self.address, self.keys, self.sent, self.events = address, keys or {}, 0, []

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.socket.close()

    def connect(self):
        host = self.address.removeprefix(SCHEME)
        try:
            with urllib.request.urlopen(f"http://{host}/json/list", timeout=5) as answer:
                tabs = [tab for tab in json.load(answer) if tab["type"] == "page"]
            if not tabs:
                raise Problem(f"The browser at {self.address} has no open tab.")
            self.socket = websocket.create_connection(tabs[0]["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        except (OSError, ValueError, http.client.HTTPException, websocket.WebSocketException) as error:
            raise Problem(f"The browser at {self.address} did not answer ({error!r}). Check that it runs: "
                          f"proofreel vm up <state>.") from None

    def reconnect(self):
        self.socket.close()
        self.connect()

    def call(self, method, **params):
        self.sent += 1
        try:
            self.socket.send(json.dumps({"id": self.sent, "method": method, "params": params}))
            while (message := json.loads(self.socket.recv())).get("id") != self.sent:
                if "method" in message:
                    self.events.append(message)
        except (OSError, websocket.WebSocketException) as error:
            raise Problem(f"The browser at {self.address} stopped answering ({error!r}).") from None
        if "error" in message:
            raise Problem(f"The browser refused {method}: {message['error']['message']}.")
        return message["result"]

    def event(self, name, seconds):
        """The next event with this name, from the ones already received, then from the browser. Problem on time out."""
        end = time.time() + seconds
        while True:
            for message in self.events:
                if message["method"] == name:
                    self.events.remove(message)
                    return message["params"]
            if not self.next_event(end - time.time()):
                raise Problem(f"{name} did not come in {seconds:g} s.")

    def next_event(self, seconds):
        """Wait up to seconds for one more message, and keep it if it is an event. False when none came."""
        self.socket.settimeout(max(seconds, 0.01))
        try:
            message = json.loads(self.socket.recv())
        except websocket.WebSocketTimeoutException:
            return False
        except (OSError, websocket.WebSocketException) as problem:
            raise Problem(f"The browser at {self.address} stopped answering ({problem!r}).") from None
        finally:
            self.socket.settimeout(30)
        if "method" in message:
            self.events.append(message)
        return True

    def open(self, url, timeout=30):
        """Go to the url in the tab, and wait for its load event. Returns (start, end)."""
        self.call("Page.enable")
        self.events.clear()
        started = time.time()
        result = self.call("Page.navigate", url=url)
        if "errorText" in result:
            raise Problem(f"The browser could not open {url}: {result['errorText']}.")
        if "loaderId" in result:
            self.event("Page.loadEventFired", timeout)
        return started, time.time()

    def mouse(self, kind, x, y, button=1, count=0, held=0):
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=BUTTONS[button][0] if held or count else "none",
                  clickCount=count, buttons=held)

    def move(self, x, y):
        self.mouse("mouseMoved", x, y)
        time.sleep(0.1)
        return time.time(), None

    def click(self, x, y, button=1, count=1):
        self.mouse("mouseMoved", x, y)
        time.sleep(0.15)
        pressed, held = time.time(), BUTTONS[button][1]
        for n in range(1, count + 1):
            self.mouse("mousePressed", x, y, button, n, held)
            self.mouse("mouseReleased", x, y, button, n)
        released = time.time()
        time.sleep(0.2)
        return pressed, released

    def drag(self, x1, y1, x2, y2, steps=12):
        self.mouse("mouseMoved", x1, y1)
        self.mouse("mousePressed", x1, y1, 1, 1, 1)
        pressed = time.time()
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps, 1, 0, 1)
            time.sleep(0.03)
        self.mouse("mouseReleased", x2, y2, 1, 1)
        return pressed, time.time()

    def stroke(self, name, down=True, up=True):
        bits, key, code, vk, text = keystroke(name)
        event = {"modifiers": bits, "key": key, "code": code, "windowsVirtualKeyCode": vk}
        if down:
            edit = EDITS.get(key.lower()) if bits & 6 and len(key) == 1 else None
            self.call("Input.dispatchKeyEvent", type="keyDown" if text else "rawKeyDown", text=text,
                      **event, **({"commands": [edit]} if edit else {}))
        if up:
            self.call("Input.dispatchKeyEvent", type="keyUp", **event)

    def type(self, text, delay=0.04):
        first = last = time.time()
        for index, char in enumerate(text):
            last = time.time()
            first = last if index == 0 else first
            if char.isascii():
                self.stroke("enter" if char == "\n" else "space" if char == " " else char)
            else:
                self.call("Input.insertText", text=char)
            time.sleep(delay)
        return first, last

    def key(self, *keys):
        first = last = time.time()
        for index, name in enumerate(keys):
            last = time.time()
            first = last if index == 0 else first
            self.stroke(name)
            time.sleep(0.05)
        return first, last

    def press(self, key, down):
        at = time.time()
        self.stroke(key, down, not down)
        return at, None

    def size(self):
        """The viewport in CSS pixels."""
        return tuple(self.call("Runtime.evaluate", expression="[innerWidth, innerHeight]", returnByValue=True)
                     ["result"]["value"])

    def capture(self, path):
        path = Path(path)
        image = self.call("Page.captureScreenshot", format="jpeg" if path.suffix in (".jpg", ".jpeg") else "png")
        path.write_bytes(base64.b64decode(image["data"]))

    def fit(self, width, height):
        """Make the viewport width x height. Headless Chrome keeps room for its tab strip and toolbar in the window."""
        window = self.call("Browser.getWindowForTarget")["windowId"]
        outer = self.call("Runtime.evaluate", expression="[outerWidth, outerHeight]", returnByValue=True)["result"]["value"]
        inner = self.size()
        self.call("Browser.setWindowBounds", windowId=window, bounds={"width": width + outer[0] - inner[0],
                                                                       "height": height + outer[1] - inner[1]})

    def lines(self):
        """The visible text lines of the page: [{text, x, y, w, h, words: [{text, x, y, w, h}]}], top to bottom."""
        answer = self.call("Runtime.evaluate", expression=LINES, returnByValue=True)
        if "exceptionDetails" in answer:
            raise Problem(f"The page text could not be read: {answer['exceptionDetails']['text']}.")
        return answer["result"]["value"]


def close_browser(address):
    """Ask the browser to close itself, which writes its cookies and storage. A browser that is gone is no error."""
    try:
        with urllib.request.urlopen(f"http://{address.removeprefix(SCHEME)}/json/version", timeout=5) as answer:
            socket = websocket.create_connection(json.load(answer)["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
        socket.send(json.dumps({"id": 1, "method": "Browser.close"}))
        socket.close()
    except (OSError, ValueError, KeyError, http.client.HTTPException, websocket.WebSocketException):
        pass


def screencast(address, stop, deliver):
    """Give deliver(time, (width, height), write) a frame at the start, then one at each change of the page, until the
    event stop is set. A browser that stops answering is tried again."""
    while not stop.is_set():
        try:
            with WebScreen(address) as screen:
                width, height = screen.size()
                screen.call("Page.startScreencast", format="jpeg", quality=90, maxWidth=width, maxHeight=height)
                first = screen.call("Page.captureScreenshot", format="jpeg", quality=90)["data"]
                deliver(time.time(), (width, height), lambda path: path.write_bytes(base64.b64decode(first)))
                while not stop.is_set():
                    screen.next_event(0.5)
                    for event in [e for e in screen.events if e["method"] == "Page.screencastFrame"]:
                        screen.events.remove(event)
                        params = event["params"]
                        screen.call("Page.screencastFrameAck", sessionId=params["sessionId"])
                        size = (round(params["metadata"]["deviceWidth"]), round(params["metadata"]["deviceHeight"]))
                        deliver(time.time(), size, lambda path, data=params["data"]: path.write_bytes(base64.b64decode(data)))
                    screen.events.clear()
        except Problem:
            stop.wait(0.5)
