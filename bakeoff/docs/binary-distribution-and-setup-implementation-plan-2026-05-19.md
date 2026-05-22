# Bakeoff Binary Distribution And Setup Implementation Plan

Date: 2026-05-19

Status: superseded for the internal developer workflow. Bakeoff now defaults to
building the bundled Go source into `${CLAUDE_PLUGIN_DATA}/bin/bakeoff` via
`/bakeoff:setup`, and the plugin manifests omit explicit versions so Claude
Code tracks updates by git SHA. Release downloads remain available only as the
optional `--from-release --version <tag>` no-Go path. See
`docs/cli-reference.md` and `docs/release-publishing.md` for current behavior.

## Requirement

Make Bakeoff usable by normal Claude Code plugin users without requiring a Go
toolchain. Keep source builds available for contributors, but make the primary
installed-plugin path binary-first, explicit, auditable, and reversible.

The current README says users need "Go 1.24+ unless you have `dist/bakeoff` or
set `BAKEOFF_GO_BINARY`." That is the right fallback contract, but the default
user experience should not depend on Go. A plugin command should provision a
released binary into persistent plugin data, and all plugin commands should use
that binary automatically.

## Current Evidence

- `bin/bakeoff` currently resolves `BAKEOFF_GO_BINARY`, then
  `${ROOT}/dist/bakeoff`, then `go run "${ROOT}/cmd/bakeoff"`.
- `scripts/bakeoff-ensure-cli` mirrors that shape and builds
  `${ROOT}/dist/bakeoff` from source when Go is available.
- `/bakeoff:quickstart` currently calls `scripts/bakeoff-ensure-cli`, then
  runs `bin/bakeoff doctor --skip-auth-probe --json`.
- `/bakeoff:doctor`, `/bakeoff:run`, and `/bakeoff:inspect` already use
  `${CLAUDE_PLUGIN_ROOT}/bin/bakeoff`, which means one launcher change can cover
  all command surfaces.
- Claude Code plugin docs say `bin/` executables are added to PATH while the
  plugin is enabled, `${CLAUDE_PLUGIN_ROOT}` is versioned/ephemeral, and
  `${CLAUDE_PLUGIN_DATA}` is the persistent directory for installed
  dependencies, caches, and generated files.
- Claude Code `Setup` hooks run for `claude --init-only`, `--init`, or
  `--maintenance -p`; they are not a reliable post-`/plugin install` hook for
  normal interactive users.
- This checkout's `origin` remote is `git@github.com:mstefanko/claude-plugins.git`,
  and `go.mod` uses `github.com/mstefanko/claude-plugins/bakeoff`, so v1 release
  assets should come from `mstefanko/claude-plugins` unless the repository is
  intentionally moved before implementation.

References:

- https://code.claude.com/docs/en/plugins-reference
- https://code.claude.com/docs/en/discover-plugins
- https://code.claude.com/docs/en/plugin-marketplaces

## Recommendation

Add an explicit `/bakeoff:setup` command backed by a new
`scripts/bakeoff-setup` provisioner. The provisioner downloads the matching
released `bakeoff` binary for the host platform, verifies its checksum, installs
it atomically under `${CLAUDE_PLUGIN_DATA}/bin/bakeoff`, and runs a version
probe. Update the launcher and readiness scripts to prefer that persistent data
binary before plugin-root `dist/` and source builds.

Do not rely on `/plugin install` to run arbitrary setup. Installing the plugin
should install commands and scripts. Provisioning an executable binary from the
network should remain a visible user action via `/bakeoff:setup`, with
`/bakeoff:quickstart` detecting the missing binary and pointing directly to it.

Keep `BAKEOFF_GO_BINARY` as the highest-precedence override for development,
testing, and air-gapped environments.

## Resolved V1 Decisions

- Release repository: `mstefanko/claude-plugins`.
- Default release URL template:

  ```text
  https://github.com/mstefanko/claude-plugins/releases/download/<tag>/<asset>
  ```

