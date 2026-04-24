"""Entrypoint for `python3 -m swarm_do.roles`.

Delegates to cli.main() and exits with the returned code.
Use `python3 -m swarm_do.roles --help` for available subcommands.
"""
import sys

from .cli import main

sys.exit(main())
