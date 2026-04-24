"""Allow `python3 -m swarm_do.roles` invocation."""
import sys

from .cli import main

sys.exit(main())