- Setup v1 assumes public GitHub Release assets. Private release support would
  require `gh` auth or a token flow and is out of scope for the first pass.
- Do not make Windows release assets a v1 setup requirement. `/bakeoff:setup`
  should reject Windows with a clear "unsupported in v1" message until the
  Claude Code shell path is tested there.
- Keep `version` in `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`
  and bump both to the release version. Claude Code uses `plugin.json` as the
  authoritative version when present, so omitting it would make plugin updates
  commit-SHA based rather than release based.
- Do not use `CODEX_PLUGIN_DATA` in v1. It is not documented in the evidence for
  this plan. Codex support stays on `BAKEOFF_GO_BINARY`, packaged `dist/bakeoff`,
  or source builds until a persistent Codex plugin data variable is verified.
- Do not commit multi-platform `dist/bakeoff-*` binaries to this marketplace
  repository in v1. Use release downloads for normal users; keep `dist/bakeoff`
  as a local build/package escape hatch.

## Rejected Alternatives

### Auto-download from `/plugin install`

Rejected. Claude Code marketplace install copies/caches plugin files, but there
is no documented plugin-defined post-install script. Hiding network binary
installation behind plugin install would also make trust and failure modes
harder to explain.

### Use a `SessionStart` hook

Rejected. It would create surprise network and filesystem writes when a session
starts. It also risks noisy failures before the user asks to use Bakeoff.

### Use a `Setup` hook as the primary flow

Rejected as the main path. A `Setup` hook only runs under specific Claude Code
startup modes and is better suited for CI or scripted maintenance. It can be
added later as an opt-in convenience after the explicit setup command is stable.

### Require Homebrew, npm, or Go

Rejected for the first version. Those are useful secondary distribution
channels, but they make the simplest plugin setup depend on another ecosystem.
The plugin can download a single Go binary directly and verify it.

### Ship only `dist/bakeoff` in the plugin repository

Rejected as the only strategy. It works for a single platform, but not for a
shared marketplace plugin unless the marketplace publishes platform-specific
plugin packages. Keep `dist/bakeoff` support for local builds and future
platform-specific plugin packages, but do not commit a matrix of binaries to the
marketplace repo in v1.

## Target User Flow

Fresh install:

```text
/plugin marketplace add mstefanko-plugins <source>
/plugin install bakeoff@mstefanko-plugins
/reload-plugins
/bakeoff:setup
/bakeoff:quickstart
```

Day-to-day:

```text
/bakeoff:run review this diff against main
```

If a user skips setup:

```text
/bakeoff:quickstart
```

should report that no provisioned CLI exists and say:

```text
Run /bakeoff:setup to install the prebuilt Bakeoff CLI, or set
BAKEOFF_GO_BINARY. Go 1.24+ is only needed for source installs.
```

## Launcher Contract

Update every launcher/readiness path to use this order:

```text
BAKEOFF_GO_BINARY
  -> ${BAKEOFF_PLUGIN_DATA}/bin/bakeoff
  -> ${CLAUDE_PLUGIN_DATA}/bin/bakeoff
  -> <plugins-root>/data/<plugin>-<marketplace>/bin/bakeoff
  -> ${CLAUDE_PLUGIN_ROOT}/dist/bakeoff
  -> go run/go build from source when Go is present
```

Notes:

- `BAKEOFF_PLUGIN_DATA` is an explicit override for tests, mirrors, and
  non-Claude launchers.
- `CLAUDE_PLUGIN_DATA` is the normal installed-plugin location.
- The conventional Claude plugin data path is derived from plugin roots shaped
  like `<plugins-root>/marketplaces/<marketplace>/<plugin>` or
  `<plugins-root>/cache/<marketplace>/<plugin>/<version>` and is probed even
  when `CLAUDE_PLUGIN_DATA` is not present in the child environment.
- Resolution is order-only. Data-dir candidates beat `dist/bakeoff`; mtimes,
  hashes, and version strings are not tie-breakers.
