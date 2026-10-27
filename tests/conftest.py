# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures_synthetic"
TEST_TOKEN = "t" * 40


@pytest.fixture
def personas():
    data = json.loads((FIXTURES / "personas.json").read_text(encoding="utf-8"))
    return {p["id"]: p for p in data["personas"]}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.agent_api import create_app

    return TestClient(create_app(token=TEST_TOKEN, data_dir=FIXTURES))


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
