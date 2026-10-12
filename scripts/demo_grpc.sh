#!/usr/bin/env bash
# gRPC demo: raw RPC example, happy path, error statuses, idempotent replay, then a
# slow-inventory deadline failure and recovery. Order Service must keep the same PID.
# Usage: scripts/demo_grpc.sh   (ports 8080/50051 must be free)
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
LOGDIR=evidence
mkdir -p "$LOGDIR"
ORDER=http://127.0.0.1:8080
INV_ADDR=127.0.0.1:50051
INV_PID=""; ORD_PID=""

cleanup() { kill $INV_PID $ORD_PID 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT

wait_up() {  # wait until the order service answers HTTP
  for _ in $(seq 50); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$1")" != "000" ] && return 0
    sleep 0.2
  done
  echo "timed out waiting for $1"; exit 1
}

wait_port() {  # wait until a TCP port accepts connections
  for _ in $(seq 50); do
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return 0
    sleep 0.2
  done
  echo "timed out waiting for port $1"; exit 1
}

start_inventory() {  # $@ = extra args (e.g. --delay 5)
  $PY -m grpc_version.inventory_server "$@" >>"$LOGDIR/grpc_inventory.log" 2>&1 &
  INV_PID=$!
  wait_port 50051
}

stop_inventory() { kill $INV_PID; wait $INV_PID 2>/dev/null; }

order() {  # $1 = description, $2 = JSON body, $3.. = extra curl args
  local desc=$1 body=$2; shift 2
  echo "\$ POST /v1/orders $body   # $desc"
  curl -s -w '\n-> HTTP %{http_code} in %{time_total}s\n' "$ORDER/v1/orders" \
    -H 'Content-Type: application/json' -d "$body" "$@"
  echo
}

raw_rpc() {  # call InventoryService.ReserveInventory directly, bypassing the Order Service
  $PY - <<'PYEOF'
import grpc
from common import config
from grpc_version import inventory_pb2, inventory_pb2_grpc

req = inventory_pb2.ReserveRequest(item_id="sku-123", quantity=2, idempotency_key="raw-demo-1")
print("RPC inventory.v1.InventoryService/ReserveInventory")
print("request:")
print("  " + str(req).strip().replace("\n", "\n  "))
with grpc.insecure_channel("127.0.0.1:50051") as ch:
    stub = inventory_pb2_grpc.InventoryServiceStub(ch)
    resp = stub.ReserveInventory(req, timeout=2, metadata=(("authorization", f"Bearer {config.INVENTORY_API_TOKEN}"),))
    print("response (status OK):")
    print("  " + str(resp).strip().replace("\n", "\n  "))
PYEOF
  echo
}

: > "$LOGDIR/grpc_inventory.log"; : > "$LOGDIR/grpc_order.log"

echo "=== Start services ==="
start_inventory
$PY -m grpc_version.order_service >"$LOGDIR/grpc_order.log" 2>&1 &
ORD_PID=$!
wait_up "$ORDER/health"
echo "inventory pid=$INV_PID  order pid=$ORD_PID"
echo "\$ GET /health"; curl -s "$ORDER/health"; echo; echo

echo "=== Raw gRPC call straight to Inventory (no Order Service) ==="
raw_rpc

echo "=== Normal behaviour via Order Service ==="
order "success -> 201"                '{"item_id":"sku-123","quantity":1}'
order "unknown item -> NOT_FOUND / 404"              '{"item_id":"nope","quantity":1}'
order "insufficient stock -> FAILED_PRECONDITION / 409" '{"item_id":"sku-456","quantity":2}'
order "invalid quantity -> INVALID_ARGUMENT / 400"   '{"item_id":"sku-123","quantity":0}'
echo "--- idempotent replay: same Idempotency-Key twice, same reservation_id, stock decremented once ---"
order "first try"  '{"item_id":"sku-456","quantity":1}' -H 'Idempotency-Key: demo-key-1'
order "replay"     '{"item_id":"sku-456","quantity":1}' -H 'Idempotency-Key: demo-key-1'

echo "=== Failure: inventory responds slower (5s) than the 2s deadline ==="
stop_inventory
start_inventory --delay 5
echo "before: $(curl -s "$ORDER/health")"
order "slow inventory -> expect DEADLINE_EXCEEDED / 504 after ~2s" '{"item_id":"sku-123","quantity":1}'
echo "after:  $(curl -s "$ORDER/health")   <- same pid = Order Service survived"
echo

echo "=== Recovery: inventory restarted without delay ==="
stop_inventory
start_inventory
order "same order service process -> 201" '{"item_id":"sku-123","quantity":1}'
echo "final:  $(curl -s "$ORDER/health")"
echo
echo "=== Done (logs: $LOGDIR/grpc_order.log, $LOGDIR/grpc_inventory.log) ==="
