#!/bin/sh
# core.hooksPath is local config, so a committed hook is inert in a fresh
# clone until this runs. Relative on purpose, so linked worktrees use their
# own copy.
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
[ "$(git config --get core.hooksPath)" = ".githooks" ] || { echo "setup-hooks: hooksPath not set" >&2; exit 1; }
[ -x .githooks/pre-push ] || { echo "setup-hooks: .githooks/pre-push missing or not executable" >&2; exit 1; }
echo "setup-hooks: pre-push gate active"
