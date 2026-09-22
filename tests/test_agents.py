"""Offline tests for the agent layer. ScriptedBackend only — no Ollama needed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from oncocs.agents.approve import approve
from oncocs.agents.graph import run_agent, UNAPPROVED_BANNER
from oncocs.agents.replay import replay_agent
from oncocs.agents.verifier import verify_draft
from oncocs.llm.recorded import (RecordedBackend, ScriptedBackend,
                                 TranscriptMismatch)

SEED = 20240601


@pytest.fixture()
def synth_results(synth_split):
    """A real results.json produced by the synthetic pipeline."""
    from tests.test_pipeline import _run
    r = _run(synth_split)
    return synth_split / "results" / "synth" / r["run_id"] / "results.json"


# ---------- verifier ----------

FLAT = {"models.cox.harrell_c": 0.6466, "models.cox.p": 0.0248,
        "n_patients": 501.0, "models.cox.auc_24m": 0.6912}
GOOD = ("## Cohort\n501 patients.\n\n## Models and metrics\nHarrell C 0.647, "
        "AUC at 24 months 0.691.\n\n## Checks and abstentions\nAll checks passed.\n\n"
        "## Limitations\nResearch only.")


def test_verifier_accepts_correct_numbers():
    assert verify_draft(GOOD, FLAT, [])["passed"]


def test_verifier_accepts_percentage():
    d = GOOD.replace("0.647", "64.7%")
    assert verify_draft(d, FLAT, [])["passed"]


def test_verifier_rejects_fabricated_number():
    d = GOOD.replace("0.647", "0.892")
    v = verify_draft(d, FLAT, [])
    assert not v["passed"] and v["unverified_numbers"]


def test_verifier_rejects_forbidden_and_missing():
    assert "outperforms" in verify_draft(GOOD + " outperforms baselines", FLAT, [])["forbidden"]
    assert "## Cohort" in verify_draft(GOOD.replace("## Cohort", "## Data"), FLAT, [])["missing_sections"]


def test_verifier_abstention_and_significant():
    checks = [{"name": "proportional_hazards", "passed": False}]
    v = verify_draft(GOOD, FLAT, checks)
    assert not v["passed"] and v["abstention_missing"]
    ok = GOOD.replace("All checks passed.",
                      "proportional_hazards failed; Cox HRs are abstained.")
    assert verify_draft(ok, FLAT, checks)["passed"]
    # 'significant' requires a verifying p-value within 40 chars
    sig_ok = GOOD + "\nThe effect was significant (p=0.0248)."
    assert verify_draft(sig_ok, FLAT, [])["passed"]
    sig_bad = GOOD + "\nThe effect was significant (p=0.9999)."
    assert not verify_draft(sig_bad, FLAT, [])["passed"]


# ---------- graph ----------

def _agent_run(root, results_path, responses, seed=SEED):
    from oncocs.llm.recorded import RecordingBackend
    backend = RecordingBackend(ScriptedBackend(responses))
    return run_agent("synth", results_path, backend, seed, root)


def _scripted_ok(results_path):
    r = json.loads(Path(results_path).read_text())
    from oncocs.agents.demo import demo_responses
    from oncocs.splits import load_split
    from oncocs.config import load_cohort
    split = load_split(load_cohort("synth", results_path.parents[3]), results_path.parents[3])
    return demo_responses(r, split)


def test_graph_passes_and_writes_banner(synth_results):
    rec = _agent_run(synth_results.parents[3], synth_results, _scripted_ok(synth_results))
    assert rec["status"] == "draft_pending_approval"
    md = (synth_results.parent / "report.md").read_text(encoding="utf-8")
    assert UNAPPROVED_BANNER in md


def test_graph_rejected_after_three_attempts(synth_results):
    bad_draft = "## Cohort\n0.99999 fabricated.\n" * 4  # unverifiable, missing sections
    responses = ["cohort text", '{"focus_models": []}',
                 bad_draft, bad_draft, bad_draft]
    rec = _agent_run(synth_results.parents[3], synth_results, responses)
    assert rec["status"] == "rejected"
    assert len(rec["drafts"]) == 3
    assert all(not d["verification"]["passed"] for d in rec["drafts"])


def test_analysis_json_fallback(synth_results):
    responses = ["cohort text", "not json at all", "still not json",
                 *_scripted_ok(synth_results)[2:]]
    rec = _agent_run(synth_results.parents[3], synth_results, responses)
    assert rec["analysis_plan_fallback"] is True


def test_modeling_node_abstains_on_tamper(synth_results, tmp_path):
    r = json.loads(synth_results.read_text())
    r["split_sha256"] = "0" * 64
    tampered = tmp_path / "results.json"
    tampered.write_text(json.dumps(r))
    rec = _agent_run(synth_results.parents[3], tampered, _scripted_ok(synth_results))
    assert rec["status"] == "abstained"


# ---------- replay ----------

def test_replay_identical_and_tamper_detected(synth_results):
    rec = _agent_run(synth_results.parents[3], synth_results, _scripted_ok(synth_results))
    run_path = synth_results.parent / "agent_run.json"
    ok, msg = replay_agent(run_path)
    assert ok, msg
    tampered = json.loads(run_path.read_text())
    tampered["transcript"][0]["prompt_sha256"] = "0" * 64
    run_path.write_text(json.dumps(tampered))
    with pytest.raises(TranscriptMismatch):
        replay_agent(run_path)


# ---------- approve ----------

def test_approve_and_tamper_refusal(synth_results):
    rec = _agent_run(synth_results.parents[3], synth_results, _scripted_ok(synth_results))
    run_path = synth_results.parent / "agent_run.json"
    approve(run_path, by="tester", note="looks right")
    md = (synth_results.parent / "report.md").read_text(encoding="utf-8")
    assert "> Approved by tester" in md and UNAPPROVED_BANNER not in md
    # editing the approved run then trying to approve again must fail
    tampered = json.loads(run_path.read_text())
    tampered.pop("approval")
    tampered["transcript"][0]["elapsed_s"] = 999
    run_path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError):
        approve(run_path, by="attacker")
