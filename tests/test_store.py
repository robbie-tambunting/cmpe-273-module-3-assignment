import pytest

from common.inventory_store import (
    IdempotencyConflict,
    InsufficientStock,
    InvalidQuantity,
    InventoryStore,
    ItemNotFound,
)


@pytest.fixture
def store():
    return InventoryStore({"sku-123": 5, "sku-456": 1})


def test_reserve_success_decrements_stock(store):
    r = store.reserve("sku-123", 2)
    assert (r.item_id, r.quantity) == ("sku-123", 2)
    assert r.reservation_id
    assert store.stock_of("sku-123") == 3


def test_unknown_item(store):
    with pytest.raises(ItemNotFound):
        store.reserve("nope", 1)


def test_insufficient_stock(store):
    with pytest.raises(InsufficientStock):
        store.reserve("sku-456", 2)
    assert store.stock_of("sku-456") == 1


@pytest.mark.parametrize("qty", [0, -1])
def test_invalid_quantity(store, qty):
    with pytest.raises(InvalidQuantity):
        store.reserve("sku-123", qty)


def test_idempotent_replay_reserves_once(store):
    first = store.reserve("sku-123", 2, idempotency_key="k1")
    second = store.reserve("sku-123", 2, idempotency_key="k1")
    assert first == second
    assert store.stock_of("sku-123") == 3


def test_idempotency_key_with_different_body_conflicts(store):
    store.reserve("sku-123", 2, idempotency_key="k1")
    with pytest.raises(IdempotencyConflict):
        store.reserve("sku-123", 3, idempotency_key="k1")
    assert store.stock_of("sku-123") == 3


def test_get_reservation(store):
    r = store.reserve("sku-123", 1)
    assert store.get_reservation(r.reservation_id) == r
    assert store.get_reservation("missing") is None
