
def test_parse_policy_offline_mode(client, monkeypatch):
    # Unset API key to trigger fallback
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/parse-policy", json={"text": "Meals reimbursable up to $200/day per employee."})
    assert r.status_code == 200
    body = r.json()
    assert "rules" in body and isinstance(body["rules"], list)
    rule = body["rules"][0]
    for k in ["name","description","condition","threshold","unit","category","scope","applies_when","violation_message"]:
        assert k in rule
