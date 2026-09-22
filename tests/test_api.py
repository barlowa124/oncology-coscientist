"""API tests on the synthetic fixture (TestClient, no server needed)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from oncocs.api.app import create_app
from tests.test_agents import (
    _agent_run,
    _scripted_ok,
)
from tests.test_agents import (
    synth_results as synth_results,  # re-export: registers the fixture
)


@pytest.fixture()
def client(synth_results):
    root = synth_results.parents[3]
    rec = _agent_run(root, synth_results, _scripted_ok(synth_results))
    app = create_app(root)
    c = TestClient(app)
    c.synth = {"root": root, "results": synth_results, "rec": rec,
               "run_id": synth_results.parent.name}
    return c


def test_list_and_get(client):
    assert "synth" in client.get("/cohorts").json()
    runs = client.get("/runs").json()
    assert any(r["run_id"] == client.synth["run_id"] for r in runs)
    detail = client.get(f"/runs/synth/{client.synth['run_id']}").json()
    assert detail["cohort"] == "synth"
    agents = client.get(f"/runs/synth/{client.synth['run_id']}/agent").json()
    assert agents[0]["agent_run_id"] == client.synth["rec"]["agent_run_id"]
    aid = agents[0]["agent_run_id"]
    rep = client.get(f"/agent/synth/{client.synth['run_id']}/{aid}/report")
    assert rep.status_code == 200 and "UNAPPROVED" in rep.text
    aj = client.get(f"/agent/synth/{client.synth['run_id']}/{aid}/agent_run")
    assert aj.status_code == 200


def test_approve_and_conflicts(client):
    aid = client.synth["rec"]["agent_run_id"]
    base = f"/agent/synth/{client.synth['run_id']}/{aid}"
    r = client.post(base + "/approve", json={"by": "tester", "note": "ok"})
    assert r.status_code == 200
    assert client.post(base + "/approve", json={"by": "x"}).status_code == 409
    assert client.post(base + "/reject",
                       json={"by": "x", "reason": "late"}).status_code == 409
