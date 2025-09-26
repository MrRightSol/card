import os
import json
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.app.main import create_app


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("USE_OPENAI", "0")  # ensure offline fallback for tests
    app = create_app()
    return TestClient(app)


def test_healthz_ok(client: TestClient):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_generate_synth(client: TestClient):
    r = client.post("/generate-synth", json={"rows": 50, "seed": 42})
    assert r.status_code == 200
    data = r.json()
    assert "path" in data and os.path.exists(data["path"])  # path exists
    assert "preview" in data and isinstance(data["preview"], list)
    assert len(data["preview"]) <= 10
    assert {"amount", "category"}.issubset(data["preview"][0].keys())


def test_parse_policy_from_text(client: TestClient):
    r = client.post("/parse-policy", json={"text": "Company travel policy..."})
    assert r.status_code == 200
    data = r.json()
    assert "rules" in data and isinstance(data["rules"], list) and len(data["rules"]) >= 1
    # Validate required rule fields exist
    rule = data["rules"][0]
    for key in [
        "name",
        "description",
        "condition",
        "threshold",
        "unit",
        "category",
        "scope",
        "applies_when",
        "violation_message",
    ]:
        assert key in rule
    assert data.get("version") == "1.0"
    assert data.get("source") in {"fallback", "openai", "none", "upload"}


def test_train_and_score_flow(client: TestClient):
    # generate dataset
    gen = client.post("/generate-synth", json={"rows": 500, "seed": 1}).json()
    dataset_path = gen["path"]
    # parse rules
    rules = client.post("/parse-policy", json={"text": "Meal cap $75; Hotel $300."}).json()
    # train
    tr = client.post("/train", json={"algo": "isoforest", "max_rows": 200})
    assert tr.status_code == 200
    trd = tr.json()
    assert trd["algo"] == "isoforest"
    assert isinstance(trd.get("features"), list) and len(trd["features"]) > 0
    # score
    sc = client.post("/score", json={"dataset_path": dataset_path, "rules_json": rules})
    assert sc.status_code == 200
    out = sc.json()
    assert isinstance(out, list) and len(out) > 0
    item = out[0]
    assert {"txn_id", "amount", "category", "fraud_score", "policy"}.issubset(item.keys())
    assert isinstance(item["fraud_score"], float)
    assert isinstance(item["policy"], dict)
    assert isinstance(item["policy"].get("compliant"), bool)
    assert isinstance(item["policy"].get("violated_rules"), list)
    assert isinstance(item["policy"].get("reason"), str)
