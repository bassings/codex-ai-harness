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
of the separation AC-SIMP-12 asks for. The marker and the note both live
at the repository ROOT, never at cwd: a Codex session's cwd is often a
subdirectory, so the root is resolved first and both paths are built
under it.

Wait format this hook understands, on an open task's own line, replacing
the line's existing "state:" segment rather than adding another one
(only the latest "(since ...)" on a line is honoured):
    - [ ] C5: ... -- state: awaiting-ci #12 (since 2026-09-19T05:10:00+00:00)
The timestamp needs an explicit UTC offset -- a trailing Z/z, "+00:00" or
the bare "+0000" form, fractional seconds allowed -- and is refused if it
carries no zone at all: with no zone there is no way to know how old it
really is. A wait is live for one hour from that timestamp.

The blocked-on-human note is ignored, the same as if it did not exist,
once it is older than NOTE_MAX_AGE: conduct-plan's own instructions are to
delete it the moment a human answers, but a note left behind by accident
must not go on parking the plan indefinitely.

Open tasks are detected loosely (-, *, + or a numbered bullet, any
indentation, including nested lines) but a task's id -- the only part of
a task line ever echoed into a message -- is captured strictly and
capped in length, per AC-SEC-12. A line inside a fenced code block never
counts, so a ```-quoted example task is not read as real work.

Fails open throughout: a symlinked or unreadable marker or note, a plan
path outside the repository root, a missing or oversized plan, a
malformed marker, or any exception all end in allow, never in a block,
per AC-SEC-12 and AC-OPS-13. The allow paths that are diagnostically
interesting write one line to stderr naming what happened -- never to
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
NOTE_MAX_AGE = dt.timedelta(hours=24)
MAX_READ_BYTES = 1024 * 1024
MAX_IDS_LISTED = 10
GIT_TIMEOUT_SECONDS = 2

# Loose detection of an open checklist line: -, * or + or "1.", any
# indentation. This decides whether the plan has open work at all.
OPEN_TASK_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\[ \]")
# Strict id capture, applied only to lines the loose check already matched.
# Bounded length (AC-SEC-12, item 8 of round 2): the rest of the line --
# description, injected text, anything -- is never captured or echoed.
ID_CAPTURE_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\[ \]\s*([A-Z]{1,8}[0-9]{1,4}):")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SINCE_RE = re.compile(r"\(since ([^)]*)\)")

REASON_TEMPLATE = (
    "Codex plan guard: {count} open task(s) ({ids}) have no recorded wait "
    "and the plan is not parked on a human decision. Record a wait by "
    'replacing the open task\'s "state:" segment with, for example, '
    '"state: awaiting-ci #1 (since 2026-09-19T05:55:00+00:00)"; write '
    '.codex/blocked-on-human as "<plan path>: <question>"; or tick the '
    "remaining tasks before stopping."
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
    stderr note (item 11 of round 2); the hook still allows either way.
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
    partially loaded into memory first (round 2, item 9).
    """
    if path.stat().st_size > limit:
        return None
    return path.read_text(encoding="utf-8")


def parse_timestamp(raw: str) -> dt.datetime | None:
    """Parse a "since" value; requires an explicit UTC offset.

    Accepts what conduct-plan writes (a trailing Z, any case) plus the
    common variants: a numeric offset with or without a colon, and
    fractional seconds. A string with no zone at all parses fine as a
    naive datetime, which is deliberately refused (round 2, item 2):
    without a zone there is no way to know how old it actually is.
    """
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    bare_offset = re.match(r"^(.*[+-]\d{2})(\d{2})$", text)
    if bare_offset:
        text = f"{bare_offset.group(1)}:{bare_offset.group(2)}"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def latest_wait(line: str) -> dt.datetime | None:
    """The most recent (since ...) timestamp on this line, or None.

    Round 2, item 3: only the latest matters, not the first one written
    (a stale marker can be left behind by hand) and not simply the last
    one positionally either, since only time order is meaningful here.
    """
    timestamps = [parse_timestamp(raw) for raw in SINCE_RE.findall(line)]
    timestamps = [t for t in timestamps if t is not None]
    return max(timestamps) if timestamps else None


def open_task_lines(plan_text: str) -> list[str]:
    """Every open-checklist line, several common styles, skipping fenced
    code blocks (a ```-fenced example task must not read as real work)."""
    lines: list[str] = []
    in_fence = False
    for line in plan_text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if OPEN_TASK_LINE_RE.match(line):
            lines.append(line)
    return lines


def has_recent_wait(open_lines: list[str], now: dt.datetime) -> bool:
    """True when some open task's own line records a wait begun within
    the last hour (AC-QA-22: 59 minutes counts, 61 minutes does not)."""
    for line in open_lines:
        since = latest_wait(line)
        if since is not None and dt.timedelta(0) <= now - since <= WAIT_WINDOW:
            return True
    return False


def note_names_plan(root: Path, plan_path: Path, now: dt.datetime) -> bool:
    """Whether .codex/blocked-on-human is live and declares this plan.

    "Live" means: not a symlink, no older than NOTE_MAX_AGE (round 2, item
    1 -- conduct-plan's own instructions are now to delete it the moment a
    human answers, but this is the second line of defence), and its
    declared path resolves to the same file as plan_path. Resolving
    rather than comparing raw strings (round 2, item 4) means ./PLAN.md,
    PLAN.md and the absolute form all match. The declared path is split
    off at the first ": " (colon-space), not the first ":", so a colon
    inside the path itself does not truncate it early.
    """
    note = root / NOTE_RELATIVE
    if note.is_symlink() or not note.is_file():
        return False
    try:
        mtime = dt.datetime.fromtimestamp(note.stat().st_mtime, tz=dt.timezone.utc)
    except OSError:
        return False
    if now - mtime > NOTE_MAX_AGE:
        return False
    text = read_capped(note)
    if text is None:
        return False
    text = text.lstrip("﻿").strip().strip("`")
    declared, sep, _question = text.partition(": ")
    if not sep:
        return False
    declared = declared.strip().strip("`")
    if not declared:
        return False
    declared_path = resolve_within_root(root, declared)
    return declared_path is not None and declared_path == plan_path


def decide(payload: dict, cwd: Path, now: dt.datetime) -> tuple[str | None, str | None]:
    """Return (block_reason, stderr_note); both None is a silent allow."""
    if payload.get("stop_hook_active"):
        # AC-C5-2: never block twice in a row.
        return None, None

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

    plan_rel = marker_text.strip()
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

    open_lines = open_task_lines(plan_text)
    if not open_lines:
        return None, None  # all tasks ticked (or none were ever open)

    if note_names_plan(root, plan_path, now):
        return None, None

    if has_recent_wait(open_lines, now):
        return None, None

    ids = sorted({
        match.group(1)
        for line in open_lines
        if (match := ID_CAPTURE_RE.match(line))
    })
    shown = ids[:MAX_IDS_LISTED]
    remainder = len(ids) - len(shown)
    ids_display = ", ".join(shown)
    if remainder > 0:
        ids_display = (f"{ids_display}, and {remainder} more" if ids_display
                        else f"{remainder} more")
    return REASON_TEMPLATE.format(count=len(open_lines), ids=ids_display), None


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
