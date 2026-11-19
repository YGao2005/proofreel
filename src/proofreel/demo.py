"""A made-up session: a sign-up form on a plain desktop, drawn frame by frame. It needs no VNC, so it shows what
proofreel makes and tests the renderer."""

import json
import shutil

from PIL import Image, ImageDraw

from .draw import font
from .render import render
from .session import VERSION

W, H = 1440, 900
EMAIL, NAME = "sam@example.com", "Sam"
TYPO = "Sma"
FIELD_EMAIL = (560, 380, 880, 420)
FIELD_NAME = (560, 450, 880, 490)
BUTTON = (560, 530, 880, 574)


def screen(state):
    image = Image.new("RGB", (W, H), (58, 92, 140))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        k = y / H
        draw.line([(0, y), (W, y)], fill=(int(58 + 40 * k), int(92 + 30 * k), int(140 + 20 * k)))
    draw.rectangle((0, 0, W, 28), fill=(236, 236, 240))
    draw.text((16, 6), "Demo App      File      Edit      View", font=font(14), fill=(30, 30, 30))
    draw.rounded_rectangle((480, 220, 960, 640), 14, fill=(250, 250, 252))
    draw.text((560, 270), "Create your account" if not state["done"] else "Welcome, " + state["name"],
              font=font(28), fill=(20, 20, 24))
    if not state["done"]:
        for box, label, value in ((FIELD_EMAIL, "Email", state["email"]), (FIELD_NAME, "First name", state["name"])):
            focused = state["focus"] == label
            draw.rounded_rectangle(box, 8, fill="white", outline=(10, 132, 255) if focused else (200, 200, 208),
                                   width=2 if focused else 1)
            draw.text((box[0] + 12, box[1] + 10), value or label, font=font(17),
                      fill=(20, 20, 24) if value else (150, 150, 158))
        busy = state["busy"]
        draw.rounded_rectangle(BUTTON, 10, fill=(10, 132, 255) if not busy else (120, 170, 235))
        draw.text((BUTTON[0] + 100, BUTTON[1] + 11), "Creating..." if busy else "Create account", font=font(18),
                  fill="white")
    else:
        draw.text((560, 330), "Your account is ready.", font=font(18), fill=(90, 90, 98))
    return image


def demo(folder, broken=False):
    """broken: the first name is typed wrong, so the final check fails."""
    name = TYPO if broken else NAME
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "frames").mkdir(parents=True)
    t0 = 1_800_000_000.0
    state = {"email": "", "name": "", "focus": None, "busy": False, "done": False}
    events, frames = [], []

    def at(t, kind, text, **fields):
        events.append({"t": t0 + t, "kind": kind, "text": text, **fields})

    def hold(start, end, fps=10):
        t = start
        while t < end:
            frames.append((t, dict(state)))
            t += 1 / fps

    mid = lambda box: ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    at(0.2, "step", "Open the sign-up form")
    hold(0, 1.5)
    at(1.5, "step", "Fill in the form")
    at(2.2, "click", 'click "Email"', x=mid(FIELD_EMAIL)[0], y=mid(FIELD_EMAIL)[1])
    hold(1.5, 2.3)
    state["focus"] = "Email"
    at(2.6, "type", f'type "{EMAIL}"', end=t0 + 2.6 + len(EMAIL) * 0.08)
    for i in range(len(EMAIL) + 1):
        state["email"] = EMAIL[:i]
        hold(2.6 + i * 0.08, 2.6 + (i + 1) * 0.08, 25)
    at(4.4, "click", 'click "First name"', x=mid(FIELD_NAME)[0], y=mid(FIELD_NAME)[1])
    hold(2.6 + (len(EMAIL) + 1) * 0.08, 4.5)
    state["focus"] = "First name"
    at(4.8, "type", f'type "{name}"', end=t0 + 4.8 + len(name) * 0.1)
    for i in range(len(name) + 1):
        state["name"] = name[:i]
        hold(4.8 + i * 0.1, 4.8 + (i + 1) * 0.1, 25)
    at(5.8, "click", 'click "Create account"', x=mid(BUTTON)[0], y=mid(BUTTON)[1])
    hold(5.2, 5.9)
    state["busy"], state["focus"] = True, None
    at(5.95, "step", "The account is made")
    frames.append((6.0, dict(state)))
    for t in range(7, 14):
        frames.append((float(t) + 0.2, dict(state)))
    state["busy"], state["done"] = False, True
    hold(14.0, 15.5)
    at(6.0, "wait", 'wait for "Welcome"', end=t0 + 14.6, ok=True, detail="seen after 8.6 s")
    at(15.0, "check", '"Welcome, Sam" is on the screen', ok=not broken)
    hold(15.5, 17.0)

    cache = {}
    with open(folder / "times.txt", "w") as times:
        for n, (t, s) in enumerate(frames):
            key = json.dumps(s, sort_keys=True)
            if key not in cache:
                cache[key] = screen(s)
            cache[key].save(folder / "frames" / f"{n:06d}.jpg", quality=88)
            times.write(f"{t0 + t:.3f} {t0 + t + 0.03:.3f}\n")
    (folder / "screen.txt").write_text(f"{W} {H}\n")
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (folder / "session.json").write_text(json.dumps({
        "version": VERSION, "title": "Sign-up demo",
        "about": "A new user makes an account in a made-up app, drawn frame by frame to show what proofreel makes. The wait for the server plays fast.",
        "meta": {"": "proofreel demo, run with a typo" if broken else "proofreel demo"}}))
    print(render(folder))
