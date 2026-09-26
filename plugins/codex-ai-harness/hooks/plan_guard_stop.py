#!/usr/bin/env python3
"""Codex Stop hook: refuse to end a turn while a conducted plan still has
open tasks and is not parked on a human decision.

Why a wait is not an exemption (2026-09-26): Codex has no equivalent of
Claude Code's /loop, so nothing wakes a session once its turn ends. An
earlier version let the turn end while an open task recorded a wait begun
within the hour; in practice that was a licence to stop at every CI run,
merge or scan and never come back. A pending external state is now
something to keep polling within the turn, not a reason to stop.

Why refusals are counted: Codex sets stop_hook_active on the stop attempt
that follows a refusal, and an earlier version allowed any such attempt,
so a second attempt always got out. The guard now refuses up to
MAX_CONSECUTIVE_REFUSALS times in a row. A chain of refusals continues
only while Codex sets stop_hook_active; any attempt without it starts a
new chain, so a count left behind by an interrupted turn never shortens
the next one, however soon that turn's first stop attempt arrives. (An
earlier version also continued a chain for two minutes after a refusal,
which let a user's quick reply to an interrupted turn end that turn with
no refusal at all.) The count is keyed on a
hash of the open task lines with their "(since ...)" stamps removed: a
ticked task or a changed task state is progress and starts the count
again, while refreshing a stamp or appending a log line is not, so an
agent that keeps trying to stop without moving any task is let go after
the limit, and that is recorded as a harness fault rather than passing
silently. Rewording a task's state resets that count too, so a chain
also has an overall cap, MAX_CHAIN_REFUSALS, that rewording cannot
reset. Only real progress resets it: the chain records the lowest number
of open tasks it has seen, and an attempt with fewer open tasks than that
starts the overall count again and lowers the minimum. Because the
minimum only ever goes down, ticking and unticking the same task buys
nothing: a chain is released after MAX_CHAIN_REFUSALS refusals without
its open count falling, so a plan whose agent ticks a task between
attempts is never released with tasks open, and the hook still cannot
hold a session indefinitely, since the open count can fall only so many
times. The count lives in the git directory (never the working tree,
so it can never be committed), is never written through a symlink, and if
it cannot be kept at all the guard falls back to Codex's own
stop_hook_active flag: one refusal, never an unbounded loop.

Every refusal, and every time the guard gives way, appends one ledger row
(kind stop_guard; counts only, plus the repo-relative plan path) through
the harness's own ledger writer, so the optimiser can count early stops
instead of relying on the agent to report them. The ledger is written,
never read: the decision still comes only from the marker, the plan, the
blocked-on-human note and the refusal count (AC-SIMP-12 as amended
2026-09-26). A telemetry failure never changes the decision, and main()
prints and flushes the decision before any telemetry is written, so a
slow write cannot push the decision past the hook's timeout.

The marker, note and plan live at the repository ROOT, never at cwd: a
Codex session's cwd is often a subdirectory, so the root is resolved
first and every path is built under it.

The blocked-on-human note is ignored, the same as if it did not exist,
once its age falls outside [-FUTURE_TOLERANCE, NOTE_MAX_AGE]: too old
(conduct-plan's own instructions are to delete it the moment a human
answers, but a note left behind by accident must not park the plan
indefinitely) or, symmetrically, dated too far in the future to be
honoured forever either. Its declared plan is found by trying each ':'
in the note in turn and accepting the first prefix that resolves to the
active plan's path, which is what lets "PLAN.md: question", "PLAN.md:
question" with no space, and the question on its own line all work
without guessing at a delimiter.

Open tasks are detected loosely (-, *, + or a numbered bullet, any
indentation, including nested lines), with NO fenced-code exemption: an
earlier version skipped ``` and ~~~ blocks, and review found five
distinct fence shapes (unclosed, a longer fence nesting a shorter one,
tilde nesting backtick, an indented marker, an unclosed one inside a
list item) that each defeated a simple open/close toggle and let a real
open task afterward silently read as ticked -- an allow where the guard
should have blocked. An example task line inside a fence now simply
counts as open instead: this can only over-block, never allow silently,
which is the direction this guard is meant to fail in. A task's id --
the only part of a task line ever echoed into a message -- is captured
strictly and capped in length, per AC-SEC-12, from either "T7: ..." or
the bold "**T7 — ...**" form; when no open line yields a capturable id,
the reason says so rather than rendering an empty list.

Fails open throughout: a symlinked or unreadable marker or note, a plan
path outside the repository root, a missing or oversized plan, a
malformed marker, or any exception all end in allow, never in a block,
per AC-SEC-12 and AC-OPS-13. The allow paths that are diagnostically
interesting write one line to stderr naming what happened -- never to
stdout, which stays empty on every allow. The marker, plan and note are
each decoded with errors="replace", so one stray non-UTF-8 byte degrades
to a replacement character rather than turning the guard off.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HOOK_NAME = "plan_guard_stop"
MARKER_RELATIVE = Path(".codex") / "active-plan"
NOTE_RELATIVE = Path(".codex") / "blocked-on-human"
COUNTER_NAME = "codex-stop-guard.json"
TELEMETRY_WRITER = Path(__file__).resolve().parents[1] / "scripts" / "ledger.py"
MAX_CONSECUTIVE_REFUSALS = 3
MAX_CHAIN_REFUSALS = 10
NOTE_MAX_AGE = dt.timedelta(hours=24)
FUTURE_TOLERANCE = dt.timedelta(minutes=5)
MAX_READ_BYTES = 1024 * 1024
MAX_IDS_LISTED = 10
GIT_TIMEOUT_SECONDS = 2
# A note is expected to be a short "<plan path>: <question>" line; bounding
# how much of it is tried as a candidate path keeps a pathological note
# (thousands of colons) from forcing thousands of filesystem resolutions.
MAX_NOTE_COLON_ATTEMPTS = 200
# Removed from task lines before hashing, so refreshing a wait stamp is not
# mistaken for progress. Bounded so a pathological line cannot be slow.
SINCE_RE = re.compile(r"\(since [^)\n]{0,64}\)")

# Loose detection of an open checklist line: -, * or + or "1.", any
# indentation. This decides whether the plan has open work at all.
OPEN_TASK_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\[ \]")
# Strict id capture, applied only to lines the loose check already matched:
# "T7: ..." or the bold "**T7 — ...**" form. Bounded length (AC-SEC-12):
# the rest of the line -- description, injected text, anything -- is
# never captured or echoed.
ID_CAPTURE_RE = re.compile(
    r"^\s*(?:[-*+]|\d+\.)\s+\[ \]\s*(?:\*\*)?([A-Z]{1,8}[0-9]{1,4})(?::|\*\*|\s+[—–-]\s)"
)

REASON_TEMPLATE = (
    "Codex plan guard: {count} open task(s) ({ids}) and the plan is not "
    "parked on a human decision (refusal {refusal} of {limit}; {chain} of "
    "{chain_limit} without a task ticked). Codex cannot "
    "wake this session once the turn ends, so a pending local gate, CI run, "
    "review, merge or scan is not a reason to stop: keep polling it within "
    "this turn until it reaches a terminal state, update the plan, then take "
    "the next action. Stop only by ticking every task, or, when a human "
    'decision is genuinely required, by writing .codex/blocked-on-human as '
    '"<plan path>: <question>". After {limit} refusals with no task ticked or '
    "changed state, or {chain_limit} in a row with no task ticked, the stop "
    "is allowed and recorded as a harness fault."
)


def repository_root(cwd: Path) -> Path | None:
    """The repository root for cwd, or None when it cannot be determined.

    Same approach as the harness's telemetry writer uses for the same
    purpose: one git rev-parse --show-toplevel call. Any failure (not a
    repository, git missing, a timeout) returns None rather than raising,
    so the caller's only choice on an unknown root is to allow.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, text=True, capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except (OSError, ValueError):
        return None


