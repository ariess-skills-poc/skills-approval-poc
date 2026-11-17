"""Tests for validate.py and release.py. Run: python3 -m unittest discover -s .github/scripts"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATE = HERE / "validate.py"
RELEASE = HERE / "release.py"
SKILL = "data/eng/demo-skill"

GOOD = """---
name: demo-skill
description: Does a demo thing. Use when testing.
metadata:
  author: team-a
  version: {ver}
---

# Demo
"""


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class Repo:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@example.invalid")

    def git(self, *a):
        r = run(["git", *a], self.path)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def write(self, rel, text, newline="\n"):
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline=newline) as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def validate(self, base="main"):
        return run([sys.executable, str(VALIDATE), base], self.path)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.0.0"))
        self.r.write(f"{SKILL}/scripts/run.sh", "echo hi\n")
        self.r.write(".claude-plugin/marketplace.json",
                     '{"name": "t", "owner": {"name": "t"}, "plugins": [{"name": "data-eng", "source": "./data/eng"}]}')
        self.plugin("1.0.0")
        self.r.commit("base")
        self.r.git("checkout", "-qb", "pr")

    def plugin(self, ver):
        self.r.write("data/eng/.claude-plugin/plugin.json",
                     '{"name": "data-eng", "version": "%s", "skills": "./"}' % ver)

    def tearDown(self):
        self.r.tmp.cleanup()

    def test_change_without_bump_fails(self):
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.0.0") + "more\n")
        self.r.commit("edit")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("is not higher than", res.stdout)

    def test_change_with_bump_passes(self):
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.1.0") + "more\n")
        self.plugin("1.1.0")
        self.r.commit("edit")
        res = self.r.validate()
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_scripts_only_change_without_bump_fails(self):
        self.r.write(f"{SKILL}/scripts/run.sh", "echo changed\n")
        self.r.commit("script")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("not higher than", res.stdout)

    def test_quoted_version_passes(self):
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver='"1.0.1"  # bump'))
        self.plugin("1.1.0")
        self.r.commit("quoted")
        res = self.r.validate()
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_crlf_passes(self):
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.0.1"), newline="\r\n")
        self.plugin("1.1.0")
        self.r.commit("crlf")
        res = self.r.validate()
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_extra_top_level_field_fails(self):
        text = GOOD.format(ver="1.0.1").replace("name: demo-skill\n", "name: demo-skill\nowner: team-a\n")
        self.r.write(f"{SKILL}/SKILL.md", text)
        self.r.commit("extra")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("non-standard top-level fields", res.stdout)

    def test_missing_base_ref_fails(self):
        res = self.r.validate("origin/does-not-exist")
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("not found", res.stdout)

    def test_deleted_skill_passes_with_notice(self):
        self.r.git("rm", "-rq", SKILL, "data/eng/.claude-plugin")
        self.r.write(".claude-plugin/marketplace.json", '{"name": "t", "owner": {"name": "t"}, "plugins": []}')
        self.r.commit("delete")
        res = self.r.validate()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("skill deleted", res.stdout)

    def test_block_scalar_description_and_bad_lifecycle(self):
        text = GOOD.format(ver="1.0.1").replace(
            "description: Does a demo thing. Use when testing.\n",
            "description: >\n  Does a demo thing.\n  Use when testing.\n").replace(
            "  version: 1.0.1\n", "  version: 1.0.1\n  lifecycle: beta\n")
        self.r.write(f"{SKILL}/SKILL.md", text)
        self.r.commit("lifecycle")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("lifecycle", res.stdout)
        self.assertNotIn("description is required", res.stdout)

    def test_renamed_folder_must_match_name(self):
        self.r.git("mv", SKILL, "data/eng/other-name")
        self.r.commit("rename")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("must equal folder name", res.stdout)


    def test_skill_bump_without_plugin_bump_fails(self):
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.1.0"))
        self.r.commit("edit")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("bump the plugin version", res.stdout)

    def test_unlisted_skill_folder_fails(self):
        self.r.write("data/sales/new-skill/SKILL.md", GOOD.format(ver="0.1.0").replace("demo-skill", "new-skill"))
        self.r.commit("new")
        res = self.r.validate()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("not listed in .claude-plugin/marketplace.json", res.stdout)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.0.0"))
        self.r.write("data/eng/second-skill/SKILL.md",
                     GOOD.format(ver="2.0.0").replace("demo-skill", "second-skill"))
        self.first = self.r.commit("first")

    def tearDown(self):
        self.r.tmp.cleanup()

    def release(self, before, after):
        return run([sys.executable, str(RELEASE), before, after], self.r.path)

    def tags(self):
        return sorted(self.r.git("tag").split())

    def test_first_push_tags_all(self):
        res = self.release("0" * 40, self.first)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.tags(), ["demo-skill--v1.0.0", "second-skill--v2.0.0"])

    def test_only_changed_version_is_tagged_and_pr_in_message(self):
        self.release("0" * 40, self.first)
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.1.0"))
        after = self.r.commit("Merge pull request #7 from x/y")
        res = self.release(self.first, after)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("demo-skill--v1.1.0", self.tags())
        self.assertIn("(PR #7)", self.r.git("tag", "-l", "-n1", "demo-skill--v1.1.0"))
        self.assertNotIn("second-skill--v2.0.1", self.tags())

    def test_reused_version_fails(self):
        self.release("0" * 40, self.first)
        self.r.write(f"{SKILL}/SKILL.md", GOOD.format(ver="1.1.0"))
        a = self.r.commit("bump")
        self.r.git("tag", "-a", "demo-skill--v1.1.0", "-m", "x", self.first)  # tag already used elsewhere
        res = self.release(self.first, a)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("already exists on another commit", res.stdout)


if __name__ == "__main__":
    unittest.main()
