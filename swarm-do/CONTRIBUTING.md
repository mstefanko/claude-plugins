# Contributing

## Recovery Operations

Recovery operations on `~/.local/share/swarmdaddy/` state must ship as
`swarm` subcommands. Do not commit one-off `/tmp` helper scripts, and do not
link to `/tmp` scripts in investigation notes as the recommended fix path.

Read-only probe scripts are acceptable during investigations, but any state
mutation that becomes an operator recommendation belongs behind a tested
`bin/swarm ...` command with an audit event.
