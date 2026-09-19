# Codex AI Harness

A Codex-native counterpart of [claude-ai-harness](https://github.com/bassings/claude-ai-harness). It replaces Claude dynamic
workflows with installable Codex skills and built-in subagent orchestration.

## Included workflows

- `$plan-cycle <spec>` — parallel specialist planning with testable acceptance criteria.
- `$review-cycle [base] [spec]` — read-only, multi-lens branch review.
- `$tdd-task <task>` — one red/green/refactor implementation loop.
- `$conduct-plan <plan>` — reconcile and execute a multi-task delivery plan.
- `$optimise-cycle` — analyse the local run ledger and propose harness improvements.

Plan and review runs keep local, untracked telemetry in
`.codex/harness-ledger.jsonl`. The plugin hook snapshots tracked uncommitted
changes before Bash calls and blocks the most obvious destructive Git commands
when there is work to lose. Plugin hooks require explicit trust when enabled.
Snapshots exclude untracked and ignored files. On the normal fast path they
prune to the newest 20 per checkout; pruning is skipped rather than delaying a
Bash call when the hook reaches its 2.5-second internal deadline. List them with:

```bash
git for-each-ref --format='%(refname) %(creatordate:iso-strict)' refs/harness-snapshots/
```

Recover one tracked file without overwriting the current copy using
`git show <ref>:<path> > <path>.recovered`.

## Install from this checkout

From any directory, register this repository as a local marketplace and install
the plugin:

```bash
codex plugin marketplace add /absolute/path/to/codex-ai-harness
codex plugin add codex-ai-harness@ai-harness-local
```

Plugin hooks require an explicit trust decision when Codex first discovers
them. Start a new Codex conversation after installation so the skills are
rediscovered. To refresh an edited local plugin, remove and add it again.

## Development

From the repository root:

```bash
bin/verify
```

No API key is needed when Codex is already authenticated.

## Runtime differences from the Claude version

Codex performs orchestration in the invoking skill instead of a separate
dynamic-workflow VM. Lens reports remain in subagent threads and only the
synthesis returns to the main thread. Review agents inspect the pinned commit
without changing the user's checkout. Custom trigger overrides live at
`.codex/harness-triggers.json`.
