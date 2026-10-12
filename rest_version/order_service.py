"""REST Order Service: POST /v1/orders -> Inventory Service over HTTP/JSON."""

import logging
import os
import uuid
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common import config

log = logging.getLogger("order")

INVENTORY_URL = f"http://127.0.0.1:{config.INVENTORY_REST_PORT}"
# Inventory statuses that are meaningful to the caller and passed straight through.
PASSTHROUGH = {400, 404, 409}


class OrderRequest(BaseModel):
    item_id: str
    quantity: int


def _error(status, code, detail):
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def create_app(client=None):
    """`client` is injectable for tests; by default it carries the Order -> Inventory timeout."""
    app = FastAPI(title="Order Service (REST)")
    inventory = client or httpx.Client(
        base_url=INVENTORY_URL, timeout=config.INVENTORY_TIMEOUT_SECONDS
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
        try:
            resp = inventory.post(
                "/v1/reservations",
                json={"item_id": body.item_id, "quantity": body.quantity},
                headers={
                    "Authorization": f"Bearer {config.INVENTORY_API_TOKEN}",
                    "Idempotency-Key": key,
                },
            )
        except httpx.TimeoutException:
            log.warning("inventory timed out after %.1fs (key=%s)", config.INVENTORY_TIMEOUT_SECONDS, key)
            return _error(
                504, "inventory_timeout",
                f"inventory did not respond within {config.INVENTORY_TIMEOUT_SECONDS}s; "
                f"the reservation may or may not exist, retry with Idempotency-Key {key}",
            )
        except httpx.ConnectError:
            log.warning("inventory unreachable")
            return _error(503, "inventory_unavailable", "could not connect to inventory service")
        except httpx.HTTPError as e:
            log.warning("inventory call failed: %r", e)
            return _error(502, "inventory_error", "unexpected error calling inventory service")

        if resp.status_code == 201:
            r = resp.json()
            log.info("order confirmed: reservation %s", r["reservation_id"])
            return JSONResponse(status_code=201, content={"status": "confirmed", **r})
        if resp.status_code in PASSTHROUGH:
            log.info("order rejected by inventory: %d", resp.status_code)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        log.warning("unexpected inventory response: %d", resp.status_code)
        return _error(502, "inventory_error", f"unexpected inventory status {resp.status_code}")

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s order %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=config.ORDER_REST_PORT)
