---
name: tdd-task
description: Implement one scoped repository task with an explicit red-green-refactor loop and focused verification. Use when the user requests TDD or asks the harness to implement a plan task.
---

# TDD task

Work on one bounded task. Read applicable `AGENTS.md` and the referenced spec
before editing. If the user did not authorize implementation, stop after a test
plan.

1. Restate the behavior and identify its acceptance criteria. Inspect the real
   execution path and choose the smallest test that distinguishes the desired
   behavior from the current behavior.
2. RED: add or update the test first. Run the narrowest relevant command and
   capture evidence that it fails for the intended missing behavior, not a
   fixture, syntax, environment, or unrelated failure. If a meaningful failing
   test cannot be produced, explain why before changing production code.
3. GREEN: make the smallest production change that passes that test. Preserve
   unrelated user changes and avoid broad refactors.
4. REFACTOR only when it reduces demonstrated duplication or complexity. Keep
   the test green after each refactor.
5. Run focused tests, then the repository's proportionate broader gate. Review
   the diff for accidental changes and verify each in-scope criterion.
6. Append a `tdd_task` ledger event with outcome `done`, `blocked`, or
   `aborted`, relevant lens `qa`, and numeric test/finding counts only.

Use one implementation subagent only when isolation would materially help;
give it exclusive write ownership and wait for it before touching the same
files. Never run multiple writers against one checkout.

Return changed files, red and green evidence, final verification, and anything
left unverified. Do not commit or open a PR unless the user asks.
