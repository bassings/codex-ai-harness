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

## Stop hook: bounded refusals under an installed plugin (2026-09-26)

Codex version: `codex-cli 0.157.1`. Run through the installed plugin (added from branch
`fix/stop-guard-persistence` at 115ba0f with the owner's agreement), with the
Stop hook approved in `/hooks` (`hooks.state` in `~/.codex/config.toml`
carries a `...:stop:0:0` trust entry). No `--dangerously-bypass-hook-trust`.

This closes the follow-up recorded above: the earlier entry ran the script
directly, and the hook had in fact never run under Codex because its trust
entry was missing.

Scratch repo: `git init`, `PLAN.md` with one open task
(`- [ ] **T1 — wait for a human to say done** — state: queued`),
`.codex/active-plan` naming it, no `.codex/blocked-on-human` note. Then:

```
codex exec -s read-only --json "This is a harness test. Do not edit, create or
delete any file and do not run any command. Reply with the single word
'stopping' and end your turn. If you are told you cannot stop, reply with the
single word 'again' and try to end your turn again."
```

Observed: four agent messages (`stopping`, `again`, `again`, `again`),
exit 0, and these `stop_guard` rows in `.codex/harness-ledger.jsonl`:

| Attempt | outcome | refusals | chain_refusals |
|---|---|---|---|
| 1 | blocked | 1 | 1 |
| 2 | blocked | 2 | 2 |
| 3 | blocked | 3 | 3 |
| 4 | aborted | 3 | 3 |

The counter file in the git directory was removed after the give-way. So
Codex runs the approved Stop hook, feeds a refusal back to the agent, and sets
`stop_hook_active` on the retry: the count reached 2 and 3 instead of
restarting at 1, which is the behaviour every refusal limit depends on.
