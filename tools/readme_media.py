"""Dev tool, not in the wheel: play a scripted tour of a review page and write the README media.

    python tools/readme_media.py <review folder> [--out docs]

Needs playwright, Google Chrome, and ffmpeg. It writes tour.mp4, tour.gif, review-page.png, and budget-failed.png.
The review folder is not changed: the tool builds the page in a copy.
"""

import argparse
import base64
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SIZE = (1440, 900)
GIF_LIMIT = 8_000_000

KINDS = {
    "play": "button.play",
    "node": ".flow g.node:not(.start) >> nth={}",
    "bad-node": ".flow g.node.bad >> nth=0",
    "row": ".flow ol.steps > li:not(.more) .row >> nth={}",
    "show": '.flow [aria-label=Show] button:text-is("{}")',
    "tracks": "button.fold",
    "tab": '[role=tab][data-view="{}"]',
}
ACTIONS = ("goto", "click", "look")

PASS_RUN = "Write and save a note"
FAIL_RUN = "Search notes, tags down"

TOUR = [
    {"action": "goto", "target": ("run", PASS_RUN), "caption": "A journey that passed", "pause": 1.5},
    {"action": "click", "target": ("play", None), "caption": "Play the review video", "pause": 5, "shot": "review-page.png"},
    {"action": "look", "target": None, "caption": "The flow lights the current state", "pause": 4},
    {"action": "click", "target": ("node", 0), "caption": "Click a state to jump there", "pause": 3.5},
    {"action": "click", "target": ("node", 1), "caption": "Click another state", "pause": 3},
    {"action": "click", "target": ("show", "Steps"), "caption": "Or list the steps", "pause": 1.5},
    {"action": "click", "target": ("row", 1), "caption": "Click a step to jump there", "pause": 3.5},
    {"action": "click", "target": ("show", "Flow"), "caption": "Back to the flow", "pause": 1},
    {"action": "click", "target": ("tracks", None), "caption": "Open Tracks under the video", "pause": 4},
    {"action": "goto", "target": ("run", FAIL_RUN), "caption": "Now a run that failed", "pause": 1.5},
    {"action": "look", "target": None, "caption": "Tracks open red: budget failed", "pause": 4, "shot": "budget-failed.png"},
    {"action": "click", "target": ("bad-node", None), "caption": "The failed check is in the flow", "pause": 3.5},
    {"action": "click", "target": ("tab", "network"), "caption": "The failed request is here", "pause": 4},
    {"action": "click", "target": ("tab", "stats"), "caption": "Numbers for every measure", "pause": 4},
    {"action": "click", "target": ("tab", "journeys"), "caption": "Every journey of the suite", "pause": 4},
]

CURSOR = """
addEventListener('DOMContentLoaded', () => {
  const css = document.createElement('style');
  css.textContent = `
    .pr-cursor { position: fixed; left: 0; top: 0; width: 26px; height: 26px; z-index: 2147483647; pointer-events: none;
      transition: scale .1s; transform-origin: 3px 3px; filter: drop-shadow(0 1px 2px rgba(0,0,0,.4)); }
    .pr-cursor.down { scale: .82; }
    .pr-ring { position: fixed; z-index: 2147483646; pointer-events: none; width: 14px; height: 14px; margin: -7px 0 0 -7px;
      border-radius: 50%; border: 2px solid #3b82f6; animation: pr-ring .5s ease-out forwards; }
    @keyframes pr-ring { to { transform: scale(3.2); opacity: 0; } }
    .pr-caption { position: fixed; left: 34.5%; top: 50%; translate: -50% 0; z-index: 2147483647; pointer-events: none;
      padding: 9px 20px; border-radius: 999px; background: rgba(17,17,20,.92); color: #fff; font: 500 19px/1.2 Inter, system-ui, sans-serif; }
    .pr-hidden { display: none !important; }`;
  document.head.append(css);
  const cursor = document.createElement('div');
  cursor.className = 'pr-cursor pr-hidden';
  cursor.innerHTML = '<svg viewBox="0 0 26 26" width="26" height="26"><path d="M3 3l17 7.5-7 2.3-2.6 7z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const caption = document.createElement('div');
  caption.className = 'pr-caption pr-hidden';
  document.body.append(cursor, caption);
  addEventListener('mousemove', e => { cursor.classList.remove('pr-hidden'); cursor.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 3}px)`; }, true);
  addEventListener('mousedown', e => {
    cursor.classList.add('down');
    const ring = document.createElement('div');
    ring.className = 'pr-ring'; ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px';
    document.body.append(ring); setTimeout(() => ring.remove(), 600);
  }, true);
  addEventListener('mouseup', () => cursor.classList.remove('down'), true);
  window.prCaption = text => { caption.textContent = text || ''; caption.classList.toggle('pr-hidden', !text); };
  window.prBare = on => { cursor.classList.toggle('pr-hidden', on); caption.classList.toggle('pr-hidden', on || !caption.textContent); };
});
"""


