import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from proofreel import cli


def test_skill_install_copies_and_overwrites(tmp_path, capsys):
    cli.command(["skill", "install", "--to", str(tmp_path)])
    skill = tmp_path / "proofreel" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: proofreel")
    assert str(skill.parent) in capsys.readouterr().out
    skill.write_text("old")
    cli.command(["skill", "install", "--to", str(tmp_path)])
    assert skill.read_text().startswith("---\nname: proofreel")


def test_wheel_contains_the_skill(tmp_path):
    root = Path(__file__).resolve().parents[1]
    build = ["uv", "build", "--wheel", "-q", "-o", str(tmp_path), str(root)] if shutil.which("uv") else \
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(tmp_path), str(root)]
    subprocess.run(build, check=True)
    wheel = next(tmp_path.glob("proofreel-*.whl"))
    assert "proofreel/skill/SKILL.md" in zipfile.ZipFile(wheel).namelist()


def test_the_plugin_agent_hands_the_proof_to_a_small_model_with_the_skill():
    root = Path(__file__).resolve().parents[1]
    head = (root / "agents" / "proof-runner.md").read_text().split("---\n")[1]
    fields = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
    assert (fields["name"], fields["model"]) == ("proof-runner", "sonnet")
    assert "skills:\n  - proofreel" in head
    assert "name: proofreel\n" in (root / "skills" / "proofreel" / "SKILL.md").read_text()
