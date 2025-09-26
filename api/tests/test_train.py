
import time

def test_train_is_fast(client):
    r = client.post("/train", json={"algo":"isoforest","max_rows": 5000})
    assert r.status_code == 200
    body = r.json()
    assert body["algo"] == "isoforest"
    assert body["fit_seconds"] < 10.0
    assert isinstance(body["features"], list) and len(body["features"]) > 0
