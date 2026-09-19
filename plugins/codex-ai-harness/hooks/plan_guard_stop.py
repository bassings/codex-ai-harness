#!/usr/bin/env python3
"""Codex Stop hook: refuse to end a turn while a conducted plan still has
open tasks, no recorded wait and no human block.

Scope, deliberately narrow (AC-SIMP-12): the decision comes from exactly
three inputs -- the plan named by .codex/active-plan, the
.codex/blocked-on-human note, and stop_hook_active. It never reads the
harness's run-history file, so this file mentions none of that machinery;
a wait is read from the named plan's own task line, not from any recorded
history.

Root resolution below duplicates a few lines the harness's telemetry
writer already has for the same purpose (git rev-parse --show-toplevel),
rather than importing it. That import would put a word this file must
not contain into its own source, so the small duplication is the price
of the separation AC-SIMP-12 asks for.

Wait format this hook understands, on an open task's own line:
    - [ ] C5: ... -- state: awaiting-ci #12 (since 2026-09-19T05:10Z)
The timestamp is ISO-8601 UTC ("Z" suffix), seconds optional. A wait is
live for one hour from that timestamp; older than that, it no longer
exempts the plan. skills/conduct-plan/SKILL.md is the source that tells
the conductor to write this.

Fails open throughout: a symlinked or unreadable marker, a plan path
outside the repository root, a missing plan, or any exception all end in
allow, never in a block, per AC-SEC-12 and AC-OPS-13. The two allow paths
that are diagnostically interesting (a missing plan; an internal
exception) write one line to stderr naming what happened -- never to
stdout, which stays empty on every allow.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HOOK_NAME = "plan_guard_stop"
MARKER_RELATIVE = Path(".codex") / "active-plan"
NOTE_RELATIVE = Path(".codex") / "blocked-on-human"
WAIT_WINDOW = dt.timedelta(hours=1)

# Task ids in every output must match this shape (AC-SEC-12); the rest of
# an open task's line -- description, injected text, anything -- is never
# captured or repeated back.
OPEN_TASK_RE = re.compile(r"^- \[ \] ([A-Z]+[0-9]+):.*$", re.MULTILINE)
SINCE_RE = re.compile(
    r"\(since (\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?Z\)"
)

REASON_TEMPLATE = (
    "Codex plan guard: {count} open task(s) ({ids}) have no recorded wait "
    "and the plan is not parked on a human decision. Record a wait on the "
    'open task\'s own line as "state: <status> (since <UTC timestamp>)", '
    'write .codex/blocked-on-human as "<plan path>: <question>", or tick '
    "the remaining tasks before stopping."
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
            cwd=cwd, text=True, capture_output=True, timeout=5, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except (OSError, ValueError):
        return None


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


def parse_since(line: str) -> dt.datetime | None:
    match = SINCE_RE.search(line)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        return dt.datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second) if second else 0, tzinfo=dt.timezone.utc,
        )
    except ValueError:
        return None


def has_recent_wait(plan_text: str, now: dt.datetime) -> bool:
    """True when some open task's own line records a wait begun within
    the last hour (AC-QA-22: 59 minutes counts, 61 minutes does not)."""
    for line in plan_text.splitlines():
        if not OPEN_TASK_RE.match(line):
            continue
        since = parse_since(line)
        if since is not None and dt.timedelta(0) <= now - since <= WAIT_WINDOW:
            return True
    return False


def note_names_plan(root: Path, plan_rel: str) -> bool:
    """Whether .codex/blocked-on-human is live and declares this plan.

    Compared as the same repo-relative text the marker holds (AC-DATA-12
    calls this "repo-relative path prefix, then :"), not by resolving
    paths -- both the marker and a note written per conduct-plan's own
    instructions carry the same repo-relative string, so a plain string
    match is the whole rule.
    """
    note = root / NOTE_RELATIVE
    if note.is_symlink() or not note.is_file():
        return False
    text = note.read_text(encoding="utf-8")
    declared, sep, _question = text.partition(":")
    if not sep:
        return False
    return declared.strip() == plan_rel


def decide(payload: dict, cwd: Path, now: dt.datetime) -> tuple[str | None, str | None]:
    """Return (block_reason, stderr_note); both None is a silent allow."""
    if payload.get("stop_hook_active"):
        # AC-C5-2: never block twice in a row.
        return None, None

    # Round-1 review finding: the marker and the note both live at the
    # REPOSITORY root (that is what .codex/active-plan and conduct-plan's
    # own instructions assume), never at cwd. A Codex session whose cwd is
    # an ordinary subdirectory of the repo must still find them, so the
    # root is resolved before either path is built, not after.
    root = repository_root(cwd)
    if root is None:
        return None, None  # cannot place a marker against a repo; allow

    marker = root / MARKER_RELATIVE
    if marker.is_symlink() or not marker.is_file():
        # No marker at all: AC-C5-3, silent. A symlinked marker: AC-SEC-12.
        return None, None

    plan_rel = marker.read_text(encoding="utf-8").strip()
    if not plan_rel:
        return None, None  # malformed marker: nothing named, nothing to check

    plan_path = resolve_within_root(root, plan_rel)
    if plan_path is None:
        return None, None  # AC-SEC-12: plan path resolves outside the repo

    if not plan_path.is_file():
        return None, f"{HOOK_NAME}: {marker} names a plan that does not exist"

    plan_text = plan_path.read_text(encoding="utf-8")

    open_ids = OPEN_TASK_RE.findall(plan_text)
    if not open_ids:
        return None, None  # all tasks ticked

    if note_names_plan(root, plan_rel):
        return None, None

    if has_recent_wait(plan_text, now):
        return None, None

    ids = sorted(set(open_ids))
    return REASON_TEMPLATE.format(count=len(ids), ids=", ".join(ids)), None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        cwd = Path(payload.get("cwd") or os.getcwd())
        reason, note = decide(payload, cwd, dt.datetime.now(dt.timezone.utc))
    except Exception as exc:  # a hook that cannot decide must never block
        print(f"{HOOK_NAME}: allowed the stop after an internal error "
              f"({type(exc).__name__})", file=sys.stderr)
        return 0
    if note:
        print(note, file=sys.stderr)
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
