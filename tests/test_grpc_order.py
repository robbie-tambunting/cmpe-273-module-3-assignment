import grpc
import pytest
from fastapi.testclient import TestClient

from common import config
from common.inventory_store import InventoryStore
from grpc_version import inventory_pb2_grpc, order_service
from grpc_version.inventory_server import create_server

ORDER = {"item_id": "sku-123", "quantity": 1}


@pytest.fixture
def make_client():
    cleanup = []

    def _make(delay=0.0, port=None):
        store = InventoryStore({"sku-123": 5, "sku-456": 1})
        server, bound = create_server(port or 0, store, delay)
        server.start()
        channel = grpc.insecure_channel(f"127.0.0.1:{bound}")
        cleanup.append((server, channel))
        stub = inventory_pb2_grpc.InventoryServiceStub(channel)
        return TestClient(order_service.create_app(stub)), server

    yield _make
    for server, channel in cleanup:
        channel.close()
        server.stop(None)


def test_success_201(make_client):
    client, _ = make_client()
    r = client.post("/v1/orders", json=ORDER)
    assert r.status_code == 201
    assert r.json()["status"] == "confirmed" and r.json()["reservation_id"]


@pytest.mark.parametrize("body,status,grpc_status", [
    ({"item_id": "nope", "quantity": 1}, 404, "NOT_FOUND"),
    ({"item_id": "sku-456", "quantity": 2}, 409, "FAILED_PRECONDITION"),
    ({"item_id": "sku-123", "quantity": 0}, 400, "INVALID_ARGUMENT"),
])
def test_inventory_errors_mapped(make_client, body, status, grpc_status):
    client, _ = make_client()
    r = client.post("/v1/orders", json=body)
    assert r.status_code == status
    assert r.json()["grpc_status"] == grpc_status


def test_invalid_order_body_400(make_client):
    client, _ = make_client()
    assert client.post("/v1/orders", json={"item_id": "a"}).status_code == 400


def test_deadline_exceeded_is_504_and_service_survives(make_client, monkeypatch):
    monkeypatch.setattr(config, "INVENTORY_DEADLINE_SECONDS", 0.3)
    client, server = make_client(delay=1.0)
    r = client.post("/v1/orders", json=ORDER)
    assert r.status_code == 504
    assert r.json()["grpc_status"] == "DEADLINE_EXCEEDED"
    # Order service still answers.
    assert client.get("/health").status_code == 200
    # Recovery: next request succeeds once inventory is fast again.
    server.stop(None).wait()
    monkeypatch.setattr(config, "INVENTORY_DEADLINE_SECONDS", 2.0)
    fast_client, _ = make_client(delay=0.0)
    assert fast_client.post("/v1/orders", json=ORDER).status_code == 201


def test_inventory_down_is_503_and_service_survives():
    channel = grpc.insecure_channel("127.0.0.1:1")  # nothing listening
    client = TestClient(order_service.create_app(inventory_pb2_grpc.InventoryServiceStub(channel)))
    r = client.post("/v1/orders", json=ORDER)
    assert r.status_code == 503 and r.json()["grpc_status"] == "UNAVAILABLE"
    assert client.get("/health").status_code == 200
    channel.close()
