# Dashboard validation

`release_readiness_dashboard.html` is a standalone offline snapshot of
`release_readiness_audit.json`, whose assessed commit is
`35a9fe6e8e558af7ad31e499d5a1f0e2fe7af349`. It does not reassess a release or query
live CI, issues or protections. No release decision was changed.

Checks completed on 2026-10-12:

- Embedded audit equals the repository JSON; downloading it preserves its exact bytes
  and SHA-256 (`ce9075be877cf3bfbc0a76a4ed9c7b3dab55246d46918e8e6091a3f4d1dd6962`).
- All 14 inventoried source hashes matched the workspace files at build time.
- No external scripts, stylesheets, frames, images or other assets are required.
- JavaScript syntax check passed.
- jsdom checks passed for the 8/12 measurement toggle, 18/17/1 suite filters,
  14/1/0 provenance search results, section anchors, workspace-path copying,
  original-byte audit export and print-button wiring; no DOM script errors.
  Clipboard, download navigation and the print dialog were mocked in these checks.
- Diff whitespace check passed.

Visual desktop/mobile browser rendering was not verified: the local Playwright
browser was absent and its download failed. DOM checks do not validate layout,
actual system clipboard permissions, native downloads or printed pagination.

The dashboard explicitly identifies the audit's incomplete source inventory.
Absolute workspace paths are derived display metadata, not a claim that the
original audit recorded absolute paths or that source files are embedded.
