"""Plugin folders: conditions and probes. A plugin is a folder with a manifest (<kind>.toml) and scripts.

A name is found in this order, and the first match wins:
  1. a path to a folder
  2. ./.proofreel/<kind>s/<name>        (the project you work in: an app's repo ships its own plugins)
  3. $PROOFREEL_HOME/<kind>s/<name>     (yours, on this Mac)
  4. the plugins that come with proofreel

Every manifest has name (the folder's name), version, os (the guest systems it works on), fidelity (what it does not
reproduce), and [values] (name = default; "" means the value is required). Each kind adds its own fields and says
which scripts it needs. A step that runs in the guest is <step>.sh on macOS and Linux, and <step>.ps1 on Windows
(guest.py decides). host.sh, if it is there, runs on the host first, in a copy of the folder ($OUT), and that copy
goes to the guest.
"""

import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from . import HOME, Problem, guest

def guest_steps(*steps):
    return lambda info: {guest.GUESTS[system].script(step) for system in info["os"] for step in steps}


def probe_scripts(info):
    """A host probe is run.py, run with this Python. A guest probe is run, in the guest's own script language."""
    if info["where"] == "host":
        return {"run.py"}
    if info["where"] != "guest":
        raise ValueError(f"{info['name']}/probe.toml: where is host or guest, not {info['where']!r}.")
    return guest_steps("run")(info)


KINDS = {
    "condition": {"fields": ("fakes", "applies", "checks"), "scripts": guest_steps("apply", "check")},
    "probe": {"fields": ("where", "privacy"), "scripts": probe_scripts},
}
COMMON = ("name", "version", "os", "fidelity")


def roots(kind):
    """The folders that hold plugins of a kind, in search order, with where each is from."""
    return [(Path.cwd() / ".proofreel" / f"{kind}s", "project"), (HOME / f"{kind}s", "home"),
            (Path(__file__).parent / f"{kind}s", "")]


def known(kind):
    """{name: source} for every plugin of a kind. A name in an earlier root hides the same name in a later one."""
    found = {}
    for root, source in roots(kind):
        for path in sorted(root.glob(f"*/{kind}.toml")) if root.exists() else []:
            found.setdefault(path.parent.name, source)
    return found


def find(kind, name):
    path = Path(name)
    if path.is_dir() and (path / f"{kind}.toml").exists():
        return path
    for root, _ in roots(kind):
        if (root / name / f"{kind}.toml").exists():
            return root / name
    raise Problem(f"No {kind} {name!r}. Known: {', '.join(known(kind)) or 'none'}.")


def manifest(kind, path):
    """The manifest, checked: every field, a known system for each os, the folder's name, and each step's script for
    each system. A broken plugin raises ValueError, so its author sees it at once."""
    path = Path(path)
    info = tomllib.loads((path / f"{kind}.toml").read_text())
    if missing := [f for f in COMMON + KINDS[kind]["fields"] if not info.get(f)]:
        raise ValueError(f"{path.name}/{kind}.toml has no {', '.join(missing)}.")
    if unknown := [name for name in info["os"] if name not in guest.GUESTS]:
        raise ValueError(f"{path.name}/{kind}.toml names unknown systems {unknown}. Known: {', '.join(guest.GUESTS)}.")
    if info["name"] != path.name:
        raise ValueError(f"{path.name}/{kind}.toml is named {info['name']!r}; the folder and the name must match.")
    scripts = KINDS[kind]["scripts"](info)
    if missing := sorted(s for s in scripts if not (path / s).exists()):
        raise ValueError(f"{path.name} has no {', '.join(missing)}.")
    return {**info, "values": info.get("values", {})}


def resolve(info, given):
    """The plugin's values: the given ones, else the defaults. A value with no default must be given."""
    values = {name: given.get(name, default) for name, default in info["values"].items()}
    if missing := [name for name, value in values.items() if value == ""]:
        raise Problem(f"{info['name']} needs --set {'=... --set '.join(missing)}=...")
    return values


def fits(kind, name, system):
    """The manifest of a plugin that works on the guest system; any other stops everything."""
    info = manifest(kind, find(kind, name))
    if system not in info["os"]:
        raise Problem(f"{kind.capitalize()} {name} works on {', '.join(info['os'])}, and the VM is {system}.")
    return info


def folder(run, kind, name):
    """Where a plugin's files live in the guest."""
    return f"{run.guest.home}/{kind}s/{name}"


def stage(run, kind, name, values):
    """Copy the plugin into the guest, after its host.sh, if any, has run in a copy of the folder."""
    path = find(kind, name)
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / path.name
        shutil.copytree(path, copy)
        if (copy / "host.sh").exists():
            done = subprocess.run(["sh", "host.sh"], cwd=copy, env={**os.environ, **values, "OUT": str(copy)},
                                  capture_output=True, text=True)
            if done.returncode:
                raise Problem(f"{name}: host.sh failed: {(done.stdout + done.stderr).strip()[-800:]}")
        target = folder(run, kind, path.name)
        run.ssh(run.guest.fresh_folder(target), timeout=30)
        run.upload(str(copy), target.rsplit("/", 1)[0])


def script(run, kind, name, step, values, timeout=300):
    """Run one step of a staged plugin in the guest. Returns (exit code, output)."""
    try:
        result = run.ssh(run.guest.run_script(folder(run, kind, name), step, values), check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"{step} did not end in {timeout} s."
    return result.returncode, (result.stdout + result.stderr).strip()
