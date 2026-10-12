import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from common.inventory_store import InventoryStore
from rest_version import inventory_service, order_service


def order_client(handler):
    inv = httpx.Client(base_url="http://inventory", transport=httpx.MockTransport(handler), timeout=1)
    return TestClient(order_service.create_app(inv))


def canned(status, body):
    return order_client(lambda request: httpx.Response(status, json=body))


def test_success_201():
    body = {"reservation_id": "r1", "item_id": "sku-123", "quantity": 2}
    r = canned(201, body).post("/v1/orders", json={"item_id": "sku-123", "quantity": 2})
    assert r.status_code == 201
    assert r.json() == {"status": "confirmed", **body}


@pytest.mark.parametrize("status", [400, 404, 409])
def test_inventory_errors_pass_through(status):
    err = {"error": "x", "detail": "y"}
    r = canned(status, err).post("/v1/orders", json={"item_id": "a", "quantity": 1})
    assert r.status_code == status and r.json() == err


def test_unexpected_inventory_status_is_502():
    r = canned(500, {}).post("/v1/orders", json={"item_id": "a", "quantity": 1})
    assert r.status_code == 502


def test_invalid_order_body_400():
    assert canned(201, {}).post("/v1/orders", json={"item_id": "a"}).status_code == 400


def test_sends_auth_and_idempotency_key():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(201, json={"reservation_id": "r", "item_id": "a", "quantity": 1})

    c = order_client(handler)
    c.post("/v1/orders", json={"item_id": "a", "quantity": 1}, headers={"Idempotency-Key": "k9"})
    assert seen["authorization"] == "Bearer demo-token"
    assert seen["idempotency-key"] == "k9"


def test_timeout_is_504_and_service_survives():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    c = order_client(handler)
    r = c.post("/v1/orders", json={"item_id": "a", "quantity": 1})
    assert r.status_code == 504 and r.json()["error"] == "inventory_timeout"
    assert c.get("/health").status_code == 200


def test_connect_error_is_503():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    r = order_client(handler).post("/v1/orders", json={"item_id": "a", "quantity": 1})
    assert r.status_code == 503


def test_real_slow_inventory_times_out_then_recovers():
    """Real HTTP: inventory sleeps longer than the Order client's timeout."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    store = InventoryStore({"sku-123": 5})
    server = uvicorn.Server(uvicorn.Config(
        inventory_service.create_app(store, delay=1.0),
        host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        inv = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=0.3)
        c = TestClient(order_service.create_app(inv))
        assert c.post("/v1/orders", json={"item_id": "sku-123", "quantity": 1}).status_code == 504
        assert c.get("/health").status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=5)
