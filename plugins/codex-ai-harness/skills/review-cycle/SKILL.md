---
name: review-cycle
description: Review a branch or working change with parallel read-only specialist Codex subagents, verify acceptance criteria, and synthesize evidence-backed findings. Use for multi-lens review, pre-PR review, or a review cycle.
---

# Review cycle

Read `../plan-cycle/references/harness-contract.md` and
`../plan-cycle/references/lenses.md` completely before dispatching agents.

## Workflow

1. Read applicable `AGENTS.md`. Resolve the base from the user's argument,
   otherwise the remote default branch, otherwise `main` then `master`. Record
   the current tip SHA and tree SHA. Never switch, reset, or mutate the user's
   checkout during review.
2. Compute the committed diff `base...tip` and separately record working-tree
   changes. The review target is the pinned tip unless the user explicitly asks
   to include uncommitted work. Locate the named spec or infer it from changed
   files and acceptance-criterion references.
3. Select lenses from changed paths and behaviors. Always run security and QA;
   add product, design, accessibility, architecture, data, and operability per
   the roster. Architecture also runs for UI diffs. Merge valid overrides from
   `.codex/harness-triggers.json` using
   `../plan-cycle/references/triggers.md`; an invalid file is a visible warning
   and falls back to defaults.
4. Spawn one subagent per lens in parallel and explicitly instruct it to remain
   read-only. This is behavioral, not a separate sandbox: subagents inherit the
   parent session's permissions. Give it the base, pinned tip, spec, its single
   lens section, and the review output contract. Tell it to inspect the pinned
   tree with `git diff` and `git show`; it must not checkout another revision in the user's
   working directory or edit files. Do not give it the expected tree hash.
5. Wait for all lenses. Independently compute the pinned tree hash and reject a
   lens result whose `head_tree_measured` differs. Record `head_sha_measured`
   as drift evidence but do not require it to equal the pinned tip.
6. After domain lenses finish, spawn one fresh verification subagent with the
   diff and output contract but without the plan rationale or lens conclusions.
   Ask it to challenge evidence and find uncovered correctness defects.
7. Synthesize by severity, then file and line. Deduplicate only when root cause
   and fix are the same. Report every AC as PASS, FAIL, or UNVERIFIABLE; a
   missing or blocked lens cannot become PASS. Findings outside any AC are
   explicitly labelled spec gaps.
8. Append a `review_cycle` ledger event with outcome `done` or `blocked`, lens
   names, per-lens verdicts and spec-gap counts, aggregate counts, spec path
   when known, and no free-form excerpts.

Return findings first. If none survive synthesis, say so explicitly, then give
coverage, AC verdicts, and residual uncertainty. Do not implement fixes unless
the user separately asks for them.
