# Live smoke: running the plugin's hooks for real

Records of running a plugin hook directly against a realistic Codex payload,
or (once the owner agrees to a reinstall) through an installed plugin under
`codex exec`. Each entry names what was run, the Codex version and the date,
and the observed result. Later tasks (C2) add their own entries here.

## Stop hook: plan guard (task C5, 2026-09-19)

Codex version: `codex-cli 0.155.0` (`codex --version`).

**Not run through an installed plugin.** The owner's live Codex install
caches a copy of the plugin at whatever commit it was last added from, and
`codex plugin remove codex-ai-harness@ai-harness-local && codex plugin add
codex-ai-harness@ai-harness-local` would point that live install at this
worktree, changing the owner's environment as a side effect of building a
task, which is out of scope here. This is recorded as pending: the live
`codex exec` run through an installed plugin, with the owner's agreement to
the reinstall, is a follow-up, not done in this task.

What was run instead: `plugins/codex-ai-harness/hooks/plan_guard_stop.py`
invoked directly with `python3`, fed a Stop-hook payload shaped exactly as
Codex 0.155 sends it (`hook_event_name`, `cwd`, `session_id`,
`transcript_path`, `stop_hook_active`, `last_assistant_message`), against a
scratch git repository created with `mktemp -d` and removed afterwards. This
exercises the same script the hooks.json `Stop` entry registers, with the
same stdin contract, short of Codex's own process supervision.

### Run 1: blocked

Scratch repo: `git init`, then `specs/PLAN.md` containing one open task
(`- [ ] C1: build the thing`) and `.codex/active-plan` containing
`specs/PLAN.md`. No `.codex/blocked-on-human` note, no wait recorded on the
task line, `stop_hook_active` false. Re-run 2026-09-19 against the round-3
implementation (fence-awareness removed, rejected-wait wording, bounded
output); the quote below replaces an earlier round's, which the code no
longer prints.

```
$ echo "$PAYLOAD" | python3 plan_guard_stop.py
{"decision": "block", "reason": "Codex plan guard: 1 open task(s) (C1) have no recorded wait and the plan is not parked on a human decision. Record a wait by replacing the open task's \"state:\" segment with, for example, \"state: awaiting-ci #1 (since 2026-09-19T05:55:00+00:00)\"; write .codex/blocked-on-human as \"<plan path>: <question>\"; or tick the remaining tasks before stopping."}
exit: 0
```

Observed: exit 0, one line of valid JSON on stdout with `decision: block` and
a reason naming the open task id and count only, nothing else on stdout.

### Run 2: allowed

A second, empty scratch repo (`git init`, nothing else): no
`.codex/active-plan` marker at all.

```
$ echo "$PAYLOAD" | python3 plan_guard_stop.py
stdout: []
exit: 0
```

Observed: exit 0, stdout empty. This is the no-marker path (AC-C5-3): most
Codex stops have nothing to do with a conducted plan, and this hook says
nothing about them.

### What is not covered here

- An installed-plugin `codex exec` run (see above): pending the owner's
  agreed reinstall.
- Whether Codex actually calls a registered `Stop` hook the way its own
  documentation and the plan's Problem section describe (verified from the
  binary's hook schema, not from a live invocation in this task).
- Interactive-session stop behaviour (for example a client-side "stop"
  keypress) is not distinguished here from a programmatic Stop event; both
  read as the same payload shape to this hook.