def selector(kind, arg):
    return KINDS[kind].format(arg)


def check_tour(tour):
    """The problems in a tour: a step with an unknown action or target kind, or a caption of other than 3 to 8 words."""
    problems = []
    for i, step in enumerate(tour, 1):
        if step["action"] not in ACTIONS:
            problems.append(f"step {i}: unknown action {step['action']!r}")
        target = step.get("target")
        if step["action"] == "click" and (not target or target[0] not in KINDS):
            problems.append(f"step {i}: a click needs a target of a known kind")
        if step["action"] == "goto" and (not target or target[0] != "run"):
            problems.append(f"step {i}: goto needs a run target")
        if step["action"] == "look" and target:
            problems.append(f"step {i}: look has no target")
        if not 3 <= len(step["caption"].split()) <= 8:
            problems.append(f"step {i}: the caption has {len(step['caption'].split())} words")
        if step["pause"] <= 0:
            problems.append(f"step {i}: the pause must be above 0")
    return problems


def build_page(folder, work):
    from proofreel import page
    site = work / "site"
    shutil.copytree(folder, site)
    runs = page.load_runs(site)
    (site / "index.html").write_text(page.document(runs))
    return site / "index.html", runs


def run_index(runs, title):
    for i, run in enumerate(runs, 1):
        if title in (run.get("journey"), run["title"]):
            return i
    raise SystemExit(f"No run named {title!r}. The runs: {[r['title'] for r in runs]}")


