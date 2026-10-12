# Implementation validation

## Numerical CLI follow-up

The CLI now applies policy-owned numerical limits to recorded pytest properties,
independently of a green pytest outcome. The follow-up gate tests exercise the exact
`1e-4` boundary, above-threshold failures, missing/invalid/duplicate metrics, a bad
case among passing cases, both CLI exit codes and reports, and the archived real
normalization evidence. This extends the original validation below; it does not
rerun or certify the full acceptance suite. The review-only push exception remains
in effect and full repository checks remain incomplete.

Follow-up validation: all 21 gate tests passed (`unittest discover`), including
end-to-end CLI success at `1e-4` and exit 1 at `1.3e-4`. `uv run mypy scripts`
(with its cache outside the repository) passed for all three source files.
`make format` completed with the same tooling warnings recorded below;
`git diff --check` passed. The model normalization implementation was unchanged.

## Original implementation checks

This is a local implementation review, not a release approval. No full candidate
acceptance or trained Gemma-3 checkpoint run was completed.

| Check | Observed result |
| --- | --- |
| `uv run python -m unittest discover -s tests/unit/release_readiness -v` | 15 passed, including an actual pytest subprocess recording failure, skip, xfail and deselection |
| Normalization sentinel pytest run with the evidence plugin | 8 passed; CPU float32, both HT and Bridge |
| `uv run mypy scripts` | Passed, 3 source files |
| `make format` | Completed; formatted the new Python files; existing isort target also reports a nonexistent `format` path and Black lacks notebook extras |
| Explicit Black and isort checks on all five new Python files | Passed |
| `git diff --check` | Passed |
| Readiness CLI supplied only the local normalization evidence | Exit 1, BLOCKED: 17 missing suites plus dirty working tree |
| `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 make test-pr` | Incomplete; interrupted during unit tests after collection of 3,132 cases (42 deselected, 3,090 selected). The run showed existing skips. Model cache is absent; unit fixtures include model/tokenizer downloads. No full-suite pass is claimed. |
| `uv run mypy .` | Incomplete; interrupted after an extended run without a final result. The focused script check above passed. |

The normalization run measured maximum absolute activation error of zero on ordinary
inputs and `3.725290298461914e-9` on low-amplitude inputs, against tolerance `1e-6`.
The deliberately incorrect epsilon-outside-square-root negative control produced
`1.5218294858932495` on low-amplitude inputs. These are synthetic component metrics,
not the historical Gemma-3 incident's model-logit measurements. Sequence lengths
4 and 128 repeat the same activation pattern; they do not test accumulated sequence
effects in a trained model. After this run, metric extraction was changed to detach
the tensor before scalar conversion, removing an autograd warning without changing
the forward computation or assertion.

Raw normalization evidence and the corresponding intentionally blocked local decision
are preserved in `validation/`. They record the original base SHA and dirty state;
they must never be used as clean-commit release evidence. No GitHub Actions run,
live environment protection, gated notebook, GPU/bfloat16 case or issue disposition
was verified by these local checks.

Repository `AGENTS.md` requires a clean full test run before pushing. On 2026-10-12,
the repository owner explicitly authorized pushing this review-only branch with
the incomplete checks documented above. This exception permits branch review;
it does not approve a release, waive the implemented gate, or authorize a PR or merge.
