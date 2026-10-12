"""Thread-safe in-memory inventory shared by the REST and gRPC versions."""

import threading
import uuid
from dataclasses import dataclass


class InventoryError(Exception):
    """Base class for domain errors."""


class InvalidQuantity(InventoryError):
    pass


class ItemNotFound(InventoryError):
    pass


class InsufficientStock(InventoryError):
    pass


class IdempotencyConflict(InventoryError):
    """Same idempotency key reused with a different request body."""


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    item_id: str
    quantity: int


class InventoryStore:
    def __init__(self, stock=None):
        self._lock = threading.Lock()
        self._stock = dict(stock) if stock is not None else {
            "sku-123": 5,
            "sku-456": 1,  # only one unit left: demos 409
            "sku-789": 0,
        }
        self._reservations = {}  # reservation_id -> Reservation
        self._by_key = {}  # idempotency_key -> Reservation

    def reserve(self, item_id, quantity, idempotency_key=None):
        with self._lock:
            if idempotency_key is not None and idempotency_key in self._by_key:
                prior = self._by_key[idempotency_key]
                if (prior.item_id, prior.quantity) != (item_id, quantity):
                    raise IdempotencyConflict(
                        "idempotency key was already used with a different request"
                    )
                return prior

            if quantity < 1:
                raise InvalidQuantity("quantity must be at least 1")
            if item_id not in self._stock:
                raise ItemNotFound(f"unknown item {item_id}")
            if self._stock[item_id] < quantity:
                raise InsufficientStock(
                    f"requested {quantity} of {item_id}, only {self._stock[item_id]} left"
                )

            self._stock[item_id] -= quantity
            reservation = Reservation(str(uuid.uuid4()), item_id, quantity)
            self._reservations[reservation.reservation_id] = reservation
            if idempotency_key is not None:
                self._by_key[idempotency_key] = reservation
            return reservation

    def get_reservation(self, reservation_id):
        with self._lock:
            return self._reservations.get(reservation_id)

    def stock_of(self, item_id):
        with self._lock:
            return self._stock.get(item_id)
