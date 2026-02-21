#!/usr/bin/env bash
set -euo pipefail

# CI parity for local runs.
#
# Why this exists:
# - gives a single "what would CI do?" entrypoint
# - avoids memorizing harness arguments

python scripts/harness.py all --strict
