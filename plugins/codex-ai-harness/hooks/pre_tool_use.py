#!/usr/bin/env python3
"""Codex PreToolUse hook: block destructive Git and snapshot other Bash calls."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

KEEP_PER_CHECKOUT = 20
SNAPSHOT_DEADLINE_SECONDS = 2.5
CONTROL = {"&&", "||", ";", "|", "&", "\n"}
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"exec", "time", "!", "if", "then", "elif", "else", "do", "{", "("}


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def run_git(
    args: list[str], cwd: Path, input_text: str | None = None, deadline: float | None = None,
) -> subprocess.CompletedProcess[str]:
    timeout = 0.8
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise subprocess.TimeoutExpired(args, 0)
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=", *args], cwd=cwd, env=clean_env(),
        input=input_text, text=True, capture_output=True, timeout=timeout,
    )


def segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace_split = True
    lexer.whitespace = " \t"
    result: list[list[str]] = [[]]
    for token in lexer:
        if token in CONTROL:
            result.append([])
        else:
            result[-1].append(token)
    return [item for item in result if item]


def parse_git(tokens: list[str], initial_cwd: Path) -> tuple[str, list[str], Path, bool] | None:
    """Return subcommand, args, effective cwd, and inline escape state."""
    inline_escape = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "HARNESS_ALLOW_DESTRUCTIVE_GIT=1":
            inline_escape = True
            index += 1
        elif ENV_ASSIGNMENT.match(token) or token in WRAPPERS:
            index += 1
        elif token == "command":
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
        elif token == "env":
            index += 1
            while index < len(tokens):
                if tokens[index] in {"-u", "--unset"} and index + 1 < len(tokens):
                    index += 2
                elif tokens[index].startswith("-") or ENV_ASSIGNMENT.match(tokens[index]):
                    index += 1
                else:
                    break
        else:
            break
    if index >= len(tokens) or Path(tokens[index]).name != "git":
        return None
    index += 1
    effective_cwd = initial_cwd
    while index < len(tokens):
        token = tokens[index]
        if token == "-C" and index + 1 < len(tokens):
            target = Path(tokens[index + 1])
            effective_cwd = target if target.is_absolute() else effective_cwd / target
            index += 2
        elif token in {"-c", "--git-dir", "--work-tree", "--exec-path"} and index + 1 < len(tokens):
            index += 2
        elif token.startswith(("--git-dir=", "--work-tree=", "--exec-path=")):
            index += 1
        elif token in {"--no-pager", "-p", "--paginate"}:
            index += 1
        else:
            break
    if index >= len(tokens):
        return None
    return tokens[index], tokens[index + 1 :], effective_cwd, inline_escape


def destructive(parsed: tuple[str, list[str], Path, bool]) -> tuple[bool, bool]:
    """Return (is destructive, include untracked files in the dirt check)."""
    subcommand, args, _cwd, _escape = parsed
    if subcommand == "reset" and "--hard" in args:
        return True, False
    has_short_force = any(re.fullmatch(r"-[A-Za-z]+", arg) and "f" in arg[1:] for arg in args)
    if subcommand == "clean" and ("--force" in args or has_short_force):
        return True, True
    if subcommand == "restore":
        staged_only = ("--staged" in args or "-S" in args) and not ("--worktree" in args or "-W" in args)
        return not staged_only, False
    if subcommand == "switch":
        forced = any(arg in {"--force", "--discard-changes"} for arg in args) or has_short_force
        return forced, False
    if subcommand == "checkout":
        forced = "--force" in args or has_short_force
        return forced or "--" in args or any(arg in {".", "HEAD"} for arg in args), False
    return False, False


def dirty(cwd: Path, include_untracked: bool) -> bool:
    args = ["status", "--porcelain"]
    if not include_untracked:
        args.append("--untracked-files=no")
    result = run_git(args, cwd)
    if result.returncode != 0:
        raise RuntimeError("could not measure Git working-tree state")
    return bool(result.stdout.strip())


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def snapshot(cwd: Path) -> None:
    if os.environ.get("HARNESS_DISABLE_SNAPSHOT") == "1":
        return
    deadline = time.monotonic() + SNAPSHOT_DEADLINE_SECONDS
    git_dir_result = run_git(["rev-parse", "--absolute-git-dir"], cwd, deadline=deadline)
    if git_dir_result.returncode != 0:
        return
    made = run_git(["stash", "create", "codex-harness pre-tool snapshot"], cwd, deadline=deadline)
    sha = made.stdout.strip()
    if made.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        return
    key = hashlib.sha1(git_dir_result.stdout.strip().encode()).hexdigest()[:12]
    prefix = f"refs/harness-snapshots/{key}/"
    anchored = run_git(["update-ref", f"{prefix}{time.time_ns()}-{os.getpid()}", sha, ""], cwd, deadline=deadline)
    if anchored.returncode != 0:
        return
    listed = run_git(["for-each-ref", "--sort=creatordate", "--format=%(refname)", prefix], cwd, deadline=deadline)
    refs = listed.stdout.splitlines() if listed.returncode == 0 else []
    expired = refs[:-KEEP_PER_CHECKOUT]
    if expired:
        run_git(["update-ref", "--stdin"], cwd, "".join(f"delete {item}\n" for item in expired), deadline)


def cd_target(tokens: list[str], current_cwd: Path) -> tuple[bool, Path | None]:
    """Return whether this is cd, and its statically resolvable target."""
    index = 0
    while index < len(tokens) and (tokens[index] in WRAPPERS or ENV_ASSIGNMENT.match(tokens[index])):
        index += 1
    if index >= len(tokens) or tokens[index] != "cd":
        return False, current_cwd
    args = tokens[index + 1 :]
    if len(args) != 1 or args[0] == "-" or any(char in args[0] for char in "$`*?"):
        return True, None
    target = Path(args[0])
    return True, target if target.is_absolute() else current_cwd / target


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return 0
        command = (payload.get("tool_input") or {}).get("command", "")
        cwd = Path(payload.get("cwd") or os.getcwd())
        parsed_commands: list[tuple[tuple[str, list[str], Path, bool], bool]] = []
        effective_cwd: Path | None = cwd
        for part in segments(command):
            is_cd, target = cd_target(part, effective_cwd or cwd)
            if is_cd:
                effective_cwd = target
                continue
            parsed = parse_git(part, effective_cwd or cwd)
            if parsed:
                parsed_commands.append((parsed, effective_cwd is not None))
    except Exception:
        return 0

    for parsed, cwd_known in parsed_commands:
        is_destructive, include_untracked = destructive(parsed)
        if not is_destructive or parsed[3] or os.environ.get("HARNESS_ALLOW_DESTRUCTIVE_GIT") == "1":
            continue
        if not cwd_known:
            deny("Codex AI Harness could not resolve the directory targeted by this destructive Git command; it was blocked.")
            return 0
        try:
            has_changes = dirty(parsed[2], include_untracked)
        except Exception:
            deny("Codex AI Harness could not verify that this destructive Git command is safe; it was blocked.")
            return 0
        if has_changes:
            deny(
                "Codex AI Harness blocked a destructive Git command while changes are present. "
                "Preserve or stash the work first. To opt in deliberately, set "
                "HARNESS_ALLOW_DESTRUCTIVE_GIT=1 on this command."
            )
            return 0

    try:
        snapshot(cwd)
    except Exception:
        pass  # recovery is best-effort for non-destructive commands
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
