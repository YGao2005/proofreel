"""Record an agent driving a screen, and turn it into a review video and page."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path

__version__ = "0.1.0"

HOME = Path(os.environ.get("PROOFREEL_HOME", Path.home() / ".proofreel"))


def swift_tool(source, *flags):
    """A Swift file of this package, compiled once on the host. The name holds a hash of the source and the flags,
    so a change builds it again. The build goes to a temporary file first, so parallel runs never see half a binary."""
    text = resources.files(__name__).joinpath(source).read_bytes()
    digest = hashlib.sha256(text + repr(flags).encode()).hexdigest()[:12]
    binary = HOME / "bin" / f"proofreel-{Path(source).stem}-{digest}"
    if binary.exists():
        return binary
    if not shutil.which("swiftc"):
        sys.exit(f"{source} is built with swiftc, so it needs a macOS host with Xcode or the Command Line Tools.")
    binary.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=binary.parent) as temp, \
            resources.as_file(resources.files(__name__).joinpath(source)) as path:
        built = Path(temp) / binary.name
        subprocess.run(["swiftc", "-O", *flags, str(path), "-o", str(built)], check=True, capture_output=True)
        built.replace(binary)
    return binary
