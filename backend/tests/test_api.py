"""
Basic API integration tests.
Uses TestClient so no real HTTP calls are made and SQLite is in-memory.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app

# ── In-memory test DB ──────────────────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


# ── Tests ──────────────────────────────────────────────────────────────────

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_recalls_empty(client):
    resp = client.get("/api/recalls/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_listings_empty(client):
    resp = client.get("/api/listings/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0


def test_analytics_summary(client):
    resp = client.get("/api/analytics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_detected_listings" in data
    assert "active_recalls_in_db" in data


def test_import_recall(client):
    payload = {
        "product_name": "Acme Widget X200",
        "brand": "Acme Corp",
        "recall_number": "23-001",
        "product_type": "Children's Toys",
        "hazard_description": "Choking hazard",
        "is_active": True,
    }
    resp = client.post("/api/recalls/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["id"] > 0


def test_list_recalls_after_import(client):
    resp = client.get("/api/recalls/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_scan_platforms(client):
    resp = client.get("/api/scans/platforms")
    assert resp.status_code == 200
    platforms = resp.json()["platforms"]
    assert "ebay" in platforms
    assert "craigslist" in platforms


def test_esafe_status(client):
    resp = client.get("/api/esafe/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_reported" in data
    assert "pending_submission" in data


def test_analytics_by_platform(client):
    resp = client.get("/api/analytics/by-platform", params={"days": 30})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_analytics_trend(client):
    resp = client.get("/api/analytics/trend", params={"days": 7})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
