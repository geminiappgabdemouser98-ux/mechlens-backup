# Maintaining the release-readiness gate

Run commands from the repository root in Bash with `uv`. This branch is for
review; a passing implementation test suite does not approve a release.

## What is generated, and what is curated

| File | Purpose / producer |
| --- | --- |
| `release/readiness-policy.json` | Reviewed suite inventory and numerical limits |
| `scripts/release_evidence.py` | Opt-in pytest plugin producing raw execution JSON |
| `scripts/release_readiness.py` | Gate CLI producing `readiness.json` and `readiness.md` |
| `release_readiness_audit.json` | Curated audit combining a CLI decision, validation results, measurements, provenance and limitations |
| `release_readiness_dashboard.html` | Self-contained, static presentation of that audit plus separately sourced historical Gemma-3 figures |

**There is no checked-in generator for the enriched audit or dashboard.** The CLI
only regenerates its two decision reports. Do not rename `readiness.json` to
`release_readiness_audit.json`: their schemas differ. The dashboard contains
rendered HTML as well as embedded data; changing only its JSON does not refresh
the visible decision, cards or tables. The manual refresh procedure below is
necessary until a reviewed generator is added.

The committed audit assesses `35a9fe6e8e558af7ad31e499d5a1f0e2fe7af349`, not the
latest branch head. It is BLOCKED with 20 reasons: 17 missing suites, one archived
norm suite with a mismatched commit and unrecorded working-tree state, and an
unknown full-checks result. It does not establish the next release version or
current issue dispositions. These are snapshot facts, not live dashboard queries.

## Run an audit against candidate evidence

Use a separate evidence directory for each exact commit, run ID and attempt.
Copy/download only raw execution and reviewed supplemental evidence into it.
The CLI recursively reads every JSON file, so keep decision reports, the enriched
audit and synthetic fixtures outside that directory.

```bash
uv sync
uv run --no-project python scripts/release_readiness.py --help

# Replace these with the identity and conclusion of the actual evidence run.
CANDIDATE_SHA=FULL_40_CHARACTER_COMMIT_SHA
EVIDENCE_RUN_ID=ACTUAL_ACTIONS_RUN_ID
EVIDENCE_RUN_ATTEMPT=ACTUAL_ATTEMPT_NUMBER
CHECKS_RESULT=unknown
EVIDENCE_DIR=/tmp/candidate-release-evidence
REPORT_DIR=/tmp/candidate-release-report

uv run --no-project python scripts/release_readiness.py \
  --policy release/readiness-policy.json \
  --evidence-dir "$EVIDENCE_DIR" \
  --commit "$CANDIDATE_SHA" \
  --run-id "$EVIDENCE_RUN_ID" \
  --run-attempt "$EVIDENCE_RUN_ATTEMPT" \
  --checks-result "$CHECKS_RESULT" \
  --output-dir "$REPORT_DIR"
gate_exit=$?
printf 'Gate exit: %s\n' "$gate_exit"
```

Use `success` only when the complete checks workflow for that candidate/run
actually succeeded. `unknown`, `failure`, `cancelled` and `skipped` block. Do not
infer success from the gate unit tests or one green demo sweep. In a shell with
`set -e`, capture the status with an `if` statement so an expected block does not
prevent report inspection; do not suppress failure in a publishing pipeline.

Exit **0** means PASS; exit **1** means BLOCKED. Both normal outcomes write
`readiness.json` and `readiness.md`. Argument errors, crashes or missing reports
are execution failures, never approval. Review `blockers`, per-suite reasons,
`measurements`, `contradictions` and source paths/hashes in the JSON.

For CI, run the **Release Readiness** workflow on the candidate branch
(`.github/workflows/release-readiness.yml`). It calls the checks workflow,
downloads `release-evidence-*` artifacts for that attempt and uploads
`release-readiness-<attempt>`. It has no publishing steps. To reproduce locally,
download that attempt's raw evidence and use the exact workflow identity and
checks conclusion. The publisher in `release.yml` depends on this wrapper;
repository configuration alone does not verify live permissions or protections.

