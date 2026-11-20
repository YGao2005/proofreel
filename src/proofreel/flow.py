"""Flow files: one proofreel command on each line.

`#` starts a comment. `${NAME}` and `${NAME:-default}` take their values from `--set NAME=VALUE`. A line
`condition <name>` says that the run VM's state must have that condition; for a condition that lasts one recording,
`condition <name>[:KEY=VALUE,...]` applies it with the flow's `start`. A line `probe <name>[:KEY=VALUE,...]` adds
a probe to the flow's recording. Every line is read and parsed before the
first one runs, so a typo stops the flow before it changes anything. A line `state <name>` says where the app should
be; the waits and checks after it prove it (see session.visits). A failed check is recorded and the flow goes
on. Any other failure stops the flow.
"""

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import Problem

VALUE = re.compile(r"\$\{(?P<name>\w+)(?::-(?P<default>[^}]*))?\}")


@dataclass
class Flow:
    name: str
    lines: list = field(default_factory=list)
    conditions: list = field(default_factory=list)
    probes: list = field(default_factory=list)


def expand(line, values):
    def value(match):
        if match["name"] in values:
            return values[match["name"]]
        if match["default"] is not None:
            return match["default"]
        raise Problem(f"No value for ${{{match['name']}}}. Pass --set {match['name']}=...")
    return VALUE.sub(value, line)


def load(path, values, parse):
    """The flow's command lines as (line number, words), each checked with parse(words) before any runs."""
    path = Path(path)
    flow = Flow(path.name)
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        try:
            words = shlex.split(expand(raw, values), comments=True)
            if words and words[0] in ("condition", "probe"):
                if len(words) != 2:
                    raise Problem(f"Write one {words[0]} on each line: {words[0]} <name>.")
                (flow.conditions if words[0] == "condition" else flow.probes).append(words[1])
            elif words:
                parse(words)
                flow.lines.append((number, words))
        except (Problem, ValueError) as problem:
            raise Problem(f"{path.name}:{number}: {problem}") from None
    return flow


def run(flow, execute, abort):
    """Run each line with execute(words), which returns 1 for a failed check. Returns 1 when a check failed. Any
    other failure calls abort(message), so a recording stops with the line that failed, and then raises."""
    failed = 0
    for number, words in flow.lines:
        where = f"{flow.name}:{number}: {shlex.join(words)}"
        print(where)
        try:
            code = execute(words) or 0
        except BaseException as error:
            abort(f"{where}: {error}")
            raise
        if code and words[0] not in ("check", "stop"):
            abort(f"{where}: exit {code}")
            raise Problem(f"{where} failed (exit {code}).")
        failed |= code
    return failed
