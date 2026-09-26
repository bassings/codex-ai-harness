# Changelog

## Unreleased

### Fixed

- Bundled hook commands now find an installed harness copy when Codex keeps an
  active session's old plugin root after an upgrade removes that cache entry.
  This keeps both the Stop plan guard and the PreToolUse Git guard available
  until a new session loads the updated plugin.

## 0.2.0 (2026-09-26)

### Fixed

- The conduct-plan Stop hook now keeps a conducted plan running. A recorded
  wait no longer lets the agent end its turn (Codex cannot wake a session
  once its turn has ended), and refusals are bounded: at most 3 in a row with
  no change to open-task state, and at most 10 without the open-task count
  falling, before the stop is allowed and recorded as a fault. Previously any
  second stop attempt was allowed. (#5)
- Every refusal and give-way is written to the ledger as a `stop_guard` row,
  so early stops are counted rather than self-reported. (#5)
- Task ids written in the bold `**T7 — ...**` form are recognised. (#5)

### Notes

- A Codex hook only runs once it is approved in `/hooks`. Approve the Stop
  hook after installing or upgrading, and check that `~/.codex/config.toml`
  carries a `...:stop:0:0` trust entry.

## 0.1.0

- Initial Codex plugin: plan, review, TDD, conduct and optimise workflows,
  the PreToolUse Git guard and the conduct-plan Stop hook.
