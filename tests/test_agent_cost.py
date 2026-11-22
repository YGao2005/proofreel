import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import agent_cost  # noqa: E402


def test_filler_is_the_same_size_every_time():
    text = agent_cost.filler(2000)
    assert text == agent_cost.filler(2000)
    assert 8000 <= len(text) < 8200


def test_tally_reads_claude_json():
    out = json.dumps({"usage": {"input_tokens": 5, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900,
                                "output_tokens": 7}, "num_turns": 3, "total_cost_usd": 0.25, "result": "done"})
    assert agent_cost.tally("claude", out) == dict(new=105, out=7, cache=900, turns=3, usd=0.25, text="done")


def test_tally_reads_codex_events():
    events = [{"type": "item.completed", "item": {"type": "command_execution"}},
              {"type": "item.completed", "item": {"type": "agent_message", "text": "Verdict: works"}},
              {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 9}}]
    row = agent_cost.tally("codex", "\n".join(map(json.dumps, events)))
    assert (row["new"], row["out"], row["cache"], row["turns"], row["text"]) == (200, 9, 800, 1, "Verdict: works")


def test_review_takes_the_page_the_agent_names(tmp_path):
    session = tmp_path / "sessions" / "a-1"
    session.mkdir(parents=True)
    (session / "run.json").write_text(json.dumps({"verdict": "works"}))
    page = tmp_path / "review" / "index.html"
    page.parent.mkdir()
    page.write_text("x")
    assert agent_cost.review(tmp_path, f"Review page: {page}") == ("works", str(page))
    assert agent_cost.review(tmp_path, "no path") == ("works", str(session / "index.html"))
