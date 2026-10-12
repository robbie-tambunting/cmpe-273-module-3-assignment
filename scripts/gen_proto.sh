#!/usr/bin/env bash
# Regenerate gRPC stubs. Run from anywhere; operates on the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. --pyi_out=. grpc_version/inventory.proto
