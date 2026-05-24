# Bakeoff Release Publishing

Bakeoff's normal internal setup path builds the bundled Go source with
`/bakeoff:setup`. GitHub Release assets are optional for users who do not want
Go installed locally, or for air-gapped mirroring.

The plugin intentionally omits explicit `version` fields, so Claude Code uses
the plugin source git SHA as the update key. Source changes reach internal users
through normal marketplace updates; after updating, they rerun `/bakeoff:setup`
to rebuild the CLI from the updated source.

## Optional Release Checklist

1. Pick the CLI release tag:

   ```text
   CLI release tag -> v0.1.0
   ```

2. Validate from the repository root:

   ```bash
   cd bakeoff
   scripts/bakeoff-setup-tests
   go test ./...
   ```

   Review [release notes](release-notes.md) before tagging so externally
   visible CLI contract changes are called out.

3. Optionally run a local archive smoke if GoReleaser is installed:

   ```bash
   cd bakeoff
   goreleaser release --snapshot --clean
   ```

4. Publish by pushing the matching tag from the repository root:

   ```bash
   git push origin main
   git tag v0.1.0
   git push origin v0.1.0
   ```

5. Wait for the `Bakeoff Release` GitHub Actions workflow. It publishes release
   assets only for tag pushes. Manual workflow dispatch runs a snapshot build
   for validation and does not publish a user-installable release.

6. Verify the release contains all v1 assets:

   ```bash
   gh release view v0.1.0 --repo mstefanko/claude-plugins --json tagName,url,assets
   ```

   Required assets:

   ```text
   bakeoff_v0.1.0_darwin_arm64.tar.gz
   bakeoff_v0.1.0_darwin_amd64.tar.gz
   bakeoff_v0.1.0_linux_arm64.tar.gz
   bakeoff_v0.1.0_linux_amd64.tar.gz
   checksums.txt
   ```

7. Then no-Go users can update the marketplace, install Bakeoff, reload
   plugins, and run:

   ```text
   /bakeoff:setup --from-release --version v0.1.0
   /bakeoff:quickstart
   ```

## Version Discipline

For normal internal use, do not add plugin manifest versions unless you want a
deliberate stable release cadence. Without manifest versions, `/plugin update`
can pick up every git commit. Publish GitHub Release assets only when you want
to support the optional no-Go binary setup path for a specific CLI snapshot.

## Developer Fallbacks

`BAKEOFF_GO_BINARY` and `dist/bakeoff` are still useful for development,
air-gapped testing, and debugging. The default internal install remains the
source build performed by `/bakeoff:setup`.
