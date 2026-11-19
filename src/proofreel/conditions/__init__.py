"""Conditions: fake hardware and setups in a VM guest, such as a Bluetooth headset, no microphone, or no network.

A condition is a plugin (see plugins.py): condition.toml (plus fakes, applies, and checks) and two steps. apply runs
once in the guest as the guest user (sudo needs no password). check runs in the guest, exits 0 when the effect holds,
and prints what it saw.

`vm build --condition` applies conditions and saves them in the state. `vm up` runs the check of each condition of
the state, so a state whose condition does not hold stops loudly. A flow line `condition <name>` makes `run` refuse a
run VM whose state lacks it.
"""

from .. import Problem, plugins


def names(conditions):
    return [c["name"] for c in conditions]


def missing(needed, conditions):
    """The conditions a flow needs that a state does not have."""
    return [name for name in needed if name not in names(conditions)]


def apply(run, name, given):
    """Apply a condition in the run VM, then check it. Returns the record to keep in the state."""
    info = plugins.fits("condition", name, run["os"])
    record = {"name": info["name"], "version": info["version"], "values": plugins.resolve(info, given)}
    plugins.stage(run, "condition", name, record["values"])
    code, output = plugins.script(run, "condition", info["name"], "apply", record["values"])
    if code:
        raise Problem(f"Condition {name} did not apply: {output[-800:]}")
    check(run, record)
    return record


def check(run, record):
    """Run the condition's check in the run VM. A failed check stops everything."""
    code, output = plugins.script(run, "condition", record["name"], "check", record.get("values", {}))
    if code:
        raise Problem(f"Condition {record['name']} does not hold: {output[-800:] or f'check exit {code}'}")
    print(f"Condition {record['name']}: {output.splitlines()[-1] if output else 'holds'}")
