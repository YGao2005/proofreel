"""The network probe's host side: mitmdump with the span addon, on a free port that only the run VM may use. The CA
is new for each session, in a temporary folder that is deleted when the probe stops. Nothing else is written to disk."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from proofreel import redact
from proofreel.probes import tool

# WHY: one folder for each run name, so a CA that a killed recorder left behind goes at the next start.
confdir = Path(tempfile.gettempdir()) / f"proofreel-network-{os.environ.get('PROOFREEL_VM', 'pr-run')}"
shutil.rmtree(confdir, ignore_errors=True)
confdir.mkdir(mode=0o700)
proxy = subprocess.Popen(
    [tool("mitmdump"), "-q", "--listen-host", os.environ["PROOFREEL_BIND"], "--listen-port", os.environ["PROOFREEL_PORT"],
     "--set", f"confdir={confdir}", "--set", "connection_strategy=lazy", "-s", str(Path(__file__).with_name("addon.py"))],
    env={**os.environ, "PROOFREEL_REDACT": redact.__file__}, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
signal.signal(signal.SIGTERM, lambda *_: proxy.terminate())
try:
    proxy.wait()
finally:
    shutil.rmtree(confdir, ignore_errors=True)
sys.exit(proxy.returncode)
