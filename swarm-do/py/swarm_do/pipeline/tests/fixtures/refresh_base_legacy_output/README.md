Legacy refresh-base fixture
===========================

This directory captures the legacy `/tmp/refresh-git-base.py` recovery helper
that caused prepared dispatch drift by recursively updating `git_base_sha` in
`prepared_plan.v1.json` without rewriting work-unit sidecars or descriptor
SHAs.

The regression tests synthesize that byte shape in-process with the same
recursive algorithm so the fixture does not depend on the original operator's
machine-local run paths.
