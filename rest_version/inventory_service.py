"""REST Inventory Service: POST /v1/reservations."""

import argparse
import logging
import time
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common import config
from common.inventory_store import (
    IdempotencyConflict,
    InsufficientStock,
    InvalidQuantity,
    InventoryStore,
    ItemNotFound,
)

log = logging.getLogger("inventory")


class ReservationRequest(BaseModel):
    item_id: str
    quantity: int


class ApiError(Exception):
    def __init__(self, status, code, detail):
        self.status, self.code, self.detail = status, code, detail


def _error(status, code, detail):
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def create_app(store=None, delay=0.0):
    app = FastAPI(title="Inventory Service (REST)")
    store = store or InventoryStore()

    def require_caller(authorization: Optional[str] = Header(default=None)):
        if authorization != f"Bearer {config.INVENTORY_API_TOKEN}":
            raise ApiError(401, "unauthorized", "missing or invalid bearer token")

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # The contract says invalid input is 400, not FastAPI's default 422.
        return _error(400, "invalid_request", str(exc.errors()))

    @app.post("/v1/reservations", status_code=201, dependencies=[Depends(require_caller)])
    def create_reservation(
        body: ReservationRequest,
        idempotency_key: Optional[str] = Header(default=None),
    ):
        if delay > 0:
            log.info("simulating slow inventory: sleeping %.1fs", delay)
            time.sleep(delay)
        try:
            r = store.reserve(body.item_id, body.quantity, idempotency_key)
        except InvalidQuantity as e:
            raise ApiError(400, "invalid_quantity", str(e))
        except ItemNotFound as e:
            raise ApiError(404, "item_not_found", str(e))
        except InsufficientStock as e:
            raise ApiError(409, "insufficient_stock", str(e))
        except IdempotencyConflict as e:
            raise ApiError(422, "idempotency_key_conflict", str(e))
        log.info("reserved %s x%d -> %s", r.item_id, r.quantity, r.reservation_id)
        return {"reservation_id": r.reservation_id, "item_id": r.item_id, "quantity": r.quantity}

    @app.get("/v1/reservations/{reservation_id}", dependencies=[Depends(require_caller)])
    def get_reservation(reservation_id: str):
        r = store.get_reservation(reservation_id)
        if r is None:
            raise ApiError(404, "reservation_not_found", f"unknown reservation {reservation_id}")
        return {"reservation_id": r.reservation_id, "item_id": r.item_id, "quantity": r.quantity}

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="REST Inventory Service")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to sleep before handling each reservation")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s inventory %(message)s")
    uvicorn.run(create_app(delay=args.delay), host="127.0.0.1", port=config.INVENTORY_REST_PORT)