def marker_exists_above(cwd: Path) -> bool:
    """Whether .codex/active-plan exists at cwd or any ancestor directory.

    Used only to decide whether a root-resolution failure is worth a
    stderr note; the hook still allows either way.
    """
    current = cwd
    while True:
        if (current / MARKER_RELATIVE).exists():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def resolve_within_root(root: Path, candidate: str) -> Path | None:
    """candidate resolved against root, or None if it escapes root.

    Covers both halves of AC-SEC-12: a candidate that resolves outside the
    repository (a plan path such as ../../etc/passwd) comes back None the
    same way an absolute path elsewhere in the filesystem would.
    """
    try:
        candidate_path = Path(candidate)
        joined = candidate_path if candidate_path.is_absolute() else root / candidate_path
        resolved = joined.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def read_capped(path: Path, limit: int = MAX_READ_BYTES) -> str | None:
    """The file's text, or None when it is larger than limit bytes.

    Checked by stat() before reading, so an oversized file is never
    partially loaded into memory first. Decoded with errors="replace"
    (round 3, item 9): one stray non-UTF-8 byte anywhere in the marker,
    plan or note must not raise and turn the guard off.
    """
    if path.stat().st_size > limit:
        return None
    return path.read_text(encoding="utf-8", errors="replace")




def open_task_lines(plan_text: str) -> list[str]:
    """Every open-checklist line, several common styles (-, *, + or a
    numbered bullet, any indentation). No fenced-code exemption; see the
    module docstring for why."""
    return [line for line in plan_text.splitlines() if OPEN_TASK_LINE_RE.match(line)]




