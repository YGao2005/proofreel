"""Conditions: fake hardware and setups in a VM guest, such as a Bluetooth headset, no microphone, or no network.

A condition is a folder here (or any folder path) with:
  condition.toml   name, version, fakes, applies, checks, fidelity, and [values] (name = default; "" = required)
  apply.sh         runs once in the guest, as the guest user (sudo needs no password)
  check.sh         runs in the guest; exit 0 when the effect holds; it prints what it saw
  host.sh          optional; runs on the host first, in a copy of the folder ($OUT). The copy goes to the guest.

`vm build --condition` applies conditions and saves them in the state. `vm up` runs the check of each condition of
the state, so a state whose condition does not hold stops loudly. A flow line `condition <name>` makes `run` refuse a
run VM whose state lacks it.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from .. import vm

HERE = Path(__file__).parent
FIELDS = ("name", "version", "fakes", "applies", "checks", "fidelity")
GUEST = "/Users/Shared/proofreel/conditions"


def known():
    return sorted(p.parent.name for p in HERE.glob("*/condition.toml"))


def folder(name):
    path = Path(name) if "/" in name else HERE / name
    if not (path / "condition.toml").exists():
        sys.exit(f"No condition {name!r}. Known: {', '.join(known())}.")
    return path


def manifest(path):
    path = Path(path)
    info = tomllib.loads((path / "condition.toml").read_text())
    if missing := [f for f in FIELDS if not info.get(f)]:
        raise ValueError(f"{path.name}/condition.toml has no {', '.join(missing)}.")
    if info["name"] != path.name:
        raise ValueError(f"{path.name}/condition.toml is named {info['name']!r}; the folder and the name must match.")
    if missing := [s for s in ("apply.sh", "check.sh") if not (path / s).exists()]:
        raise ValueError(f"{path.name} has no {', '.join(missing)}.")
    return {**info, "values": info.get("values", {})}


def resolve(info, given):
    """The condition's values: the given ones, else the defaults. A value with no default must be given."""
    values = {name: given.get(name, default) for name, default in info["values"].items()}
    if missing := [name for name, value in values.items() if value == ""]:
        sys.exit(f"Condition {info['name']} needs --set {'=... --set '.join(missing)}=...")
    return values


def names(conditions):
    return [c["name"] for c in conditions]


def missing(needed, conditions):
    """The conditions a flow needs that a state does not have."""
    return [name for name in needed if name not in names(conditions)]


def guest(record, script):
    env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in record.get("values", {}).items())
    result = vm.ssh(f"cd {GUEST}/{record['name']} && {env} sh {script}", check=False, timeout=300)
    return result.returncode, (result.stdout + result.stderr).strip()


def apply(name, given):
    """Apply a condition in the run VM, then check it. Returns the record to keep in the state."""
    path = folder(name)
    info = manifest(path)
    record = {"name": info["name"], "version": info["version"], "values": resolve(info, given)}
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp) / info["name"]
        shutil.copytree(path, stage)
        if (stage / "host.sh").exists():
            done = subprocess.run(["sh", "host.sh"], cwd=stage, env={**os.environ, **record["values"], "OUT": str(stage)},
                                  capture_output=True, text=True)
            if done.returncode:
                sys.exit(f"Condition {name}: host.sh failed: {(done.stdout + done.stderr).strip()[-800:]}")
        vm.ssh(f"mkdir -p {GUEST} && rm -rf {GUEST}/{info['name']}", timeout=30)
        vm.put(str(stage), GUEST)
    code, output = guest(record, "apply.sh")
    if code:
        sys.exit(f"Condition {name} did not apply: {output[-800:]}")
    check(record)
    return record


def check(record):
    """Run the condition's check in the run VM. A failed check stops everything."""
    code, output = guest(record, "check.sh")
    if code:
        sys.exit(f"Condition {record['name']} does not hold: {output[-800:] or f'check.sh exit {code}'}")
    print(f"Condition {record['name']}: {output.splitlines()[-1] if output else 'holds'}")