### Reproduce the archived audit's gate decision

This evaluates existing bytes; it does not rerun model tests or refresh evidence.

```bash
ARCHIVE_DIR=$(mktemp -d /tmp/release-archive.XXXXXX)
mkdir "$ARCHIVE_DIR/evidence"
cp release/validation/norm.json "$ARCHIVE_DIR/evidence/norm.json"
uv run --no-project python scripts/release_readiness.py \
  --policy release/readiness-policy.json \
  --evidence-dir "$ARCHIVE_DIR/evidence" \
  --commit 35a9fe6e8e558af7ad31e499d5a1f0e2fe7af349 \
  --run-id local --run-attempt local --checks-result unknown \
  --output-dir "$ARCHIVE_DIR/report"
```

Expected: exit 1, BLOCKED, 20 blockers with the current policy and archived input.
A policy/code change can change that result; retain their hashes with the report.

## Gate states and acceptance rules

| State / label | Meaning |
| --- | --- |
| `PASS` / `ready: true` | The evaluated scope satisfied its checks. An implementation-test PASS is not release acceptance. Overall CLI PASS requires all required evidence and successful full checks. |
| `BLOCKED` / `ready: false` | One or more requirements failed or could not be established; do not publish on this decision. |
| `PASS_OBSERVED_NOT_QUALIFYING` | Archived numbers meet their limits, but provenance prevents them qualifying for this candidate. |
| `NOT_EVALUATED_FOR_CANDIDATE` | No candidate evidence for this review dimension; synthetic tests do not fill the gap. An absent optional summary is not itself a CLI blocker. |
| `UNKNOWN_BLOCKING` | The full-checks conclusion is unverified; the overall gate blocks. |
| Missing | No execution record for a required suite. |
| Invalid | Evidence is present but does not meet execution, numerical or provenance requirements. |
| Within limit / Sensitivity confirmed | A measurement or negative-control assertion passed; it does not validate the candidate's provenance or entire suite. |

The last three labels are dashboard descriptions, not extra CLI exit codes.
The current policy requires 18 suites: acceptance on Python 3.10, 3.11 and 3.12,
one norm regression suite, and 14 explicitly named notebooks. Keep notebook
inventory changes synchronized with `.github/workflows/checks.yml`.

Acceptance requires recorded `max_absolute_logit_delta <= 1e-4`; norm regression
requires `max_absolute_activation_delta <= 1e-6`. Equality passes. Every recorded
policy metric is checked; averaging passing and failing cases cannot clear a
regression. Missing required metrics, invalid/nonfinite/negative values and
repeated metrics within a case block. The policy defines limits, not the evidence.

Execution records must match commit/run/attempt, explicitly record a clean
working tree, have successful pytest completion, no deselection or collection
problems, and complete passing setup/call/teardown phases without retries,
skips or xfails. Duplicate execution evidence blocks. Do not edit provenance
fields to make archived evidence qualify; rerun on the intended clean candidate.

Optional `release-summary` records must enumerate every non-summary JSON input
in `sources`. A summary cannot satisfy a suite. Supplemental `regression-evidence`
records cannot replace execution evidence either. A true regression flag or
above-limit measurement blocks even if a summary says `all_passed: true`; the
CLI reports contradictions. Formats and limitations are in `release/README.md`.
The CLI does not read prose triage notes or discover sources absent from the bundle.

## Regenerate the enriched JSON and dashboard

1. Run the CLI on the new evidence bundle and preserve both reports, including
   a blocked result. Record the exact command, exit code and evaluation identity.
2. Refresh `release_readiness_audit.json` as a reviewed document. Replace
   `raw_cli_decision` with the new `readiness.json`; derive `release_decision` and
   `blockers` from it. Update `assessed_commit`, UTC generation time and scope.
   Keep release version unverified unless independently established. Do not set
   `publish_authorized` from a passing CLI result.
