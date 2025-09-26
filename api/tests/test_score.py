
def test_score_contract(client):
    # Generate small dataset then score
    gen = client.post("/generate-synth", json={"rows": 2000, "seed": 123}).json()
    payload = {"dataset_path": gen["path"]}
    r = client.post("/score", json=payload)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and len(items) > 0
    row = items[0]
    assert 0.0 <= row["fraud_score"] <= 1.0
    assert "policy" in row and "compliant" in row["policy"]
