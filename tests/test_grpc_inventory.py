import grpc
import pytest

from common import config
from common.inventory_store import InventoryStore
from grpc_version import inventory_pb2, inventory_pb2_grpc
from grpc_version.inventory_server import create_server

AUTH = (("authorization", f"Bearer {config.INVENTORY_API_TOKEN}"),)


@pytest.fixture
def stub():
    server, port = create_server(0, InventoryStore({"sku-123": 5, "sku-456": 1}))
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    yield inventory_pb2_grpc.InventoryServiceStub(channel)
    channel.close()
    server.stop(None)


def reserve(stub, item_id="sku-123", quantity=1, key="", metadata=AUTH):
    req = inventory_pb2.ReserveRequest(item_id=item_id, quantity=quantity, idempotency_key=key)
    return stub.ReserveInventory(req, timeout=5, metadata=metadata)


def code_of(stub, **kwargs):
    with pytest.raises(grpc.RpcError) as exc:
        reserve(stub, **kwargs)
    return exc.value.code()


def test_success(stub):
    r = reserve(stub, quantity=2)
    assert r.item_id == "sku-123" and r.quantity == 2 and r.reservation_id


def test_unknown_item_not_found(stub):
    assert code_of(stub, item_id="nope") == grpc.StatusCode.NOT_FOUND


def test_insufficient_stock_failed_precondition(stub):
    assert code_of(stub, item_id="sku-456", quantity=2) == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.parametrize("qty", [0, -1])
def test_invalid_quantity(stub, qty):
    assert code_of(stub, quantity=qty) == grpc.StatusCode.INVALID_ARGUMENT


def test_missing_or_bad_auth_unauthenticated(stub):
    assert code_of(stub, metadata=()) == grpc.StatusCode.UNAUTHENTICATED
    assert code_of(stub, metadata=(("authorization", "Bearer wrong"),)) == grpc.StatusCode.UNAUTHENTICATED


def test_idempotent_replay_returns_same_reservation(stub):
    a = reserve(stub, item_id="sku-456", quantity=1, key="k1")
    b = reserve(stub, item_id="sku-456", quantity=1, key="k1")
    assert a.reservation_id == b.reservation_id


def test_idempotency_key_conflict_already_exists(stub):
    reserve(stub, quantity=1, key="k2")
    assert code_of(stub, quantity=2, key="k2") == grpc.StatusCode.ALREADY_EXISTS
