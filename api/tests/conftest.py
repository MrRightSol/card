import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure project root is on sys.path when running `pytest api/tests`
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.main import create_app


@pytest.fixture(scope="session")
def client():
    os.environ.setdefault("USE_OPENAI", "0")
    app = create_app()
    return TestClient(app)
