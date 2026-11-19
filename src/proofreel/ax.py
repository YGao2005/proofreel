"""Read the accessibility (AX) tree of a macOS guest, and find elements by their label.

A small helper (ax.swift) runs in the guest over SSH. macOS gives the Accessibility grant to the process that SSH
starts (/usr/libexec/sshd-keygen-wrapper), so the app under test needs no permission of its own.
"""

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import time
from importlib import resources

from . import vm

SOURCE = resources.files("proofreel").joinpath("ax.swift")


def helper():
    """The guest helper, compiled once on the host. The name holds a hash of the source, so a change rebuilds it."""
    source = SOURCE.read_bytes()
    binary = vm.HOME / "bin" / f"proofreel-ax-{hashlib.sha256(source).hexdigest()[:12]}"
    if not binary.exists():
        if not shutil.which("swiftc"):
            sys.exit("The AX helper is built with swiftc, so it needs a macOS host with Xcode or the Command Line Tools.")
        binary.parent.mkdir(parents=True, exist_ok=True)
        with resources.as_file(SOURCE) as path:
            subprocess.run(["swiftc", "-O", "-target", "arm64-apple-macos14", str(path), "-o", str(binary)],
                           check=True, capture_output=True)
    return binary


def tree(app=None):
    """The AX tree of the app's windows (the front app by default), and the main screen size in points."""
    binary = helper()
    command = shlex.join([f"./.{binary.name}", *(["--app", app] if app else [])])
    result = vm.ssh(command, check=False, timeout=60)
    if result.returncode == 127:
        vm.put(str(binary), f".{binary.name}")
        result = vm.ssh(command, check=False, timeout=60)
    if result.returncode:
        sys.exit(f"AX: {result.stderr.strip() or f'the helper failed ({result.returncode})'}")
    return json.loads(result.stdout)


def to_pixels(point, scale):
    return round(point * scale)


def intersect(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    return left, top, max(0, min(a[0] + a[2], b[0] + b[2]) - left), max(0, min(a[1] + a[3], b[1] + b[3]) - top)


def flatten(node, scale, clip, depth=0):
    """Each element with its depth and center in screen pixels. Visible: its center is in its window and scroll areas."""
    frame = node.get("frame")
    if frame and (depth == 0 or node["role"] == "AXScrollArea"):
        clip = intersect(clip, frame)
    element = {k: v for k, v in node.items() if k != "children"}
    element["depth"] = depth
    element["visible"] = False
    if frame and frame[2] > 0 and frame[3] > 0:
        cx, cy = frame[0] + frame[2] / 2, frame[1] + frame[3] / 2
        element.update(x=to_pixels(cx, scale), y=to_pixels(cy, scale),
                       visible=clip[0] <= cx < clip[0] + clip[2] and clip[1] <= cy < clip[1] + clip[3])
    yield element
    for child in node.get("children", []):
        yield from flatten(child, scale, clip, depth + 1)


def elements(screen, app=None):
    data = tree(app)
    scale = screen.size()[0] / data["screen"]["w"]
    clip = (0, 0, data["screen"]["w"], data["screen"]["h"])
    return [element for window in data["windows"] for element in flatten(window, scale, clip)]


def names(element):
    return [v for k in ("title", "description", "label", "value", "id") if isinstance(v := element.get(k), str)
            and not (k == "id" and v.startswith("_NS:"))]


def has_role(element, role):
    want = role.lower().removeprefix("ax")
    return any((element.get(k) or "").lower().removeprefix("ax") == want for k in ("role", "subrole"))


def matches(items, label, role=None):
    """Visible elements named the label, then ones whose name contains it. Case is ignored."""
    want = label.strip().lower()
    pool = [e for e in items if e["visible"] and (not role or has_role(e, role))]
    exact = [e for e in pool if any(name.strip().lower() == want for name in names(e))]
    return exact + [e for e in pool if e not in exact and any(want in name.lower() for name in names(e))]


def wait_for(screen, label, seconds, present=True, app=None, role=None):
    end = time.time() + seconds
    while True:
        found = matches(elements(screen, app), label, role)
        if bool(found) == present or time.time() > end:
            return found
        time.sleep(0.5)


def describe(element, indent=True):
    where = f"{element['x']:5} {element['y']:5}" if element["visible"] else f"{'-':>5} {'-':>5}"
    role = element["role"] + (f"/{element['subrole']}" if element.get("subrole") else "")
    shown = " ".join(json.dumps(name, ensure_ascii=False) for name in dict.fromkeys(names(element)))
    flags = "".join([" disabled" if element.get("enabled") is False else "", " focused" if element.get("focused") else ""])
    return f"{where}  {'  ' * element['depth'] if indent else ''}{role} {shown}{flags}".rstrip()
