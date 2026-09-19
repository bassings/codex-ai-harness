---
name: conduct-plan
description: Execute and babysit a multi-task implementation plan by reconciling repository and CI state, advancing unblocked work, and persisting progress. Use when the user asks to conduct, execute, or continue a plan across tasks or PRs.
---

# Conduct a plan

Treat each invocation as a reconcile-act-persist cycle. The plan file is the
durable source of truth; chat memory is not.

1. Read the plan and applicable `AGENTS.md`. If absent, add a `## Tasks`
   checklist with PR-sized items and optional `(needs: T1)` dependencies.
   Allowed states are `queued`, `building`, `pr-open #N`, `awaiting-ci #N`,
   `in-review #N`, `merged`, and `blocked`.
2. Ensure `.codex/active-plan` and `.codex/blocked-on-human` are excluded via
   `.git/info/exclude`, then write the repo-relative plan path to
   `.codex/active-plan`. Never put quoted findings or a human-block note in a
   tracked plan.
3. Reconcile state from Git, open PRs, and CI before acting. Do not trust stale
   status text in the plan when the external state disagrees.
4. Advance every independent unblocked task within the user's authority. Use
   `$tdd-task` for implementation and `$review-cycle` after CI is green.
   Parallelize read-only checks; use isolated worktrees and one writer per
   task for concurrent implementation.
5. After each material transition, update the task and append a terse dated
   conductor log entry. External writes such as pushes and PR creation require
   that the user's request includes that delivery scope.
6. If waiting, use an available background wait or monitoring mechanism and
   keep the task active. If a human decision is genuinely required, write
   `<plan path>: <question>` to `.codex/blocked-on-human` and ask exactly that
   question.
7. When all tasks are merged or otherwise completed, remove the two state
   files and append a `conduct_plan_event` ledger event with outcome `done`.

Never mark work complete merely because a command was launched. Report the
measured state, action taken, and next wake condition.
