import json
import shutil
import subprocess

import pytest

from proofreel import Problem, cli, conditions, page, plugins, recording, vm

FOLDER = plugins.find("condition", "slow-network")
INFO = plugins.manifest("condition", FOLDER)
STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
case "$(basename "$0") $*" in
  "uname ") echo "$SYSTEM" ;;
  "ip route show default") echo "default via 10.0.2.2 dev enp0s4 proto dhcp src 10.0.2.15" ;;
  "pfctl -E") echo "Token : 4242" >&2 ;;
  "ip link show"*) exit 1 ;;
esac
"""


def run_step(tmp_path, step, system="Linux", **given):
    """Run a step of slow-network on the host, with sudo, uname, ip, tc, pfctl, and dnctl as stubs that log each call."""
    folder, bin_ = tmp_path / "slow-network", tmp_path / "bin"
    if not folder.exists():
        shutil.copytree(FOLDER, folder)
        bin_.mkdir()
        for tool in ("uname", "ip", "tc", "pfctl", "dnctl"):
            (bin_ / tool).write_text(STUB)
            (bin_ / tool).chmod(0o755)
        (bin_ / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
        (bin_ / "sudo").chmod(0o755)
    log = tmp_path / "log"
    log.write_text("")
    values = plugins.resolve(INFO, given)
    done = subprocess.run(["sh", f"{step}.sh"], cwd=folder, capture_output=True, text=True,
                          env={"PATH": f"{bin_}:/usr/bin:/bin", "LOG": str(log), "SYSTEM": system, **values})
    calls = [line for line in log.read_text().splitlines() if line != "uname " and " show" not in line]
    return done.returncode, done.stdout + done.stderr, calls


def test_a_profile_gives_its_values_and_a_given_value_replaces_the_profiles():
    assert plugins.resolve(INFO, {}) == {"profile": "3g", "latency": "300ms", "jitter": "50ms", "loss": "1%",
                                         "rate": "1mbit"}
    assert plugins.resolve(INFO, {"profile": "edge", "loss": "5%"})["loss"] == "5%"
    assert plugins.resolve(INFO, {"profile": "none", "latency": "200ms"}) == {
        "profile": "none", "latency": "200ms", "jitter": "0ms", "loss": "0%", "rate": "0"}
    with pytest.raises(Problem, match="no profile '5g'. Known: 3g, edge, lossy-wifi, none"):
        plugins.resolve(INFO, {"profile": "5g"})


def test_a_manifest_with_profiles_needs_a_profile_value_and_known_names(tmp_path):
    path = tmp_path / "x"
    shutil.copytree(FOLDER, path)
    text = (path / "condition.toml").read_text().replace('"slow-network"', '"x"')
    (path / "condition.toml").write_text(text.replace('3g = { latency', '3g = { latnecy'))
    with pytest.raises(ValueError, match="latnecy"):
        plugins.manifest("condition", path)
    (path / "condition.toml").write_text(text.replace('profile = "3g"\n', ""))
    with pytest.raises(ValueError, match="no value profile"):
        plugins.manifest("condition", path)
    (path / "condition.toml").write_text(text)
    (path / "remove.sh").unlink()
    with pytest.raises(ValueError, match="remove.sh"):
        plugins.manifest("condition", path)


def test_linux_shapes_each_way_with_netem_and_leaves_ssh_alone(tmp_path):
    code, output, calls = run_step(tmp_path, "apply")
    assert code == 0, output
    netem = "netem delay 150ms 25ms loss 1% rate 1000kbit"
    assert calls[:3] == ["tc qdisc del dev enp0s4 clsact", "ip link del proofreel-down", "ip link del proofreel-up"]
    assert calls[3:] == [
        "ip link add proofreel-down type ifb", "ip link set proofreel-down up",
        f"tc qdisc add dev proofreel-down root {netem}",
        "ip link add proofreel-up type ifb", "ip link set proofreel-up up", f"tc qdisc add dev proofreel-up root {netem}",
        "tc qdisc add dev enp0s4 clsact",
        "tc filter add dev enp0s4 ingress prio 1 protocol ip flower ip_proto tcp dst_port 22 action pass",
        "tc filter add dev enp0s4 ingress prio 2 matchall action mirred egress redirect dev proofreel-down",
        "tc filter add dev enp0s4 egress prio 1 protocol ip flower ip_proto tcp src_port 22 action pass",
        "tc filter add dev enp0s4 egress prio 2 matchall action mirred egress redirect dev proofreel-up"]


def test_a_zero_value_is_left_out_and_odd_numbers_halve(tmp_path):
    code, output, calls = run_step(tmp_path, "apply", profile="none", latency="75", rate="2.5mbit")
    assert code == 0, output
    assert "tc qdisc add dev proofreel-up root netem delay 37.5ms rate 2500kbit" in calls


@pytest.mark.parametrize("name, value", [("latency", "fast"), ("jitter", "5s"), ("loss", "five%"), ("rate", "1gbps"),
                                         ("loss", "1.2.3%")])
def test_a_bad_value_stops_apply_before_anything_changes(tmp_path, name, value):
    code, output, calls = run_step(tmp_path, "apply", **{name: value})
    assert code == 2 and f"{name}={value}" in output and calls == []


def test_remove_works_when_nothing_was_applied(tmp_path):
    code, output, _ = run_step(tmp_path, "remove", latency="fast")
    assert code == 0 and "Not shaped" in output


def test_macos_shapes_each_way_with_dummynet_pipes_in_a_pf_anchor(tmp_path):
    code, output, calls = run_step(tmp_path, "apply", system="Darwin", profile="edge")
    assert code == 0, output
    shaping = "delay 400 plr 0.02 bw 200Kbit/s"
    assert calls[-4:] == [f"dnctl pipe 47001 config {shaping}", f"dnctl pipe 47002 config {shaping}",
                          "pfctl -q -a com.apple/proofreel-slow-network -f -", "pfctl -E"]
    assert (tmp_path / "slow-network" / "token").read_text() == "4242\n"
    code, output, calls = run_step(tmp_path, "remove", system="Darwin")
    assert "pfctl -X 4242" in calls and not (tmp_path / "slow-network" / "token").exists()


def test_a_recording_condition_is_refused_in_a_state_and_a_state_condition_at_start():
    with pytest.raises(Problem, match="lasts one recording"):
        conditions.record("slow-network", {}, "linux", recording=False)
    with pytest.raises(Problem, match="kept in a state"):
        conditions.record("offline", {}, "macos", recording=True)
    assert conditions.record(*plugins.spec("slow-network:profile=edge,loss=5%"), "linux", recording=True) == {
        "name": "slow-network", "version": 1, "recording": True,
        "values": {"profile": "edge", "latency": "800ms", "jitter": "100ms", "loss": "5%", "rate": "200kbit"}}


def test_a_flow_line_applies_a_recording_condition_at_start(home, tmp_path, monkeypatch):
    vm.CURRENT.write_text(json.dumps({"state": "plain", "conditions": []}))
    ran = []
    monkeypatch.setattr(cli, "command", lambda words: ran.append(words))
    path = tmp_path / "f.flow"
    path.write_text("condition slow-network:profile=edge\nstart x\nnote hello\n")
    cli.run_flow(path, {})
    assert ran == [["start", "x", "--condition=slow-network:profile=edge"], ["note", "hello"]]
    path.write_text("condition slow-network:profile=5g\nstart x\n")
    with pytest.raises(Problem, match="no profile '5g'"):
        cli.run_flow(path, {})


class FakeRun(dict):
    guest = None


def test_a_failed_apply_undoes_what_is_pending(home, monkeypatch):
    vm.CURRENT.write_text(json.dumps({"id": "r", "os": "linux", "state": "s", "conditions": []}))
    calls = []
    monkeypatch.setattr(plugins, "stage", lambda *a: calls.append("stage"))
    monkeypatch.setattr(plugins, "script", lambda run, kind, name, step, values, **k:
                        (calls.append(step) or (1 if step == "apply" else 0), "tc: no netem"))
    record = conditions.record("slow-network", {}, "linux", recording=True)
    with pytest.raises(Problem, match="did not apply: tc: no netem"):
        conditions.begin(FakeRun(), [record])
    assert calls == ["stage", "apply", "remove"]
    assert json.loads(vm.CURRENT.read_text())["pending"] == []


def test_undo_runs_a_condition_remove_then_a_probe_stop_and_clears_the_list(home, monkeypatch):
    vm.CURRENT.write_text(json.dumps({"id": "r", "os": "linux", "state": "s", "conditions": []}))
    run = FakeRun()
    plugins.pending(run, "probe", "network", "stop", {"A": "1"})
    plugins.pending(run, "condition", "slow-network", "remove", {"B": "2"})
    ran = []
    monkeypatch.setattr(plugins, "script", lambda run, kind, name, step, values, **k:
                        (ran.append((kind, name, step, values)) or (0, "Not shaped.\ndone")))
    results = plugins.undo(run)
    assert ran == [("condition", "slow-network", "remove", {"B": "2"}), ("probe", "network", "stop", {"A": "1"})]
    assert [(e["name"], ok, said) for e, ok, said in results] == [("slow-network", True, "done"), ("network", True, "done")]
    assert json.loads(vm.CURRENT.read_text())["pending"] == []


def test_stop_removes_a_recording_condition_and_the_page_says_its_values(home, monkeypatch):
    folder = recording.SESSIONS / "x"
    folder.mkdir(parents=True)
    record = conditions.record("slow-network", {}, "linux", recording=True)
    (folder / "session.json").write_text(json.dumps({"run": "r", "conditions": [record]}))
    recording.POINTER.write_text(json.dumps({"dir": str(folder), "pid": 999999}))
    vm.CURRENT.write_text(json.dumps({"id": "r", "os": "linux", "state": "s", "conditions": [], "pending": [
        {"kind": "condition", "name": "slow-network", "script": "remove", "values": record["values"]}]}))
    (folder / "frames").mkdir()
    monkeypatch.setattr(vm.Run, "guest", property(lambda self: type("G", (), {"harvest": lambda *a: []})()))
    monkeypatch.setattr(plugins, "script", lambda run, kind, name, step, values, **k: (0, "Not shaped: enp0s4."))
    monkeypatch.setattr("proofreel.render.render", lambda folder, **k: "rendered")
    assert recording.stop() == "rendered"
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    assert [(e["text"], e["ok"], e["detail"]) for e in events] == [("slow-network is removed", True, "Not shaped: enp0s4.")]
    assert page.condition(record) == "slow-network (profile=3g latency=300ms jitter=50ms loss=1% rate=1mbit)"
    assert page.condition({"name": "run-from-dmg", "values": {"DMG": "/Users/me/x.dmg"}}) == "run-from-dmg"
