#!/usr/bin/env bash
# python-bootstrap.sh — resolve swarm-do py/ root, export PYTHONPATH, verify python3>=3.10.
# Sourced by swarm-do bin/* thin shims.

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
