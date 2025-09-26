import json
from fastapi.testclient import TestClient
from api.app.main import create_app


def test_parse_policy_upload_json():
    app = create_app()
    client = TestClient(app)
    payload = {
        "rules": [
            {
                "name": "Custom Meal Cap",
                "description": "Meals up to 60",
                "condition": "category == 'Meals' and amount > 60",
                "threshold": 60,
                "unit": "USD",
                "category": "Meals",
                "scope": "per txn",
                "applies_when": "business",
                "violation_message": "Too high",
            }
        ]
    }
    # send the JSON as the file content directly (TestClient accepts a string here)
    file_content = json.dumps(payload)
    r = client.post("/parse-policy", files={"policy": ("rules.json", file_content, "application/json")})
    assert r.status_code == 200
    data = r.json()
    assert "rules" in data and len(data["rules"]) == 1
    assert data.get("version") == "1.0"
    assert data.get("source") == "rules.json"
