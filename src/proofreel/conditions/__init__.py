"""Conditions: fake hardware and setups in a VM guest, such as a Bluetooth headset, no microphone, or a slow network.

A condition is a plugin (see plugins.py): condition.toml (plus fakes, applies, and checks) and two steps. apply runs
once in the guest as the guest user (sudo needs no password). check runs in the guest, exits 0 when the effect holds,
and prints what it saw.

Most conditions are kept in a state: `vm build --condition` applies them and saves them in the state. `vm up` runs the
check of each condition of the state, so a state whose condition does not hold stops loudly. A flow line
`condition <name>` makes `run` refuse a run VM whose state lacks it.

A condition with `removes` (and a remove step) lasts one recording instead: `start --condition <name>[:KEY=VALUE,...]`,
or the same flow line, applies it before the recorder starts, and `stop` removes it (plugins.undo). remove runs even after an apply
that stopped half way, so it must work from any state, and it exits 0 only when nothing of the condition is left.
"""

from .. import Problem, plugins


def names(conditions):
    return [c["name"] for c in conditions]


def missing(needed, conditions):
    """The conditions a flow needs that a state does not have."""
    return [name for name in needed if name not in names(conditions)]


def lasts_one_recording(info):
    return bool(info.get("removes"))


def record(name, given, system, recording):
    """The record of a condition, checked before anything runs: it fits the system, its values resolve, and it lasts
    where it is asked to (one recording, or a state)."""
    info = plugins.fits("condition", name, system)
    if lasts_one_recording(info) != recording:
        raise Problem(f"Condition {name} lasts one recording: proofreel start <name> --condition {name}[:KEY=VALUE,...], "
                      f"or a flow line condition {name}." if lasts_one_recording(info) else
                      f"Condition {name} is kept in a state: proofreel vm build <state> --from <base> --condition {name}.")
    return {"name": info["name"], "version": info["version"], "values": plugins.resolve(info, given),
            **({"recording": True} if recording else {})}


def split(items):
    """A flow's condition lines as (names a state must have, items that its recording applies)."""
    kept, applied = [], []
    for item in items:
        name, given = plugins.spec(item)
        info = plugins.manifest("condition", plugins.find("condition", name))
        if lasts_one_recording(info):
            plugins.resolve(info, given)
            applied.append(item)
        else:
            kept.append(name)
    return kept, applied


def apply(run, record):
    """Copy a condition into the run VM, apply it, then check it."""
    plugins.stage(run, "condition", record["name"], record["values"])
    if record.get("recording"):
        plugins.pending(run, "condition", record["name"], "remove", record["values"])
    code, output = plugins.script(run, "condition", record["name"], "apply", record["values"])
    if code:
        raise Problem(f"Condition {record['name']} did not apply: {output[-800:]}")
    check(run, record)


def check(run, record):
    """Run the condition's check in the run VM. A failed check stops everything."""
    code, output = plugins.script(run, "condition", record["name"], "check", record.get("values", {}))
    if code:
        raise Problem(f"Condition {record['name']} does not hold: {output[-800:] or f'check exit {code}'}")
    print(f"Condition {record['name']}: {output.splitlines()[-1] if output else 'holds'}")


def begin(run, records):
    """Apply the conditions of a recording. When one fails, undo each reset that is pending, then raise."""
    try:
        for each in records:
            apply(run, each)
    except BaseException:
        plugins.undo(run)
        raise
