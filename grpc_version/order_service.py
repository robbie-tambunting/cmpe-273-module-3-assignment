"""gRPC Order Service: POST /v1/orders -> Inventory Service over gRPC.

Same HTTP front door as the REST version; only the Order -> Inventory hop differs.
"""

import logging
import os
import uuid
from typing import Optional

import grpc
import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common import config
from grpc_version import inventory_pb2, inventory_pb2_grpc

log = logging.getLogger("order")

INVENTORY_TARGET = f"127.0.0.1:{config.INVENTORY_GRPC_PORT}"

# gRPC status -> (HTTP status, error code) returned to the order caller.
STATUS_MAP = {
    grpc.StatusCode.DEADLINE_EXCEEDED: (504, "inventory_timeout"),
    grpc.StatusCode.UNAVAILABLE: (503, "inventory_unavailable"),
    grpc.StatusCode.NOT_FOUND: (404, "item_not_found"),
    grpc.StatusCode.FAILED_PRECONDITION: (409, "insufficient_stock"),
    grpc.StatusCode.INVALID_ARGUMENT: (400, "invalid_quantity"),
}


class OrderRequest(BaseModel):
    item_id: str
    quantity: int


def _error(status, code, detail, grpc_status=None):
    content = {"error": code, "detail": detail}
    if grpc_status is not None:
        content["grpc_status"] = grpc_status
    return JSONResponse(status_code=status, content=content)


def create_app(stub=None):
    """`stub` is injectable for tests; by default one channel/stub is created at startup."""
    app = FastAPI(title="Order Service (gRPC)")
    inventory = stub or inventory_pb2_grpc.InventoryServiceStub(
        grpc.insecure_channel(INVENTORY_TARGET)
    )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return _error(400, "invalid_request", str(exc.errors()))

    @app.get("/health")
    def health():
        return {"status": "ok", "pid": os.getpid()}

    @app.post("/v1/orders")
    def create_order(body: OrderRequest, idempotency_key: Optional[str] = Header(default=None)):
        key = idempotency_key or str(uuid.uuid4())
        log.info("order received: %s x%d (key=%s)", body.item_id, body.quantity, key)
        req = inventory_pb2.ReserveRequest(
            item_id=body.item_id, quantity=body.quantity, idempotency_key=key
        )
        try:
            r = inventory.ReserveInventory(
                req,
                timeout=config.INVENTORY_DEADLINE_SECONDS,
                metadata=(("authorization", f"Bearer {config.INVENTORY_API_TOKEN}"),),
            )
        except grpc.RpcError as e:
            code = e.code()
            name = code.name
            log.warning("inventory call failed: %s (%s) key=%s", name, e.details(), key)
            if code == grpc.StatusCode.DEADLINE_EXCEEDED:
                return _error(
                    504, "inventory_timeout",
                    f"inventory did not respond within {config.INVENTORY_DEADLINE_SECONDS}s; "
                    f"the reservation may or may not exist, retry with Idempotency-Key {key}",
                    name,
                )
            if code in STATUS_MAP:
                status, err = STATUS_MAP[code]
                return _error(status, err, e.details(), name)
            return _error(502, "inventory_error", f"unexpected inventory status {name}", name)

        log.info("order confirmed: reservation %s", r.reservation_id)
        return JSONResponse(status_code=201, content={
            "status": "confirmed",
            "reservation_id": r.reservation_id,
            "item_id": r.item_id,
            "quantity": r.quantity,
        })

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s order %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=config.ORDER_GRPC_PORT)
