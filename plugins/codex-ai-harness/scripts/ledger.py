#!/usr/bin/env python3
"""Append bounded, low-sensitivity Codex harness telemetry as JSONL."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

LEDGER_RELATIVE = Path(".codex/harness-ledger.jsonl")
KINDS = {"plan_cycle", "review_cycle", "tdd_task", "conduct_plan_event", "stop_guard"}
OUTCOMES = {"started", "done", "blocked", "aborted", "no-op"}
LENS_RE = re.compile(r"^(?:security|qa|simplicity|product|design|accessibility|architecture|data|operability|verification)$")
MAX_LINE = 16 * 1024


def git(args: list[str], cwd: Path) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, text=True, capture_output=True,
        timeout=5, check=True,
    )
    return result.stdout.strip()


def repository_root(cwd: Path) -> Path:
    return Path(git(["rev-parse", "--show-toplevel"], cwd)).resolve()


def ensure_excluded(root: Path) -> None:
    raw_git_dir = Path(git(["rev-parse", "--git-common-dir"], root))
    git_dir = raw_git_dir if raw_git_dir.is_absolute() else (root / raw_git_dir).resolve()
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    entry = LEDGER_RELATIVE.as_posix()
    if entry not in {line.strip() for line in current.splitlines()}:
        separator = "" if not current or current.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(f"{separator}{entry}\n")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", entry], cwd=root,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        timeout=5,
    )
    if ignored.returncode != 0:
        raise RuntimeError(f"{entry} is not ignored; refusing to write telemetry")


def non_negative_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, count in value.items():
        if isinstance(key, str) and re.fullmatch(r"[a-z_]{1,32}", key) and isinstance(count, int) and count >= 0:
            result[key] = count
    return result


def per_lens_values(value: object, allowed: set[str] | None = None) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for lens, item in value.items():
        if not isinstance(lens, str) or not LENS_RE.fullmatch(lens):
            continue
        if allowed is not None and item in allowed:
            result[lens] = item
        elif allowed is None and isinstance(item, int) and item >= 0:
            result[lens] = item
    return result


def sanitize(payload: object, root: Path) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    kind = payload.get("kind")
    outcome = payload.get("outcome")
    if kind not in KINDS or outcome not in OUTCOMES:
        raise ValueError("invalid kind or outcome")
    lenses = payload.get("lenses", [])
    if not isinstance(lenses, list):
        lenses = []
    clean_lenses = sorted({x for x in lenses if isinstance(x, str) and LENS_RE.fullmatch(x)})
    spec = payload.get("spec")
    clean_spec = None
    if isinstance(spec, str) and spec and "\x00" not in spec:
        candidate = (root / spec).resolve()
        try:
            clean_spec = candidate.relative_to(root).as_posix()
        except ValueError:
            clean_spec = None
    supplied_run_id = payload.get("run_id")
    try:
        run_id = str(uuid.UUID(str(supplied_run_id))) if supplied_run_id else str(uuid.uuid4())
    except (ValueError, TypeError, AttributeError):
        run_id = str(uuid.uuid4())
    return {
        "schema_version": 1,
        "run_id": run_id,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "outcome": outcome,
        "spec": clean_spec,
        "lenses": clean_lenses,
        "counts": non_negative_counts(payload.get("counts")),
        "verdicts": per_lens_values(payload.get("verdicts"), {"CLEAN", "FINDINGS", "BLOCKED"}),
        "spec_gaps": per_lens_values(payload.get("spec_gaps")),
    }


def append(entry: dict[str, object], root: Path) -> Path:
    encoded = (json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_LINE:
        raise ValueError("ledger entry exceeds 16 KiB")
    path = root / LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(path.parent, directory_flags)
    try:
        file_flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path.name, file_flags, 0o600, dir_fd=directory_fd)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    return path


def main() -> int:
    try:
        root = repository_root(Path.cwd())
        ensure_excluded(root)
        entry = sanitize(json.load(sys.stdin), root)
        path = append(entry, root)
        print(json.dumps({"write_ok": True, "run_id": entry["run_id"], "path": str(path)}))
    except Exception as exc:  # telemetry must never fail the harness run
        print(json.dumps({"write_ok": False, "error": str(exc)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