def note_names_plan(root: Path, plan_path: Path, now: dt.datetime) -> bool:
    """Whether .codex/blocked-on-human is live and declares this plan.

    "Live" means: not a symlink, its age within [-FUTURE_TOLERANCE,
    NOTE_MAX_AGE] of now (a future-dated note is not honoured forever
    either), and some prefix of its text -- split at each ':' in turn,
    accepting the first one that resolves to plan_path -- names this
    plan. Trying every colon rather than guessing a fixed delimiter is
    what lets "PLAN.md: question" with no space, a path containing its
    own colon, and the question on the next line all work without a
    special case each.

    The loop stops at the first colon followed by whitespace, even when
    that candidate does not match. Without that stop, a note written for
    a DIFFERENT plan could exempt this one: Path.resolve() collapses a
    ".." lexically even through a path component that never existed on
    disk, so a later, bogus candidate spanning past the real delimiter
    and into the note's own free-text question -- for example
    "OTHER.md: waiting on docs/../PLAN.md: ok?" -- could resolve straight
    back to this plan's real path. The real "<path>: <question>"
    delimiter is always the first colon-then-whitespace, so nothing past
    it can legitimately be part of the declared path.
    """
    note = root / NOTE_RELATIVE
    if note.is_symlink() or not note.is_file():
        return False
    try:
        mtime = dt.datetime.fromtimestamp(note.stat().st_mtime, tz=dt.timezone.utc)
    except OSError:
        return False
    age = now - mtime
    if not (-FUTURE_TOLERANCE <= age <= NOTE_MAX_AGE):
        return False
    text = read_capped(note)
    if text is None:
        return False
    text = text.lstrip("﻿")
    attempts = 0
    for index, ch in enumerate(text):
        if ch != ":":
            continue
        attempts += 1
        if attempts > MAX_NOTE_COLON_ATTEMPTS:
            break
        candidate = text[:index].strip().strip("`")
        if not candidate:
            continue
        declared_path = resolve_within_root(root, candidate)
        if declared_path is not None and declared_path == plan_path:
            return True
        if text[index + 1:index + 2].isspace():
            break  # the first colon followed by whitespace ends the declared path
    return False


