#!/usr/bin/env python3
"""Unit tests for release_notes.py:

    python3 .github/scripts/test_release_notes.py

Builds throwaway git repos in $TMPDIR — never touches the checkout.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_notes as R  # noqa: E402


COMFYUI = ["official-templates/comfyui/"]


def git(*args: str) -> None:
    subprocess.run(("git",) + args, check=True, capture_output=True, text=True)


def commit(message: str, path: str = "official-templates/comfyui/Dockerfile") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(message)
    git("add", "-A")
    subprocess.run(
        ("git", "commit", "-q", "-F", "-"),
        input=message, text=True, check=True, capture_output=True,
    )


class ReleaseNotes(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tempfile.mkdtemp())
        git("init", "-q", ".")
        git("config", "user.email", "ci@test")
        git("config", "user.name", "ci")
        commit("chore: seed")

    def test_one_commit_keeps_its_description(self):
        git("tag", "comfyui-v1.3.2")
        commit("fix: something about comfy (#103)\n\nsomething changed in comfyui\n")
        body = R.notes("comfyui", "1.3.2", "comfyui-v1.3.3", COMFYUI)
        self.assertIn("### fix: something about comfy (#103)", body)
        self.assertIn("something changed in comfyui", body)
        self.assertIn("compare/comfyui-v1.3.2...comfyui-v1.3.3", body)

    def test_several_commits_each_keep_theirs(self):
        git("tag", "comfyui-v1.3.2")
        commit("feat: new feature for Comfy (#101)\n\ndelivered a feature\n")
        commit("doc: readme (#102)\n\nchanges release doc\n", path="README.md")
        commit("fix: something about comfy (#103)\n\nsomething changed in comfyui\n")
        body = R.notes("comfyui", "1.3.2", "comfyui-v1.4.0", COMFYUI)
        self.assertIn("feat: new feature for Comfy (#101)", body)
        self.assertIn("delivered a feature", body)
        self.assertIn("fix: something about comfy (#103)", body)
        # A commit outside the family's paths is somebody else's story.
        self.assertNotIn("doc: readme", body)
        self.assertNotIn("changes release doc", body)

    def test_the_newest_change_comes_first(self):
        git("tag", "comfyui-v1.3.2")
        commit("feat: older (#101)\n")
        commit("fix: newer (#103)\n")
        body = R.notes("comfyui", "1.3.2", "comfyui-v1.4.0", COMFYUI)
        self.assertLess(body.index("fix: newer"), body.index("feat: older"))

    def test_trailers_are_dropped(self):
        git("tag", "comfyui-v1.3.2")
        commit("fix: terse (#104)\n\nCo-authored-by: bot <b@example.com>\n")
        body = R.notes("comfyui", "1.3.2", "comfyui-v1.3.3", COMFYUI)
        self.assertIn("### fix: terse (#104)", body)
        self.assertNotIn("Co-authored-by", body)

    def test_a_first_release_has_no_changelog_link(self):
        commit("feat: brand new family (#105)\n\nfirst cut\n")
        body = R.notes("comfyui", "", "comfyui-v1.0.0", COMFYUI)
        self.assertIn("### feat: brand new family (#105)", body)
        self.assertIn("first cut", body)
        self.assertNotIn("Full Changelog", body)

    def test_nothing_to_say_is_empty(self):
        git("tag", "comfyui-v1.3.2")
        commit("doc: readme (#102)\n", path="README.md")
        self.assertEqual(R.notes("comfyui", "", "comfyui-v1.3.3", COMFYUI), "")


if __name__ == "__main__":
    unittest.main()
