import time

import pytest

from proofreel import chrome, screen, vm
from test_web import PAGE


def attempt(runs, tmp_path, strategy, name):
    (tmp_path / "page.html").write_text(PAGE)
    first = vm.up("web")
    url = (tmp_path / "page.html").as_uri()
    with screen.connect(first["screen"]) as web:
        web.open(url)
        web.call("Runtime.evaluate", expression="localStorage.setItem('user', 'guest')")
        strategy(web)
    t0 = time.time()
    vm.save(name)
    took = time.time() - t0
    second = vm.up(name)
    with screen.connect(second["screen"]) as web:
        web.open(url)
        got = web.call("Runtime.evaluate", expression="localStorage.getItem('user')", returnByValue=True)["result"].get("value")
    vm.down()
    print("DEBUGRESULT", name, got, took, flush=True)
    return got


def test_strategies(runs, tmp_path):
    results = {}
    results["none"] = attempt(runs, tmp_path, lambda w: None, "s-none")
    results["sleep1"] = attempt(runs, tmp_path, lambda w: time.sleep(1), "s-sleep1")
    results["sleep6"] = attempt(runs, tmp_path, lambda w: time.sleep(6), "s-sleep6")
    results["blank"] = attempt(runs, tmp_path, lambda w: w.open("about:blank"), "s-blank")
    print("DEBUGRESULT", results, flush=True)
    assert False
