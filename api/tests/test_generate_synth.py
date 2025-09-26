
import json
from pathlib import Path

def test_generate_synth_contract(client):  # assumes a pytest fixture 'client' (httpx TestClient)
    r = client.post("/generate-synth", json={"rows": 1000, "seed": 42})
    assert r.status_code == 200
    body = r.json()
    assert "path" in body and "preview" in body
    assert isinstance(body["preview"], list) and len(body["preview"]) > 0
    # minimal schema check
    row = body["preview"][0]
    expected_cols = {"txn_id","employee_id","merchant","city","category","timestamp","amount","channel","card_id"}
    assert expected_cols.issubset(set(row.keys()))
