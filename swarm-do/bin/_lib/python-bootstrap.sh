#!/usr/bin/env bash
# python-bootstrap.sh — shared setup for swarm-do Python thin shims.
#
# Purpose: resolves the swarm_do package root (_lib/../../py), exports
# PYTHONPATH so `python3 -m swarm_do.*` works without an install step,
# and enforces a python3 >= 3.10 version gate (match-expression syntax
# and structural pattern matching are assumed by later phases).
#
# Usage: source this file from any bin/* shim before execing python3.
# Version gate: exits 1 with a clear message if python3 is absent or < 3.10.
# Sourced by swarm-do bin/* thin shims — do not exec directly.

# Resolve the python package root relative to THIS file: _lib/../../py
_PY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/py"
export _PY_ROOT
export PYTHONPATH="${_PY_ROOT}:${PYTHONPATH:-}"

# Require python3 >= 3.10
if ! command -v python3 >/dev/null 2>&1; then
  echo "swarm-telemetry: python3 not found — install Python >= 3.10" >&2
  exit 1
fi

_PY_VERSION="$(python3 --version 2>&1)"
if [[ "${_PY_VERSION}" =~ ^Python[[:space:]]([0-9]+)\.([0-9]+) ]]; then
  _PY_MAJOR="${BASH_REMATCH[1]}"
  _PY_MINOR="${BASH_REMATCH[2]}"
  if (( _PY_MAJOR < 3 )) || { (( _PY_MAJOR == 3 )) && (( _PY_MINOR < 10 )); }; then
    echo "swarm-telemetry: python3 >=3.10 required (found ${_PY_VERSION}) — please upgrade" >&2
    exit 1
  fi
else
  echo "swarm-telemetry: could not parse python3 version from '${_PY_VERSION}' — please upgrade to Python >=3.10" >&2
  exit 1
fi
