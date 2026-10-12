"""gRPC Inventory Service: InventoryService.ReserveInventory."""

import argparse
import logging
import time
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

from common import config
from common.inventory_store import (
    IdempotencyConflict,
    InsufficientStock,
    InvalidQuantity,
    InventoryStore,
    ItemNotFound,
)
from grpc_version import inventory_pb2, inventory_pb2_grpc

log = logging.getLogger("inventory")


class InventoryServicer(inventory_pb2_grpc.InventoryServiceServicer):
    def __init__(self, store=None, delay=0.0):
        self.store = store or InventoryStore()
        self.delay = delay

    def ReserveInventory(self, request, context):
        metadata = dict(context.invocation_metadata())
        if metadata.get("authorization") != f"Bearer {config.INVENTORY_API_TOKEN}":
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or invalid bearer token")

        if self.delay > 0:
            log.info("simulating slow inventory: sleeping %.1fs", self.delay)
            time.sleep(self.delay)
            if not context.is_active():
                log.warning("client gave up (deadline exceeded) before the delay finished")

        try:
            r = self.store.reserve(
                request.item_id, request.quantity, request.idempotency_key or None
            )
        except InvalidQuantity as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        except ItemNotFound as e:
            context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except InsufficientStock as e:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        except IdempotencyConflict as e:
            context.abort(grpc.StatusCode.ALREADY_EXISTS, str(e))
        log.info("reserved %s x%d -> %s", r.item_id, r.quantity, r.reservation_id)
        return inventory_pb2.ReserveResponse(
            reservation_id=r.reservation_id, item_id=r.item_id, quantity=r.quantity
        )


def create_server(port, store=None, delay=0.0):
    """Build (but don't start) a server. Use port=0 for an ephemeral port.

    Returns (server, bound_port).
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(
        InventoryServicer(store, delay), server
    )
    service_names = (
        inventory_pb2.DESCRIPTOR.services_by_name["InventoryService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)
    bound = server.add_insecure_port(f"127.0.0.1:{port}")
    return server, bound


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gRPC Inventory Service")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to sleep before handling each reservation")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s inventory %(message)s")
    server, port = create_server(config.INVENTORY_GRPC_PORT, delay=args.delay)
    server.start()
    log.info("gRPC inventory listening on :%d", port)
    server.wait_for_termination()