- `dist/bakeoff` is a local build or platform-specific package artifact, not a
  committed multi-platform distribution strategy.
- `BAKEOFF_GO_BINARY` remains first because explicit user configuration should
  always win.
- Successful setup deletes root `dist/bakeoff`, so a missing cache binary after
  setup means the launcher should use the data-dir binary. No sentinel, rename,
  or freshness marker is used.

Readiness exit-code contract:

- `scripts/bakeoff-ensure-cli --check` exits `0` when a usable configured or
  provisioned binary is found.
- `--check` exits `2` when no configured or provisioned binary exists, or when
  an explicit path such as `BAKEOFF_GO_BINARY` is missing or not executable.
- `--check` exits `1` when a candidate binary exists and is executable but
  fails the `--version` probe.
- `--print-path` prints only the resolved executable path for launch helpers.
- Without `--check`, missing binaries may fall through to a source build when Go
  is available. Build failure exits `1`; no binary and no Go exits `2`.

## Release Artifact Contract

Add a release pipeline that publishes these assets for each tag:

```text
bakeoff_<tag>_darwin_arm64.tar.gz
bakeoff_<tag>_darwin_amd64.tar.gz
bakeoff_<tag>_linux_arm64.tar.gz
bakeoff_<tag>_linux_amd64.tar.gz
checksums.txt
```

Each v1 archive contains one executable named `bakeoff`. Checksums use SHA-256
and include every archive. Future Windows support can add
`bakeoff_<tag>_windows_amd64.zip` with `bakeoff.exe` after the plugin shell path
is tested.

Use these concrete URL and file conventions:

```text
BAKEOFF_RELEASE_REPOSITORY default: mstefanko/claude-plugins
BAKEOFF_RELEASE_BASE_URL default:
  https://github.com/${BAKEOFF_RELEASE_REPOSITORY}/releases/download/${tag}

Archive URL:
  ${BAKEOFF_RELEASE_BASE_URL}/bakeoff_${tag}_${goos}_${goarch}.tar.gz

Checksum URL:
  ${BAKEOFF_RELEASE_BASE_URL}/checksums.txt
```

The checksum file must use SHA256SUM-compatible lines:

```text
<64 lowercase hex chars><two spaces><asset basename>
```

Example:

```text
0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef  bakeoff_v0.1.0_darwin_arm64.tar.gz
```

Only basenames are allowed in `checksums.txt`; no absolute paths or directory
prefixes. `scripts/bakeoff-setup` should parse the line for the selected asset,
compute the downloaded archive digest locally, compare exact lowercase hex, and
fail closed if the line is missing, duplicated, malformed, or mismatched.

Use `curl` as the only production downloader:

```bash
curl -fsSL --proto '=https' --proto-redir '=https' --tlsv1.2 -o <target> <url>
```

For tests, `BAKEOFF_RELEASE_BASE_URL=file:///...` may bypass `curl` and copy
from the local filesystem. Do not add a `wget` fallback in v1; if `curl` is
missing, fail with a clear setup error.

Use GoReleaser unless there is a strong reason to keep a hand-written workflow.
The config should:

- build `./cmd/bakeoff`;
- set `CGO_ENABLED=0`;
- target `darwin` and `linux` on `amd64` and `arm64`;
- add Windows only when the plugin command surface is tested there;
- set `internal/buildinfo.Version`, `Commit`, and `Date` with `ldflags`;
- generate archives and `checksums.txt`;
- support `goreleaser release --snapshot --clean` locally;
- leave Homebrew publishing out of v1 release automation.

## macOS Gatekeeper Strategy

Apple recommends Developer ID signing and notarization for software distributed
outside the App Store, and GoReleaser documents signing/notarization paths for
macOS binaries. Treat this as part of distribution quality, not as a "Sigstore
later" footnote.

V1 rules:

- Prefer Developer ID signing and notarization for macOS release binaries before
  public distribution if credentials are available.