def git_directory(root: Path) -> Path | None:
    """This checkout's own git directory (per worktree), or None.

    The refusal count lives here rather than under .codex/ so that it can
    never be committed and needs no exclude entry.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            cwd=root, text=True, capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS, check=True,
        )
        return Path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def read_state(counter: Path) -> dict:
    """The saved chain state; {} when the file is absent, a symlink,
    unreadable or malformed."""
    try:
        if counter.is_symlink() or not counter.is_file():
            return {}
        data = json.loads(read_capped(counter, 4096) or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def count_field(state: dict, key: str) -> int:
    value = state.get(key)
    return value if isinstance(value, int) and value > 0 else 0


def lowest_open_tasks(state: dict) -> int | None:
    """The lowest open-task count the chain has recorded, or None when the
    field is missing or is anything but a positive integer (a bool is not
    one, although Python counts it as an int)."""
    value = state.get("min_open_tasks")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def chain_continues(payload: dict) -> bool:
    """Whether this attempt belongs to the chain the saved state records:
    only when Codex says so."""
    return bool(payload.get("stop_hook_active"))


def write_state(counter: Path, state: dict) -> bool:
    """Record the state by writing a fresh file and renaming it over the
    counter. The rename replaces a symlink rather than following it, and
    the fresh file is opened with O_EXCL | O_NOFOLLOW. False on failure."""
    staging = counter.with_name(f"{counter.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(staging, flags, 0o600)
        try:
            os.write(fd, json.dumps(state).encode())
        finally:
            os.close(fd)
        os.replace(staging, counter)
        return True
    except OSError:
        try:
            staging.unlink()
        except OSError:
            pass
        return False


def clear_refusals(counter: Path | None) -> None:
    if counter is None:
        return
    try:
        if counter.is_symlink() or counter.is_file():
            counter.unlink()
    except OSError:
        pass


def record(root: Path, plan_rel: str, outcome: str, counts: dict[str, int]) -> None:
    """Append one stop_guard row through the harness's telemetry writer.

    Loaded by path rather than imported, because the hook runs from the
    plugin cache with no package on sys.path. Any failure is swallowed:
    telemetry must never change the decision.
    """
    try:
        spec = importlib.util.spec_from_file_location("codex_harness_telemetry", TELEMETRY_WRITER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ensure_excluded(root)
        entry = module.sanitize(
            {"kind": "stop_guard", "outcome": outcome, "spec": plan_rel, "counts": counts},
            root,
        )
        module.append(entry, root)
    except Exception as exc:  # noqa: BLE001 -- see docstring
        print(f"{HOOK_NAME}: could not record telemetry ({type(exc).__name__})", file=sys.stderr)


def decide(
    payload: dict, cwd: Path, now: dt.datetime, deferred: list | None = None,
) -> tuple[str | None, str | None]:
    """Return (block_reason, stderr_note); both None is a silent allow.

    Telemetry rows are written immediately, or appended to deferred as
    argument tuples for record() when the caller wants to emit the decision
    first (main() does).
    """
    def emit(*row) -> None:
        if deferred is None:
            record(*row)
        else:
            deferred.append(row)

    # The marker and the note both live at the REPOSITORY root (that is
    # what .codex/active-plan and conduct-plan's own instructions assume),
    # never at cwd, so the root is resolved before either path is built.
    root = repository_root(cwd)
    if root is None:
        note = None
        if marker_exists_above(cwd):
            note = (f"{HOOK_NAME}: could not resolve a repository root for "
                     f"{cwd}, but a .codex/active-plan exists at or above it")
        return None, note

    marker = root / MARKER_RELATIVE
    if marker.is_symlink() or not marker.is_file():
        # No marker at all: AC-C5-3, silent. A symlinked marker: AC-SEC-12.
        return None, None

    marker_text = read_capped(marker)
    if marker_text is None:
        return None, None  # oversized marker: treated as malformed

    plan_rel = marker_text.lstrip("\ufeff").strip()
    if not plan_rel:
        return None, None  # malformed marker: nothing named, nothing to check

    plan_path = resolve_within_root(root, plan_rel)
    if plan_path is None:
        return None, None  # AC-SEC-12: plan path resolves outside the repo

    if not plan_path.is_file():
        return None, f"{HOOK_NAME}: {marker} names a plan that does not exist"

    plan_text = read_capped(plan_path)
    if plan_text is None:
        return None, (f"{HOOK_NAME}: {marker} names a plan larger than "
                       f"{MAX_READ_BYTES} bytes; skipping it")

    git_dir = git_directory(root)
    counter = git_dir / COUNTER_NAME if git_dir is not None else None

    open_lines = open_task_lines(plan_text)
    if not open_lines or note_names_plan(root, plan_path, now):
        clear_refusals(counter)
        return None, None

    plan_label = plan_path.relative_to(root).as_posix()
    task_state = "\n".join(SINCE_RE.sub("", line).rstrip() for line in open_lines)
    digest = hashlib.sha256(task_state.encode("utf-8", errors="replace")).hexdigest()
    state = read_state(counter) if counter is not None else {}
    if not chain_continues(payload):
        state = {}
    previous = count_field(state, "refusals") if state.get("plan_sha256") == digest else 0
    chain_previous = count_field(state, "chain_refusals")
    lowest = lowest_open_tasks(state)
    if lowest is not None and len(open_lines) < lowest:
        chain_previous = 0  # fewer open tasks than ever in this chain: progress
    lowest = len(open_lines) if lowest is None else min(lowest, len(open_lines))
    refusal = previous + 1

    if refusal > MAX_CONSECUTIVE_REFUSALS or chain_previous + 1 > MAX_CHAIN_REFUSALS:
        clear_refusals(counter)
        emit(root, plan_label, "aborted",
               {"open_tasks": len(open_lines), "refusals": previous,
                "chain_refusals": chain_previous})
        return None, (f"{HOOK_NAME}: gave way after {chain_previous} refusals "
                      f"({previous} with no task progress) on {plan_label}; recorded "
                      "as a stop_guard fault")

    note = None
    new_state = {
        "plan_sha256": digest, "refusals": refusal,
        "chain_refusals": chain_previous + 1, "min_open_tasks": lowest,
    }
    if counter is None or not write_state(counter, new_state):
        # Without a kept count the refusals cannot be bounded, so fall back
        # to Codex's own flag: refuse once, never loop.
        note = (f"{HOOK_NAME}: could not keep the refusal count; falling back "
                "to a single refusal")
        if payload.get("stop_hook_active"):
            emit(root, plan_label, "aborted",
                 {"open_tasks": len(open_lines), "refusals": 1, "chain_refusals": 1})
            return None, note

    emit(root, plan_label, "blocked",
           {"open_tasks": len(open_lines), "refusals": refusal,
            "chain_refusals": chain_previous + 1})

    ids = sorted({
        match.group(1)
        for line in open_lines
        if (match := ID_CAPTURE_RE.match(line))
    })
    if not ids:
        ids_display = "no task ids recognised"
    else:
        shown = ids[:MAX_IDS_LISTED]
        remainder = len(ids) - len(shown)
        ids_display = ", ".join(shown)
        if remainder > 0:
            ids_display = f"{ids_display}, and {remainder} more"

    reason = REASON_TEMPLATE.format(
        count=len(open_lines), ids=ids_display,
        refusal=refusal, limit=MAX_CONSECUTIVE_REFUSALS,
        chain=chain_previous + 1,
        chain_limit=MAX_CHAIN_REFUSALS,
    )
    return reason, note


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        cwd = Path(payload.get("cwd") or os.getcwd())
        deferred: list = []
        reason, note = decide(payload, cwd, dt.datetime.now(dt.timezone.utc), deferred)
    except Exception as exc:  # a hook that cannot decide must never block
        print(f"{HOOK_NAME}: allowed the stop after an internal error "
              f"({type(exc).__name__})", file=sys.stderr)
        return 0
    if note:
        print(note, file=sys.stderr)
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    sys.stdout.flush()
    sys.stderr.flush()
    for row in deferred:
        record(*row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
