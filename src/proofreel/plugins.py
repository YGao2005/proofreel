"""Plugin folders: conditions and probes. A plugin is a folder with a manifest (<kind>.toml) and scripts.

A name is found in this order, and the first match wins:
  1. a path to a folder
  2. ./.proofreel/<kind>s/<name>        (the project you work in: an app's repo ships its own plugins)
  3. $PROOFREEL_HOME/<kind>s/<name>     (yours, on this Mac)
  4. the plugins that come with proofreel

Every manifest has name (the folder's name), version, os (the guest systems it works on), fidelity (what it does not
reproduce), and [values] (name = default; "" means the value is required). [profiles] names sets of values: the value
`profile` picks one, and a value that is given replaces the profile's. Each kind adds its own fields and says which
scripts it needs. A step that runs in the guest is <step>.sh on macOS and Linux, and <step>.ps1 on Windows
(guest.py decides). host.sh, if it is there, runs on the host first, in a copy of the folder ($OUT), and that copy
goes to the guest.
"""

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from . import HOME, Problem, guest

def guest_steps(*steps):
    return lambda info: {guest.GUESTS[system].script(step) for system in info["os"] if guest.GUESTS[system].shell
            for step in steps}


def probe_scripts(info):
    """A host probe is run.py, run with this Python. A guest probe is run, in the guest's own script language. A
    probe with setup also has a guest start and stop."""
    if info["where"] not in ("host", "guest"):
        raise ValueError(f"{info['name']}/probe.toml: where is host or guest, not {info['where']!r}.")
    scripts = {"run.py"} if info["where"] == "host" else guest_steps("run")(info)
    return scripts | (guest_steps("start", "stop")(info) if info.get("setup") else set())


def condition_scripts(info):
    """A condition that lasts one recording (it has `removes`) also has a remove step."""
    return guest_steps("apply", "check", *(["remove"] if info.get("removes") else []))(info)


KINDS = {
    "condition": {"fields": ("fakes", "applies", "checks"), "scripts": condition_scripts},
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
    values, profiles = info.get("values", {}), info.get("profiles", {})
    if profiles and "profile" not in values:
        raise ValueError(f"{path.name}/{kind}.toml has [profiles] and no value profile to pick one.")
    if unknown := sorted({k for p in profiles.values() for k in p} - set(values)):
        raise ValueError(f"{path.name}/{kind}.toml: [profiles] set {', '.join(unknown)}, which are not in [values].")
    return {**info, "values": values, "profiles": profiles}


def spec(item):
    """(name, values) of "name" or "name:KEY=VALUE,KEY=VALUE"."""
    name, _, pairs = item.partition(":")
    if bad := [pair for pair in pairs.split(",") if pair and "=" not in pair]:
        raise Problem(f"{item}: write {name}:KEY=VALUE,KEY=VALUE, not {bad[0]!r}.")
    return name, dict(pair.split("=", 1) for pair in pairs.split(",") if pair)


def resolve(info, given):
    """The plugin's values: the given ones, else the picked profile's, else the defaults. A value with no default must
    be given."""
    picked = {}
    if info["profiles"]:
        name = given.get("profile", info["values"]["profile"])
        if name not in info["profiles"]:
            raise Problem(f"{info['name']} has no profile {name!r}. Known: {', '.join(info['profiles'])}.")
        picked = info["profiles"][name]
    values = {name: given.get(name, picked.get(name, default)) for name, default in info["values"].items()}
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


def pending(run, kind, name, step, values):
    """Write a reset to the run record before the guest change it undoes. It stays until `undo` runs it, so a crash
    leaves it for the next start."""
    from .vm import CURRENT
    record = json.loads(CURRENT.read_text())
    record["pending"] = [*record.get("pending", []), {"kind": kind, "name": name, "script": step, "values": values}]
    CURRENT.write_text(json.dumps(record))


def undo(run):
    """Run the pending resets, last first, and clear them. Returns (reset, ok, last line of output) for each."""
    from .vm import CURRENT
    record = json.loads(CURRENT.read_text())
    results = []
    for entry in reversed(record.get("pending", [])):
        code, output = script(run, entry["kind"], entry["name"], entry["script"], entry["values"], timeout=90)
        results.append((entry, code == 0, output.splitlines()[-1] if output else f"{entry['script']} exit {code}"))
    CURRENT.write_text(json.dumps({**record, "pending": []}))
    return results


def failed(results):
    """One line for each reset that did not work."""
    return [f"{entry['kind'].capitalize()} {entry['name']}: its {entry['script']} in the run VM failed: {said}"
            for entry, ok, said in results if not ok]
