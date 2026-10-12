# Release readiness

Run **Release Readiness** (`.github/workflows/release-readiness.yml`) on the candidate
branch before creating a GitHub release. It runs the existing checks and produces
`release-readiness-<attempt>` with `readiness.md` and `readiness.json`. It never publishes.
The release workflow calls the same workflow again for the release commit; PyPI publishing
depends on its success. This does not prevent creating the GitHub release itself.

## What the gate proves

Every suite in `readiness-policy.json` must have evidence from the exact commit,
Actions run ID and run attempt, recorded from a clean working tree. Each collected test must complete setup, call and teardown
once, successfully. Missing or duplicate suites, zero tests, malformed reports, collection
errors, skipped tests, xfail/XPASS, retries and deselections block the release. The ordinary
Checks workflow keeps its existing skip/filter behavior; the release gate refuses to call
that incomplete execution release-ready. A missing HF token cannot yield a passing release.

There is deliberately no waiver or `continue-on-error` switch. In particular, this repository's
existing HT acceptance quarantines and slow-test exclusions mean the initial report may be
BLOCKED. Do not remove tests or edit the policy just to get green. Restore required coverage,
or have maintainers review a separate, explicit release-scope policy change and its risks.
An attempt rerun does not accept evidence from a previous attempt: rerun all required jobs.

## Evidence and review

The release-readiness CLI is `uv run --no-project python scripts/release_readiness.py`.
It reads the JSON evidence emitted by `scripts.release_evidence`; the complete invocation
is below. It exits 1 if any recorded metric exceeds its policy maximum, even when all
pytest phases passed. Equality passes. Missing required metrics, negative values,
booleans, numeric strings, duplicate measurements within a case, NaN and infinity block.
Evidence-provided tolerance properties cannot override the policy.

`readiness-policy.json` requires `max_absolute_logit_delta <= 1e-4` in each Python
acceptance suite, and `max_absolute_activation_delta <= 1e-6` in the normalization suite.
Producers attach measurements using, for example:

```python
record_property("max_absolute_logit_delta", float((actual - reference).abs().max()))
```

Measure every numerical comparison separately after checking both tensors are finite.
The CLI checks every recorded value and requires at least one measurement for each
suite/metric rule; it cannot detect a comparison the producer never recorded. Existing
acceptance tests that do not emit this property need instrumentation before this gate
can pass. This change does not invent Gemma checkpoint evidence. Both decision reports
include the observed values, policy maxima and test IDs for maintainer review.

The opt-in `scripts.release_evidence` pytest plugin records node IDs, all test phases,
omissions, pytest exit code, test properties, Python/platform/dependency versions and command
arguments. JSON is written atomically at session completion; a crash or unavailable suite
leaves missing evidence and blocks. Raw artifacts retain failure details and numerical test
properties. The decision report includes SHA-256 hashes of the evidence and bounded Markdown
diagnostics; its JSON includes every blocker. These are trusted CI outputs, not signed
attestations: protect workflow/policy changes and release permissions through human review.

The required notebook inventory is explicit and currently matches the 14 entries in
`checks.yml`. Change both together after review; a unit test checks inventory drift.
All checks in the reusable workflow must also succeed, including unit tests, formatting and
type checking. Passing this gate establishes execution completeness and recorded numerical compliance within that selected scope,
not correctness of every supported architecture, input, precision or device.

## Numerical coverage and remaining release decisions

`test_release_norm_regression.py` exercises the actual HT RMSNorm and Bridge normalization
components in float32 on CPU with short/long, ordinary/low-amplitude inputs. A float64 oracle
checks absolute activation error, and a deliberately wrong epsilon-outside-square-root
formula must be rejected on sensitive inputs. Metrics are attached with `record_property`.
This sentinel is not a reproduction of a particular historical conversion-table commit and
does not establish Gemma-3 model-logit parity, Gemma weight-offset conversion or bfloat16 SAE
correctness. No incident numbers, private correspondence or issue dispositions are imported
into the repository as test expectations.

Before approving a release, maintainers still need:

- A trained-checkpoint Gemma regression corpus (original short input, failing longer input,
  and architecture boundaries), identical token IDs, pinned HF model/tokenizer revisions,
  float32/eager reference settings, finite values and maximum absolute logit error <= 1e-4.
  Save per-case errors, locations and intermediate comparisons; do not average away failures.
- A demonstration that the same test rejects the buggy conversion and passes the fixed one.
  Confirm the actual historical commits and reproduction conditions first.
- A reproduced cached/live activation comparison in every precision claimed by the release,
  including bfloat16 where supported. Forward float32 parity cannot clear a backward-hook
  or reduced-precision issue. Any included hook refactor needs gradient and cleanup checks.
- Current issue dispositions and the required human review for cross-cutting changes.
  Old spreadsheets or closed issue labels are not substitutes for candidate evidence.
- Verification of live environment/tag protections. Repository YAML alone does not establish
  who can bypass protection or upload artifacts. The existing release token setup is unchanged.

## Local review

Use `uv` in the repository environment. These commands do not publish:

```bash
uv run python -m unittest discover -s tests/unit/release_readiness
TL_RELEASE_SUITE=norm-regression TL_RELEASE_EVIDENCE=/tmp/tl-evidence/norm.json \
  uv run python -m pytest -p scripts.release_evidence \
  tests/unit/components/test_release_norm_regression.py
uv run --no-project python scripts/release_readiness.py \
  --policy release/readiness-policy.json --evidence-dir /tmp/tl-evidence \
  --commit "$(git rev-parse HEAD)" --run-id local --run-attempt local \
  --checks-result success --output-dir /tmp/tl-readiness
```

The last command intentionally blocks when only the norm suite has been collected.
For review of a downloaded Actions artifact set, supply its exact run/attempt and commit,
and the actual checks conclusion. Do not place generated reports inside the evidence directory.
The CLI returns 0 for PASS and 1 for BLOCKED; it writes both reports in either case.

## Branch provenance

This change started from backup commit `33387b7def1ead3a8cba532a729da5599e875873`.
The authorized backup had only `main`, so no `dev` base was available. No model behavior,
dependency versions, quarantine markers or issue state was changed by the gate implementation.
