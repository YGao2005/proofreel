"""`vm image`: make the `linux` state from nothing.

It downloads the Debian cloud image, checks its SHA-512, and boots it once in QEMU. cloud-init makes the user from
`images/debian-seed`, which the host serves over HTTP (no ISO tool). `images/debian-desktop.sh` then installs Xfce and
Chromium in the guest, and `vm save` stops the guest and keeps the disk.
"""

import hashlib
import http.server
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from importlib import resources

from . import Problem, qemu
from . import vm as vms

SOURCE = "https://cloud.debian.org/images/cloud/trixie/latest/"
FILE = "debian-13-generic-arm64.qcow2"
USER = PASSWORD = "tester"
DISK = "10G"
MEMORY = 2048


def fetch(name, target):
    try:
        with urllib.request.urlopen(SOURCE + name, timeout=60) as reply, open(target, "wb") as out:
            shutil.copyfileobj(reply, out)
    except (urllib.error.URLError, OSError) as error:
        raise Problem(f"Could not download {SOURCE}{name}: {error}.") from None


def sha512(path):
    digest = hashlib.sha512()
    with open(path, "rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def expected(sums, name):
    """The SHA-512 that a SHA512SUMS text lists for a file name."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0]
    raise Problem(f"SHA512SUMS at {SOURCE} does not list {name}.")


def download():
    """The Debian cloud image in PROOFREEL_HOME/images, downloaded once and checked against SHA512SUMS every time."""
    folder = vms.HOME / "images"
    folder.mkdir(parents=True, exist_ok=True)
    sums, image = folder / "SHA512SUMS", folder / FILE
    fetch("SHA512SUMS", sums)
    want = expected(sums.read_text(), FILE)
    for attempt in range(2):
        if not image.exists():
            print(f"Downloading {SOURCE}{FILE} ...", flush=True)
            fetch(FILE, image)
        if sha512(image) == want:
            return image
        image.unlink()
    raise Problem(f"{FILE} does not match its SHA-512 in {SOURCE}SHA512SUMS, so it was deleted. Try again.")


class Seed(http.server.ThreadingHTTPServer):
    """Serves the cloud-init files of this package on 127.0.0.1. The guest reaches them at 10.0.2.2."""

    def __init__(self):
        folder = resources.files(__package__).joinpath("images", "debian-seed")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                file = self.path.strip("/")
                if file not in ("meta-data", "user-data"):
                    self.send_error(404)
                    return
                body = folder.joinpath(file).read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        super().__init__(("127.0.0.1", vms.free_port(8800)), Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def smbios(self):
        return ["-smbios", f"type=1,serial=ds=nocloud;s=http://10.0.2.2:{self.server_address[1]}/"]


def make(name="linux"):
    """Make the state `name`: Debian 13 arm64 with Xfce and Chromium, signed in as tester."""
    vms.check_name(name)
    if (vms.STATES / f"{name}.json").exists() or qemu.exists(name):
        raise Problem(f"State {name!r} exists. To make it again, remove it first: proofreel vm drop {name}.")
    qemu.need_qemu()
    image = download()
    vms.down()
    vms.base(name, image, "qemu", "linux", USER, PASSWORD)
    try:
        subprocess.run(["qemu-img", "resize", str(qemu.folder(name) / "disk.qcow2"), DISK], check=True,
                       capture_output=True)
        info = vms.state_info(name)
        seed = Seed()
        try:
            run = vms.start(info, name, qemu.up(name, info, memory=MEMORY, extra=seed.smbios), desktop=False)
        finally:
            seed.shutdown()
        print("Installing the desktop in the guest. This takes a few minutes.", flush=True)
        script = resources.files(__package__).joinpath("images", "debian-desktop.sh")
        with resources.as_file(script) as path:
            run.upload(str(path), "/tmp/debian-desktop.sh")
        done = run.ssh(f"sudo sh /tmp/debian-desktop.sh {USER} 2>&1", check=False, timeout=3600)
        if done.returncode:
            raise Problem("The desktop install failed in the guest. The end of its output:\n"
                          + "\n".join(done.stdout.splitlines()[-15:]))
        vms.save(name)
    except BaseException:
        vms.down()
        vms.drop(name)
        raise
    vms.down()
    print(f"State {name} is ready: proofreel vm up {name}.")
