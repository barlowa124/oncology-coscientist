"""CLI entry-point tests on the synthetic fixture."""
from __future__ import annotations

import json

from oncocs.cli import main
from tests.test_agents import (
    synth_results as synth_results,  # re-export: registers the fixture
)


def _argv(root, *rest):
    return ["--data-dir", str(root), *rest]


def test_verify_pass_and_tamper_fail(synth_results):
    root = synth_results.parents[3]
    assert main(_argv(root, "verify", str(synth_results))) == 0

    tampered = json.loads(synth_results.read_text())
    tampered["n_patients"] += 1
    synth_results.write_text(json.dumps(tampered, indent=2))
    assert main(_argv(root, "verify", str(synth_results))) == 1


def test_qc_and_agent_summarize(synth_results):
    from tests.test_agents import _agent_run, _scripted_ok

    root = synth_results.parents[3]
    assert main(_argv(root, "qc", "--cohort", "synth")) == 0

    rec = _agent_run(root, synth_results, _scripted_ok(synth_results))
    assert main(_argv(root, "agent", "summarize")) == 0
    out = root / "results" / "agent_model_comparison.json"
    runs = json.loads(out.read_text())["runs"]
    assert any(r["agent_run_id"] == rec["agent_run_id"] for r in runs)


def test_agent_replay_and_cli_approve_reject(synth_results):
    from tests.test_agents import _agent_run, _run_path, _scripted_ok

    root = synth_results.parents[3]
    rec = _agent_run(root, synth_results, _scripted_ok(synth_results))
    run_path = _run_path(synth_results, rec)

    assert main(_argv(root, "agent", "replay", str(run_path))) == 0
    assert main(_argv(root, "approve", str(run_path), "--by", "cli-tester")) == 0
    record = json.loads(run_path.read_text())
    assert record["approval"]["by"] == "cli-tester"
    # second decision on the same run must fail closed
    assert main(_argv(root, "reject", str(run_path),
                      "--by", "x", "--reason", "late")) == 1
