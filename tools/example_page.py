"""Dev tool, not in the wheel: record the example review page that the README links.

    python tools/example_page.py <out folder>

It records the three Acme Notes journeys against a working server and "Search notes, tags down" against BROKEN=1,
all into one review folder, on the browser runner. Then publish the folder on the gh-pages branch as example/:
the README links https://ygao2005.github.io/proofreel/example/.
"""

import sys
from pathlib import Path

from sweep import ACME, suite


def main():
    out = Path(sys.argv[1])
    suite(ACME / "flows", out, False, "--title", "Acme Notes")
    runs = suite(ACME / "flows" / "search.flow", out, True, "--title", "Acme Notes", "--set", "TITLE=Search notes, tags down")
    (out / "runs.lock").unlink(missing_ok=True)
    for run in runs:
        print(f"{run['verdict']:8} {run['title']}")


if __name__ == "__main__":
    main()
