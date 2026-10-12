import pytest
from fastapi.testclient import TestClient

from common import config
from common.inventory_store import InventoryStore
from rest_version.inventory_service import create_app

AUTH = {"Authorization": f"Bearer {config.INVENTORY_API_TOKEN}"}


@pytest.fixture
def client():
    return TestClient(create_app(InventoryStore({"sku-123": 5, "sku-456": 1})))


def post(client, body, headers=AUTH):
    return client.post("/v1/reservations", json=body, headers=headers)


def test_success_201(client):
    r = post(client, {"item_id": "sku-123", "quantity": 2})
    assert r.status_code == 201
    body = r.json()
    assert body["quantity"] == 2 and body["item_id"] == "sku-123" and body["reservation_id"]


def test_unknown_item_404(client):
    assert post(client, {"item_id": "nope", "quantity": 1}).status_code == 404


def test_insufficient_stock_409(client):
    r = post(client, {"item_id": "sku-456", "quantity": 2})
    assert r.status_code == 409
    assert r.json()["error"] == "insufficient_stock"


@pytest.mark.parametrize("body", [
    {"item_id": "sku-123", "quantity": 0},
    {"item_id": "sku-123", "quantity": -3},
    {"item_id": "sku-123", "quantity": "abc"},
    {"item_id": "sku-123"},
])
def test_invalid_input_400(client, body):
    assert post(client, body).status_code == 400


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_unauthorized_401(client, headers):
    assert post(client, {"item_id": "sku-123", "quantity": 1}, headers).status_code == 401


def test_idempotent_replay_returns_same_reservation(client):
    h = {**AUTH, "Idempotency-Key": "abc"}
    a = post(client, {"item_id": "sku-456", "quantity": 1}, h)
    b = post(client, {"item_id": "sku-456", "quantity": 1}, h)
    assert a.status_code == b.status_code == 201
    assert a.json() == b.json()


def test_idempotency_key_conflict_422(client):
    h = {**AUTH, "Idempotency-Key": "abc"}
    post(client, {"item_id": "sku-123", "quantity": 1}, h)
    assert post(client, {"item_id": "sku-123", "quantity": 2}, h).status_code == 422


def test_get_reservation(client):
    created = post(client, {"item_id": "sku-123", "quantity": 1}).json()
    got = client.get(f"/v1/reservations/{created['reservation_id']}", headers=AUTH)
    assert got.status_code == 200 and got.json() == created
    assert client.get("/v1/reservations/missing", headers=AUTH).status_code == 404