3. Recompute required/qualifying/missing/invalid suite counts and gate states.
   Populate measurements from raw evidence with their case IDs, source paths,
   operators and limits. Mark whether each qualifies for this candidate. Keep
   deliberately wrong-formula negative controls distinct from acceptance metrics.
   Refresh implementation-test results only from a new saved test log; never
   carry forward a historical pass as a new run.
4. Refresh `source_provenance`: include each actual input, policy, evaluator,
   workflow, relevant tests/fixtures and review record with its repository path,
   SHA-256 and verified Git identity (or null for an uncommitted output).
   Include `checks.yml`, which the existing 14-file inventory omitted. State
   remaining omissions explicitly. Resolve workspace display paths from the
   actual checkout root; a hash is an integrity check, not a signed attestation.
5. Refresh all rendered sections of `release_readiness_dashboard.html`: decision,
   assessed identity, counts, acceptance rows, suite states/reasons, open items,
   limitations and provenance. Retain inline CSS/JS so it opens offline. Do not
   invent owners or current issue states. Historical Gemma figures stay separate:
   approximately `1.3e-4` before the fix (about 30% above `1e-4`) and `2.9e-5`
   after it (71% below). Keep the source link and approximation label; neither
   number clears a current-candidate blocker. Both bars use the same scale.
6. Update the `embedded-evidence` script payload: `audit` must equal the refreshed
   JSON, `audit_raw_text` must contain its exact text, and
   `dashboard_provenance.audit_sha256` must hash those exact file bytes. Refresh
   workspace root/path metadata too. Preserve the separately sourced
   `historical_gemma3` object. Escape `<` as `\u003c` when serializing JSON into
   HTML, so source text cannot terminate the script element.
7. Compare rendered rows/counts with the JSON, test filters, source search,
   copy/export/print controls and open it at desktop/mobile widths. Verify that
   exported JSON bytes equal the repository file. Record checks and any unverified
   behavior in `release/validation/dashboard-validation.md`.

Do not use a temporary-session builder as a general generator: the original
builder was snapshot-specific and later dashboard changes were applied separately.
A future automated renderer should derive every visible state from the refreshed
audit and preserve the historical comparison. The existing validation record
covers DOM/numeric checks; browser rendering and printed pagination remain unverified.

## Tests with uv

```bash
# Gate logic, recorder, CLI exit codes, workflow wiring and synthetic conflicts.
uv run python -m unittest discover -s tests/unit/release_readiness -v

# CPU component sentinel; save evidence outside the checkout.
LOCAL_EVIDENCE_DIR=$(mktemp -d /tmp/release-norm.XXXXXX)
GITHUB_RUN_ID=local GITHUB_RUN_ATTEMPT=local \
TL_RELEASE_SUITE=norm-regression \
TL_RELEASE_EVIDENCE="$LOCAL_EVIDENCE_DIR/norm.json" \
  uv run python -m pytest -p scripts.release_evidence \
  tests/unit/components/test_release_norm_regression.py

# Focused typing check; the full repository check remains separately required.
uv run mypy scripts
```

Run evidence collection from a clean committed checkout; untracked notes also
make the recorder mark it dirty. A norm-only bundle still lacks 17 required suites.
The sentinel tests CPU float32 components; it is not trained Gemma logit parity,
a GPU/bfloat16 replay or proof of sequence-length robustness. The 2.16.0-pattern
fixtures are synthetic and must never enter a candidate evidence bundle.

For broader checks, source the configured `.env` before commands that access HF:

```bash
set -a
source .env
set +a
make format
uv run mypy .
make test-pr
uv run build-docs
```

These are repository checks, not substitutes for the full release workflow.
Model access, caches and credentials may be needed. Never add skips or weaken
limits to make the gate green. See `release/VALIDATION.md` for the incomplete
full-suite/type-check history and the review-only push exception. That exception
does not waive release requirements. No PR or merge is authorized by these notes.
