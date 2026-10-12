# Synthetic 2.16.0 failure pattern

A green short-prompt run and all-passed summary coexist with a longer-prompt
regression. These files are invented test data, not exported historical artifacts
or a trained Gemma replay. The fake SHA/run IDs and illustrative measurements
exercise evidence reconciliation independently of model execution.

Run the corresponding checks from the repository root:

```bash
uv run python -m unittest discover -s tests/unit/release_readiness -k SummaryConflictTests
```

The tests use a one-suite policy with maximum logit delta `1e-4`. The fixture's
`5e-5` short-prompt value passes; its `2e-4` long-prompt value fails despite the
summary claiming success. The end-to-end test checks exit code 1 and report
contradictions, then changes the synthetic finding to a non-regression at `2e-5`
and requires exit code 0. These numbers are illustrative, not incident measurements.
