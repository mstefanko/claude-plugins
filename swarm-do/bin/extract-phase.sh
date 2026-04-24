#!/usr/bin/env bash
# extract-phase.sh — thin shim dispatching to the Python findings extractor.
#
# The implementation lives in swarm_do.telemetry.extractors (Phase 4). The
# legacy bash body is preserved alongside this file as extract-phase.sh.legacy
# for the duration of Phase 4's parity verification; it is deleted at phase
# close.
#
# Usage (unchanged from the legacy script):
#   extract-phase.sh <input-file> <run-id> <role> <issue-id>
#   extract-phase.sh --test
#
# Fail-open: the Python entrypoint swallows every error and exits 0. Do NOT
# add error-handling logic here — the pipeline's exit code must never change.

set -euo pipefail

_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib"

# shellcheck source=_lib/python-bootstrap.sh
source "${_lib_dir}/python-bootstrap.sh"

exec python3 -m swarm_do.telemetry.extractors "$@"
