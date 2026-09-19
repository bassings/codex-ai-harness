# codex-ai-harness

A Codex plugin providing plan, review, TDD, conduct and optimise workflows.

## Commands

| Command | What it does |
|---|---|
| `bin/verify` | Full test suite; CI and the pre-push hook run this |
| `bin/setup-hooks.sh` | Enable the pre-push gate in this clone |

## Hard rules

- Standard library Python only. No dependencies, no install step.
- Every hook or script change is test-first, and a new guard is proven by
  breaking it and watching a test fail.
- The ledger never records free text: counts, enums and repo-relative paths only.
- Harness run state under `.codex/` is never committed.

## Key locations

- `plugins/codex-ai-harness/skills/` workflow instructions
- `plugins/codex-ai-harness/hooks/` Codex lifecycle hooks
- `plugins/codex-ai-harness/scripts/` deterministic helpers the skills call
- `plugins/codex-ai-harness/tests/` the suite
