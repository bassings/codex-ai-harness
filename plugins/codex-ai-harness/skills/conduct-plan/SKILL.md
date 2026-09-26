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
6. A wait never ends the turn. Codex cannot wake this session once the turn
   ends, so when a local gate, CI run, review, merge or scan is pending, keep
   polling it within this turn (for example `gh pr checks <N> --watch` or a
   bounded polling loop) until it reaches a terminal state, then update the
   plan and take the next action. While a wait is live, record it by
   replacing the task's existing `— state:` segment (not adding another one
   alongside it) with `— state: <status> (since <UTC timestamp>)`, for example
   `— state: awaiting-ci #12 (since 2026-09-19T05:10:00+00:00)`, and refresh
   that stamp on every check so the plan shows when the wait was last
   confirmed. A status question from the user is answered in passing, never
   as a reason to end the turn.
   If a human decision is genuinely required, write `<plan path>: <question>`
   to `.codex/blocked-on-human` and ask exactly that question. The moment the
   human answers, delete `.codex/blocked-on-human` immediately, before acting
   on the answer: the guard also stops honouring a note older than a day on
   its own, but a stale, un-deleted note left in place for under a day still
   silently parks the plan.
7. When all tasks are merged or otherwise completed, remove the two state
   files and append a `conduct_plan_event` ledger event with outcome `done`.

Never mark work complete merely because a command was launched. Report the
measured state and the action taken, then carry on with the next one.

## The Stop hook enforces this

`hooks/plan_guard_stop.py` is a Codex Stop hook: it runs on every attempt to
end a turn. While `.codex/active-plan` names this plan and it still has
unticked open tasks, it refuses the stop unless `.codex/blocked-on-human`
names this plan and is under a day old. A recorded wait does not exempt a
stop. It refuses up to three times in a row; ticking a task or changing a
task's state starts that count again (refreshing a wait stamp or adding a
log line does not), and after three refusals with no such progress it lets
the stop through and records a `stop_guard` fault in the ledger. No run of
stop attempts is refused more than ten times in total, whatever the edits. Every
refusal is recorded there too, so early stops are counted rather than
self-reported. To pause a conducted plan deliberately, delete
`.codex/active-plan`.

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