- Do not automatically run `xattr -dr com.apple.quarantine` in
  `/bakeoff:setup`. That bypasses a macOS security control and should not be a
  silent plugin side effect.
- If macOS signing/notarization is not available for the first private dogfood
  release, document the release as unsigned and keep `/bakeoff:setup` explicit.
- If the installed binary fails its version probe on macOS with a Gatekeeper-like
  "damaged" or "cannot verify developer" error, print a targeted remediation:
  use a signed release when available, use a source build, or manually remove
  quarantine only if the user explicitly trusts the downloaded binary.
- Homebrew casks should wait until signing/notarization is solved. A Homebrew
  formula/tap for the CLI can be added earlier if it does not require cask-style
  quarantine workarounds.

## Installed Metadata Contract

`scripts/bakeoff-setup` must write `${data}/version.json` using this exact v1
shape:

```json
{
  "schema_version": 1,
  "owner": "bakeoff",
  "tool": "bakeoff",
  "install_kind": "release-binary",
  "repository": "mstefanko/claude-plugins",
  "version": "v0.1.0",
  "commit": "unknown",
  "date": "unknown",
  "asset": "bakeoff_v0.1.0_darwin_arm64.tar.gz",
  "checksum_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "source_url": "https://github.com/mstefanko/claude-plugins/releases/download/v0.1.0/bakeoff_v0.1.0_darwin_arm64.tar.gz",
  "binary_path": "/absolute/path/to/plugin-data/bin/bakeoff",
  "installed_at": "2026-05-19T00:00:00Z",
  "host": {
    "os": "darwin",
    "arch": "arm64"
  }
}
```

Ownership rule for uninstall:

- A plugin data directory is Bakeoff-owned only when `version.json` has
  `schema_version: 1`, `owner: "bakeoff"`, `tool: "bakeoff"`, and
  `install_kind: "release-binary"`.
- `scripts/bakeoff-uninstall` may remove `${data}/bin/bakeoff`,
  `${data}/version.json`, and Bakeoff setup temp/cache directories when that
  ownership check passes.
- It may remove the whole data directory only after deleting Bakeoff-owned files
  and confirming the directory is empty.
- It must not remove arbitrary `${CLAUDE_PLUGIN_DATA}` contents solely because
  the path looks plausible.

## Implementation Phases

### Phase 0: Release Constants And Policy

Before writing setup code, lock these constants into the plan, scripts, and
tests:

- default `BAKEOFF_RELEASE_REPOSITORY`: `mstefanko/claude-plugins`;
- default release base URL template;
- supported setup platforms: `darwin/arm64`, `darwin/amd64`, `linux/arm64`,
  `linux/amd64`;
- Windows setup rejection text;
- macOS signing/notarization posture for the first release;
- plugin manifest version bump policy.

This phase prevents the setup script from accumulating hidden placeholders such
as `TODO_REPO` or speculative environment variables.

### Phase 1: Shared Launcher Helpers

Add `scripts/bakeoff-lib` with shell functions used by `bin/bakeoff`,
`scripts/bakeoff-ensure-cli`, `scripts/bakeoff-setup`, and uninstall:

- `bakeoff_plugin_root`
- `bakeoff_data_root`
- `bakeoff_host_os_arch`
- `bakeoff_candidate_binaries`
- `bakeoff_version_probe`
- `bakeoff_print_missing_cli_help`

Keep the helper Bash-only, with no Python, jq, or Go dependency.

Sourcing convention:

- `scripts/bakeoff-lib` is sourced only; it is not executable user interface.
- The library must not call `set -e`, `set -u`, `set -o pipefail`, or `exit`.
  Callers own shell options and process exit.
- The library must not run work at source time beyond constants and function
  definitions.
- Functions return status codes instead of exiting.
- Functions that produce values write only the value to stdout.
- Diagnostics, warnings, and errors go to stderr.
- No function should depend on global mutable state except documented
  environment variables.
- Prefer `case` and shell parameter expansion over fragile text parsing.

Modify:

- `bin/bakeoff`
- `scripts/bakeoff-ensure-cli`

Expected behavior:

- `scripts/bakeoff-ensure-cli --check` checks all configured/provisioned binary
  locations and never builds.
- Default `scripts/bakeoff-ensure-cli` may still build `dist/bakeoff` for
  source checkouts when Go is available.
- Missing binary messaging points users to `/bakeoff:setup` before "install Go".
- Exit codes match the Launcher Contract section exactly.

### Phase 2: Explicit Setup Provisioner

Add `scripts/bakeoff-setup`.

Required flags:

```text
scripts/bakeoff-setup [--version <tag>] [--yes] [--dry-run] [--json]
```

Behavior:

1. Resolve plugin data root and create `${data}/bin`.
2. Detect host OS and architecture.
3. Resolve the release version:
   - default to the plugin's configured release tag, matching the installed
     plugin command version;
   - explicit `--version vX.Y.Z` for deterministic installs;
   - allow `BAKEOFF_RELEASE_BASE_URL` in tests and mirrors;
   - allow `BAKEOFF_RELEASE_REPOSITORY` to override only the owner/repo portion
     of the default GitHub URL.
4. Select the matching archive.
5. Create `${data}/tmp` and then `mktemp -d "${data}/tmp/setup.XXXXXX"` so all
   temp files live on the same filesystem as the final binary.
6. Download archive and `checksums.txt` to that temp directory.
7. Verify SHA-256 before extraction.
8. Extract only the expected `bakeoff` executable.
9. Run `bakeoff --version` from the temp location.
10. Move the verified executable into `${data}/bin/bakeoff` with same-filesystem
    atomic rename.
11. Write `${data}/version.json` using the Installed Metadata Contract.
12. Print the installed path and next command.

Safety requirements:

- Fail closed if checksum is missing or mismatched.
- Never execute a downloaded file before checksum verification.
- Do not write into `${CLAUDE_PLUGIN_ROOT}`.
- Do not let `mktemp` choose `/tmp` for setup work; cross-filesystem `mv` breaks
  the atomic rename guarantee.
- Write the new binary to a temp file under `${data}/bin`, then `mv -f` it into
  final position only after checksum verification, extraction, chmod, and version
  probe all pass.
- Use `umask 077` for temp files and make the final binary executable.
- Keep output human-readable by default and machine-readable under `--json`.
- Reject archives containing more than the expected executable, path traversal,
  absolute paths, symlinks, or directories.
- On macOS, surface Gatekeeper-like version-probe failures with the remediation
  text from the macOS Gatekeeper Strategy section.

### Phase 3: Add `/bakeoff:setup`

Add `commands/setup.md`.

Frontmatter should allow only:

```text
Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup:*)
Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*)
Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff doctor:*)
```

Command flow:

1. Run `scripts/bakeoff-setup --dry-run --json` and summarize the selected
   version, platform, target path, and release URL.
2. Ask for explicit approval unless the user passed `--yes`.
3. Run `scripts/bakeoff-setup --yes` with any `--version` value.
4. Run `scripts/bakeoff-ensure-cli --check`.
5. Run `bin/bakeoff doctor --skip-auth-probe --json`.
6. Summarize readiness and tell the user full runs still depend on authenticated
   `claude` and `codex` provider CLIs.

This command should not ask for provider API keys, mutate project files, or run
live build probes.

### Phase 4: Release Automation

Add:

- `.goreleaser.yaml`
- `.github/workflows/release.yml`

Workflow:

- On tag `v*`, run tests.
- Run GoReleaser.
- Publish release archives and checksums to `mstefanko/claude-plugins`.
- Do not publish Homebrew artifacts in the v1 release workflow; keep the
  release assets simple and plugin-focused.

Required local validation:

```bash
go test ./...
goreleaser release --snapshot --clean
```

GoReleaser config requirements:

