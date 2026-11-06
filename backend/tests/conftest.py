import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp}/test.db", DATA_DIR=_tmp, SEED_ON_START="false",
                  JWT_SECRET="test-secret-not-for-production", DEMO_PASSWORD="test-pass-123", ANTHROPIC_API_KEY="")

import pytest
from fastapi.testclient import TestClient

from app import db, service
from app.main import app


@pytest.fixture(scope="session")
def client():
    db.init_db()
    service.seed_demo(1500)
    with TestClient(app) as c:
        yield c


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "test-pass-123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def exec_h(client):
    return _login(client, "finance@companya.test")


@pytest.fixture(scope="session")
def cofounder_h(client):
    return _login(client, "cofounder@companya.test")