class Tour:
    def __init__(self, page, runs, out):
        self.page, self.runs, self.out = page, runs, out
        self.at = (SIZE[0] / 2, SIZE[1] / 2)

    def glide(self, x, y, seconds=0.7):
        (x0, y0), n = self.at, int(seconds * 40)
        for i in range(1, n + 1):
            t = i / n
            t = t * t * (3 - 2 * t)
            self.page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t)
            self.page.wait_for_timeout(1000 * seconds / n)
        self.at = (x, y)

    def click(self, kind, arg):
        place = self.page.locator(selector(kind, arg)).first
        place.wait_for(state="visible", timeout=10_000)
        place.scroll_into_view_if_needed()
        box = place.bounding_box()
        self.glide(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.page.wait_for_timeout(200)
        self.page.mouse.down()
        self.page.wait_for_timeout(80)
        self.page.mouse.up()
        if kind == "tab":
            self.page.evaluate("document.querySelector('.views').scrollIntoView({ behavior: 'smooth', block: 'start' })")

    def goto(self, title):
        self.page.evaluate("n => { location.hash = 'run-' + n; scrollTo({ top: 0, behavior: 'smooth' }) }", run_index(self.runs, title))
        self.page.wait_for_function("document.querySelector('video') && document.querySelector('video').readyState >= 2")

    def shot(self, name):
        self.page.evaluate("window.prBare(true)")
        self.page.screenshot(path=self.out / name)
        self.page.evaluate("window.prBare(false)")

    def play(self, tour):
        for step in tour:
            self.page.evaluate("t => window.prCaption(t)", step["caption"])
            if step["action"] == "goto":
                self.goto(step["target"][1])
            elif step["action"] == "click":
                self.click(*step["target"])
            self.page.wait_for_timeout(1000 * step["pause"])
            if step.get("shot"):
                self.shot(step["shot"])


class Screencast:
    """The page's frames from Chrome's screencast, each with its time. A frame comes only when the page changes."""

    def __init__(self, page, folder):
        self.session, self.folder, self.frames = page.context.new_cdp_session(page), folder, []
        folder.mkdir()
        self.session.on("Page.screencastFrame", self.take)

    def take(self, event):
        path = self.folder / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(event["data"]))
        self.frames.append((event["metadata"]["timestamp"], path))
        self.session.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})

    def start(self):
        self.session.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": SIZE[0], "maxHeight": SIZE[1],
                                                   "everyNthFrame": 1})

    def stop(self):
        self.session.send("Page.stopScreencast")

    def listing(self, since):
        """An ffmpeg concat list: each frame from the first at or after since, held until the next frame arrives."""
        shown = [(max(t, since), path) for t, path in self.frames]
        lines = []
        for (t, path), (after, _) in zip(shown, shown[1:] + [(shown[-1][0] + 0.5, None)]):
            if after > since:
                lines.append(f"file '{path}'\nduration {after - t:.4f}")
        return "\n".join(lines) + f"\nfile '{shown[-1][1]}'\n"


def record(index, runs, out, work):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # WHY: the window of headless Chrome has 87 px of frame that the page does not use, so the page gets that much less
        window = f"--window-size={SIZE[0]},{SIZE[1] + 87}"
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--autoplay-policy=no-user-gesture-required", window])
        context = browser.new_context(no_viewport=True)
        context.add_init_script(CURSOR)
        page = context.new_page()
        page.goto(index.as_uri())
        page.wait_for_selector("video", timeout=15_000)
        page.wait_for_load_state("networkidle")
        tour = Tour(page, runs, out)
        tour.goto(PASS_RUN)
        page.evaluate("window.prCaption('')")
        cast = Screencast(page, work / "frames")
        cast.start()
        started = time.time()
        tour.play(TOUR)
        page.wait_for_timeout(500)
        cast.stop()
        listing = work / "frames.txt"
        listing.write_text(cast.listing(started))
        browser.close()
    return listing


def encode(listing, out):
    mp4, gif = out / "tour.mp4", out / "tour.gif"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", f"fps=25,scale={SIZE[0]}:{SIZE[1]}", "-c:v", "libx264", "-crf", "20", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    for fps, width, colors in ((12, 960, 128), (10, 960, 96), (8, 800, 64), (8, 640, 64)):
        graph = (f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
                 f"[b][p]paletteuse=dither=bayer:bayer_scale=4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf", graph, "-loop", "0", str(gif)], check=True)
        if gif.stat().st_size < GIF_LIMIT:
            return
    raise SystemExit(f"{gif} is still over {GIF_LIMIT} bytes")


def main():
    parser = argparse.ArgumentParser(description="Make the README tour video, GIF, and pictures from a review folder.")
    parser.add_argument("folder", type=Path, help="a review folder: runs.json and the run media")
    parser.add_argument("--out", type=Path, default=Path("docs"))
    args = parser.parse_args()
    if problems := check_tour(TOUR):
        raise SystemExit("\n".join(problems))
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        index, runs = build_page(args.folder, work)
        encode(record(index, runs, args.out, work), args.out)
    for name in ("tour.mp4", "tour.gif", "review-page.png", "budget-failed.png"):
        print(name, (args.out / name).stat().st_size)


if __name__ == "__main__":
    sys.exit(main())