- `project_name: bakeoff`;
- archive names use the release tag exactly, including leading `v`;
- `checksum.name_template: checksums.txt`;
- `checksum.algorithm: sha256`;
- `CGO_ENABLED=0`;
- `ldflags` set `internal/buildinfo.Version`, `Commit`, and `Date`;
- macOS signing/notarization config is included when credentials exist, or a
  documented unsigned-dogfood limitation is added before publishing.

If GoReleaser is not available in development environments, document the
installation command but do not make normal Bakeoff users install it.

### Phase 5: Quickstart And Doctor UX

Modify:

- `commands/quickstart.md`
- `commands/doctor.md`
- `commands/inspect.md` if needed for check-only wording
- `docs/cli-reference.md`
- `README.md`

New positioning:

- `/bakeoff:setup` installs or updates the Bakeoff CLI binary.
- `/bakeoff:quickstart` checks readiness and guides next steps.
- Go is documented as contributor/source-install fallback, not user prerequisite.
- `dist/bakeoff` is documented as packaged-binary fallback.
- `BAKEOFF_GO_BINARY` is documented as explicit override.

Update troubleshooting:

```text
Quickstart cannot find a CLI -> Run /bakeoff:setup, set BAKEOFF_GO_BINARY,
install a package that includes dist/bakeoff, or install Go for source builds.
```

### Phase 6: Uninstall And Update Semantics

Modify `scripts/bakeoff-uninstall` to remove the Bakeoff-owned plugin data
binary and metadata using the Installed Metadata Contract ownership rule.

Add `scripts/bakeoff-setup --version <tag>` support before adding any
auto-update behavior. Do not auto-update on every session. A later command can
add:

```text
/bakeoff:setup --version latest
```

as the explicit upgrade path.

### Deferred: Long-Term Package Managers

Do not block plugin setup on package managers, but do not leave the bespoke
downloader as the only long-term path.

After one plugin-native setup release is stable, consider a Homebrew tap:

- create or choose `mstefanko/homebrew-tap`;
- add GoReleaser `brews` config for `bakeoff`;
- install into Homebrew `bin`;
- document `brew install mstefanko/tap/bakeoff` and `brew upgrade bakeoff`;
- keep `/bakeoff:setup` as the plugin-native path for users who do not use
  Homebrew.

## Tests And Verification

Add script-level tests that do not hit the network.

Suggested test setup:

- Build a local fake release directory under `/tmp`.
- Create fake archives for at least `darwin_arm64` or the current host tuple.
- Generate a local `checksums.txt`.
- Run `scripts/bakeoff-setup` with `BAKEOFF_RELEASE_BASE_URL=file:///tmp/...`
  or an equivalent local test flag.
- Set `BAKEOFF_PLUGIN_DATA` to a temp directory.

Test cases:

1. No Go, no binary: `scripts/bakeoff-ensure-cli --check` exits `2` and points
   to setup.
2. Valid fake release installs to `${BAKEOFF_PLUGIN_DATA}/bin/bakeoff`.
3. Installed binary is preferred over `dist/bakeoff`.
4. `BAKEOFF_GO_BINARY` still wins over the installed data binary.
5. Checksum mismatch fails and does not write final binary.
6. Missing, duplicate, path-prefixed, uppercase, or malformed checksum lines
   fail closed.
7. Archive path traversal, symlink, extra-file, and missing-binary cases fail
   closed.
8. Re-running setup is idempotent.
9. `version.json` matches the Installed Metadata Contract.
10. `scripts/bakeoff-uninstall --force` removes installed data binary only when
    ownership metadata matches.
11. macOS Gatekeeper-like version-probe failures produce targeted remediation.
12. `go test ./...` still passes.
13. `goreleaser release --snapshot --clean` produces expected archives and
   checksums.

Manual smoke:

```bash
env -i HOME="$HOME" PATH="/usr/bin:/bin" \
  CLAUDE_PLUGIN_ROOT="$PWD" \
  BAKEOFF_PLUGIN_DATA="$(mktemp -d)" \
  ./scripts/bakeoff-ensure-cli --check
```

