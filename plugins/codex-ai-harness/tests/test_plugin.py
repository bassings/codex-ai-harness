#!/usr/bin/env python3

import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


ledger = load("ledger", ROOT / "scripts" / "ledger.py")
hook = load("pre_tool_use", ROOT / "hooks" / "pre_tool_use.py")


class PluginTests(unittest.TestCase):
    def test_manifest_and_every_skill_are_complete(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "codex-ai-harness")
        skills = list((ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skills), 5)
        for path in skills:
            text = path.read_text()
            self.assertTrue(text.startswith("---\nname:"), path)
            self.assertNotIn("[TODO:", text)

        marketplace = json.loads((ROOT.parents[1] / ".agents" / "plugins" / "marketplace.json").read_text())
        entry = marketplace["plugins"][0]
        self.assertEqual(marketplace["name"], "ai-harness-local")
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual((ROOT.parents[1] / entry["source"]["path"]).resolve(), ROOT)
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")

    def test_ledger_sanitizes_free_text_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            item = ledger.sanitize({
                "kind": "review_cycle", "outcome": "done",
                "spec": "../../secret", "lenses": ["qa", "evil prompt"],
                "counts": {"findings": 2, "quote": "source text"},
                "free_text": "must not survive",
                "run_id": "quoted source or secret",
            }, root)
            self.assertIsNone(item["spec"])
            self.assertEqual(item["lenses"], ["qa"])
            self.assertEqual(item["counts"], {"findings": 2})
            self.assertEqual(item["verdicts"], {})
            self.assertEqual(item["spec_gaps"], {})
            self.assertNotIn("free_text", item)
            self.assertNotEqual(item["run_id"], "quoted source or secret")

    def test_ledger_accepts_stop_guard_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            for outcome in ("blocked", "aborted"):
                item = ledger.sanitize({"kind": "stop_guard", "outcome": outcome}, root)
                self.assertEqual((item["kind"], item["outcome"]), ("stop_guard", outcome))

    def test_ledger_appends_one_ignored_json_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root, check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "README.md").write_text("fixture\n")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            ledger.ensure_excluded(root)
            entry = ledger.sanitize({
                "kind": "plan_cycle", "outcome": "done", "spec": "README.md",
                "lenses": ["security", "qa"], "counts": {"criteria": 4},
            }, root)
            path = ledger.append(entry, root)
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["counts"], {"criteria": 4})
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", ".codex/harness-ledger.jsonl"], cwd=root
            )
            self.assertEqual(ignored.returncode, 0)

    def test_ledger_refuses_a_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root = parent / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".codex").mkdir()
            outside = parent / "outside.jsonl"
            outside.write_text("sentinel\n")
            (root / ".codex" / "harness-ledger.jsonl").symlink_to(outside)
            entry = ledger.sanitize({"kind": "tdd_task", "outcome": "done"}, root)
            with self.assertRaises(OSError):
                ledger.append(entry, root)
            self.assertEqual(outside.read_text(), "sentinel\n")

    def test_ledger_uses_common_exclude_in_a_linked_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            main = parent / "main"
            worktree = parent / "worktree"
            main.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=main, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=main, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=main, check=True)
            (main / "README.md").write_text("fixture\n")
            subprocess.run(["git", "add", "README.md"], cwd=main, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=main, check=True)
            subprocess.run(["git", "worktree", "add", "-q", str(worktree)], cwd=main, check=True)
            ledger.ensure_excluded(worktree)
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", ".codex/harness-ledger.jsonl"], cwd=worktree
            )
            self.assertEqual(ignored.returncode, 0)

    def test_hook_patterns_cover_primary_destructive_shapes(self):
        blocked = [
            "git reset --hard",
            "git restore README.md",
            "git checkout -- README.md",
            "git checkout .",
            "git checkout HEAD -- README.md",
            "git clean -fd",
            "git switch --discard-changes feature",
            "/usr/bin/git reset --hard",
            "git -C sub reset --hard",
            "env X=1 git reset --hard",
            "env -i git reset --hard",
            "command git reset --hard",
            "(git reset --hard)",
            "if git reset --hard; then echo no; fi",
        ]
        for command in blocked:
            parsed = [item for item in (hook.parse_git(s, Path(".")) for s in hook.segments(command)) if item]
            self.assertTrue(parsed and any(hook.destructive(item)[0] for item in parsed), command)
        for command in [
            "git status", "git restore --staged README.md", "echo git reset --hard",
            "git clean -n --exclude=foo",
        ]:
            parsed = [item for item in (hook.parse_git(s, Path(".")) for s in hook.segments(command)) if item]
            self.assertFalse(any(hook.destructive(item)[0] for item in parsed), command)

    def test_hook_snapshots_and_denies_in_a_real_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("before\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            tracked.write_text("after\n")
            payload = json.dumps({
                "tool_name": "Bash", "tool_input": {"command": "git reset --hard"},
                "cwd": str(root),
            })
            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks" / "pre_tool_use.py")],
                input=payload, text=True, capture_output=True, cwd=root,
            )
            self.assertEqual(result.returncode, 0)
            decision = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            refs_before = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname)", "refs/harness-snapshots/"],
                cwd=root, text=True, capture_output=True, check=True,
            ).stdout.splitlines()
            self.assertEqual(refs_before, [])
            snapshot_payload = json.dumps({
                "tool_name": "Bash", "tool_input": {"command": "rm tracked.txt"},
                "cwd": str(root),
            })
            snapshot_result = subprocess.run(
                [sys.executable, str(ROOT / "hooks" / "pre_tool_use.py")],
                input=snapshot_payload, text=True, capture_output=True, cwd=root,
            )
            self.assertEqual(snapshot_result.returncode, 0)
            self.assertEqual(snapshot_result.stdout, "")
            refs = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname)", "refs/harness-snapshots/"],
                cwd=root, text=True, capture_output=True, check=True,
            ).stdout.splitlines()
            self.assertEqual(len(refs), 1)
            recovered = subprocess.run(
                ["git", "show", f"{refs[0]}:tracked.txt"], cwd=root,
                text=True, capture_output=True, check=True,
            ).stdout
            self.assertEqual(recovered, "after\n")

    def test_cd_then_destructive_git_is_checked_in_the_target_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            outer = Path(temp)
            nested = outer / "nested"
            nested.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=nested, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=nested, check=True)
            tracked = nested / "tracked.txt"
            tracked.write_text("before\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=nested, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=nested, check=True)
            tracked.write_text("after\n")
            payload = json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": "cd nested && git reset --hard"},
                "cwd": str(outer),
            })
            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks" / "pre_tool_use.py")],
                input=payload, text=True, capture_output=True, cwd=outer,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_snapshot_deadline_is_below_registered_hook_timeout(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        timeout = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"]
        self.assertLess(hook.SNAPSHOT_DEADLINE_SECONDS, timeout)

    def test_destructive_command_fails_closed_when_git_state_times_out(self):
        payload = json.dumps({
            "tool_name": "Bash", "tool_input": {"command": "git reset --hard"},
            "cwd": ".",
        })
        output = io.StringIO()
        timeout = subprocess.TimeoutExpired(["git", "status"], 0.8)
        with patch.object(hook, "run_git", side_effect=timeout), \
                patch.object(sys, "stdin", io.StringIO(payload)), \
                contextlib.redirect_stdout(output):
            self.assertEqual(hook.main(), 0)
        decision = json.loads(output.getvalue())["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")

    def test_git_clean_is_denied_for_untracked_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "only-untracked.txt").write_text("do not lose\n")
            payload = json.dumps({
                "tool_name": "Bash", "tool_input": {"command": "git clean -fd"},
                "cwd": str(root),
            })
            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks" / "pre_tool_use.py")],
                input=payload, text=True, capture_output=True, cwd=root,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
            )


if __name__ == "__main__":
    unittest.main()
