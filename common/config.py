"""Shared constants for both the REST and gRPC versions."""

ORDER_REST_PORT = 8000
INVENTORY_REST_PORT = 8001
ORDER_GRPC_PORT = 8080
INVENTORY_GRPC_PORT = 50051

# Client-side limits for the Order -> Inventory call.
INVENTORY_TIMEOUT_SECONDS = 2.0   # REST (httpx timeout)
INVENTORY_DEADLINE_SECONDS = 2.0  # gRPC (call deadline)

# Shared demo token; not a secret.
INVENTORY_API_TOKEN = "demo-token"