Expected: no Go fallback is used; the error points to setup.

Then:

```bash
BAKEOFF_PLUGIN_DATA="$(mktemp -d)" ./scripts/bakeoff-setup --yes --version <test-tag>
BAKEOFF_PLUGIN_DATA="$same_dir" ./scripts/bakeoff-ensure-cli --check
```

Expected: ensure reports the plugin-data binary.

## Acceptance Criteria

- A user can install the plugin, run `/bakeoff:setup`, and then run
  `/bakeoff:quickstart` without Go installed.
- `/bakeoff:run`, `/bakeoff:doctor`, and `/bakeoff:inspect` all use the same
  provisioned binary through `bin/bakeoff`.
- The setup flow verifies checksums before installing.
- The setup flow uses the pinned `mstefanko/claude-plugins` release URL template
  unless explicitly overridden.
- The setup flow writes only to `${CLAUDE_PLUGIN_DATA}` or an explicit
  Bakeoff data override, never to project repos.
- Temporary files are created under plugin data, and the final binary is moved
  into place with a same-filesystem atomic rename.
- `version.json` uses the pinned schema and uninstall relies on that schema for
  ownership.
- macOS release behavior is explicit: signed/notarized when credentials exist,
  otherwise documented as unsigned dogfood with no silent quarantine bypass.
- Source checkout contributors can still build from Go with existing dev
  commands.
- Documentation clearly separates:
  - normal user install;
  - explicit binary setup;
  - source/development fallback;
  - provider CLI authentication requirements.
- Uninstall removes Bakeoff-owned plugin binary state and leaves provider CLIs,
  auth, git branches, and user work untouched.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Claude Code changes plugin environment variables | Keep `BAKEOFF_GO_BINARY` and `BAKEOFF_PLUGIN_DATA` overrides; document the observed Claude variables. |
| Corporate networks block GitHub releases | Support `--version` and `BAKEOFF_RELEASE_BASE_URL` so teams can mirror assets. |
| Checksum file from same release is not full supply-chain proof | Start with SHA-256 for integrity; add Sigstore/GitHub attestation verification later. |
| Users expect setup during `/plugin install` | README and quickstart should say plugin install adds commands; `/bakeoff:setup` provisions the binary. |
| Plugin root is cached/versioned and may disappear | Install binaries under `${CLAUDE_PLUGIN_DATA}`, not plugin root. |
| Multiple platforms in one plugin package increase size | Do not commit a binary matrix to the marketplace repo; prefer setup download first. |
| macOS unsigned binaries trip Gatekeeper or user trust warnings | Prefer signing/notarization; otherwise document unsigned dogfood and avoid silent `xattr` bypasses. |
| Bespoke setup downloader becomes the only install story | Add Homebrew tap support after release assets stabilize. |

## Open Questions

1. Are Apple Developer ID signing and notarization credentials available for
   the first public macOS release, or should the first macOS binary be marked as
   unsigned dogfood only?
2. Should a CI-only `Setup` hook be added later behind an opt-in environment
   variable such as `BAKEOFF_AUTO_SETUP=1`?
3. Should `mstefanko/homebrew-tap` be created for the first release, or should
   Homebrew wait until after one plugin-native setup release?
4. Do Codex plugins expose a documented persistent data directory equivalent to
   `${CLAUDE_PLUGIN_DATA}`? If not, keep Codex on `BAKEOFF_GO_BINARY`,
   packaged `dist/bakeoff`, or source build until verified.

## Execution Order

Follow the implementation phases in order:

1. Phase 0: release constants and policy.
2. Phase 1: shared launcher helpers.
3. Phase 2: explicit setup provisioner.
4. Phase 3: `/bakeoff:setup`.
5. Phase 4: release automation.
6. Phase 5: quickstart and doctor UX.
7. Phase 6: uninstall and update semantics.
8. Final validation: run the no-Go smoke, `go test ./...`, and
   `goreleaser release --snapshot --clean`.
