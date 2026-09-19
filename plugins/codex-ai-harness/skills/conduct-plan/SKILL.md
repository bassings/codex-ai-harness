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
   status text in the plan when the external state disagrees. A wait means
   "checked within the hour", not "checked once": each reconcile that
   confirms an external wait (a CI run, a review) is still pending must
   refresh its task's `(since <timestamp>)` stamp to the current time, per
   step 6, so a queue or review lasting several hours is not mistaken for
   one nobody is watching any more.
4. Advance every independent unblocked task within the user's authority. Use
   `$tdd-task` for implementation and `$review-cycle` after CI is green.
   Parallelize read-only checks; use isolated worktrees and one writer per
   task for concurrent implementation.
5. After each material transition, update the task and append a terse dated
   conductor log entry. External writes such as pushes and PR creation require
   that the user's request includes that delivery scope.
6. If waiting, use an available background wait or monitoring mechanism, keep
   the task active, and record the wait by replacing the task's existing
   `— state:` segment (not adding another one alongside it; only the newest
   `(since <timestamp>)` on the line is honoured) with
   `— state: <status> (since <UTC timestamp>)`, for example
   `— state: awaiting-ci #12 (since 2026-09-19T05:10:00+00:00)`. Use the
   current time with an explicit UTC offset (a trailing `Z`, or `+00:00`); a
   timestamp with no offset at all is refused. This is the only place a wait
   is recorded; write it every time a wait begins, not only the first time.
   If a human decision is genuinely required, write `<plan path>: <question>`
   to `.codex/blocked-on-human` and ask exactly that question. The moment the
   human answers, delete `.codex/blocked-on-human` immediately, before acting
   on the answer: the guard also stops honouring a note older than a day on
   its own, but a stale, un-deleted note left in place for under a day still
   silently parks the plan.
7. When all tasks are merged or otherwise completed, remove the two state
   files and append a `conduct_plan_event` ledger event with outcome `done`.

Never mark work complete merely because a command was launched. Report the
measured state, action taken, and next wake condition.

## The Stop hook enforces this

`hooks/plan_guard_stop.py` is a Codex Stop hook: it runs on every attempt to
end a turn. While `.codex/active-plan` names this plan and it still has
unticked open tasks, it refuses the stop unless the plan is genuinely
covered: an open task's line carries a `(since <timestamp>)` wait recorded
within the last hour, or `.codex/blocked-on-human` names this plan and is
under a day old. So step 6 above is not optional housekeeping: an unrecorded
wait or an unrecorded, undeleted human block means the next stop is refused.
The hook reads only the active-plan marker, the blocked-on-human note and
Codex's own `stop_hook_active` flag; it never reads the ledger, so nothing
here depends on a ledger row being written.

## The fix loop is bounded, and it escalates

Reviewing a task's fixes has a plan, not an open-ended "iterate until clean":

- **Rounds 1 to 3** resume the same implementer. It already holds the
  context for this task, and re-explaining costs more than it buys.
- **Rounds 4 to 5** use a fresh implementer on a more capable model. Three
  rounds failing to close the findings is evidence the implementer cannot see
  the problem, not that another attempt on the same approach will.
- **At round 5**, stop fixing. Adjudicate each open finding by hand: which are
  load-bearing and must block the task, and which are parked with a recorded
  reason for why they are not.

Round counts are per task, not per plan. A review round that finds a defect
the previous round's own fix introduced, rather than a new instance of the
same defect or one the previous round simply missed, stops the task for a
human decision instead of spending the next round on it: that pattern means
the approach itself needs reconsidering, not another fix.
