import pytest

from proofreel import Problem, guest, plugins


def make(root, name):
    folder = root / "conditions" / name
    folder.mkdir(parents=True)
    (folder / "condition.toml").write_text(f'name = "{name}"\n')
    return folder


def test_the_project_then_home_then_built_in_wins_and_known_says_where(tmp_path, monkeypatch):
    project, home = tmp_path / "app" / ".proofreel", tmp_path / "home"
    make(project, "offline")
    make(home, "offline")
    make(home, "slow-disk")
    monkeypatch.chdir(tmp_path / "app")
    monkeypatch.setattr(plugins, "HOME", home)
    assert plugins.find("condition", "offline") == project / "conditions" / "offline"
    known = plugins.known("condition")
    assert known["offline"] == "project" and known["slow-disk"] == "home" and known["no-microphone"] == ""
    assert plugins.find("condition", str(home / "conditions" / "slow-disk")) == home / "conditions" / "slow-disk"
    with pytest.raises(Problem, match="No condition 'gone'"):
        plugins.find("condition", "gone")


def test_each_system_runs_a_step_its_own_way():
    mac, windows = guest.GUESTS["macos"], guest.GUESTS["windows"]
    assert mac.run_script("/Users/Shared/proofreel/conditions/x", "check", {"RATE": "24000"}) == \
        "cd /Users/Shared/proofreel/conditions/x && RATE=24000 sh check.sh"
    command = windows.run_script("C:/ProgramData/proofreel/conditions/x", "apply", {"NAME": "it's"})
    assert command.startswith("powershell -NoProfile") and "$env:NAME = 'it''s'; & .\\apply.ps1" in command
    assert windows.script("apply") == "apply.ps1" and mac.script("apply") == "apply.sh"
