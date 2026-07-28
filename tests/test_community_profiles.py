"""Tests for community fork registry matching."""

from __future__ import annotations

import unittest

from ai.fork.community_profiles import match_community_profile


class TestCommunityProfiles(unittest.TestCase):
  def test_match_dragonpilot_remote(self):
    scan = {
      "remote_identity": {"slug": "dragonpilot/dragonpilot", "owner": "dragonpilot", "repo": "dragonpilot"},
      "distinctive_dirs": [],
      "root_files": ["d2"],
      "git_branch": "d2",
      "param_prefixes": {"dp_": 12},
      "readme_excerpt": "",
    }
    profile = match_community_profile(scan)
    self.assertIsNotNone(profile)
    assert profile is not None
    self.assertEqual(profile["id"], "dragonpilot/dragonpilot")
    self.assertGreater(profile["_match_score"], 50)

  def test_match_sunnypilot_dir(self):
    scan = {
      "remote_identity": {"slug": "sunnypilot/sunnypilot"},
      "distinctive_dirs": ["sunnypilot"],
      "root_files": [],
      "param_prefixes": {"Sp": 8},
      "readme_excerpt": "",
      "git_branch": "dev",
    }
    profile = match_community_profile(scan)
    self.assertIsNotNone(profile)
    assert profile is not None
    self.assertIn("sunnypilot", profile["id"].lower())


if __name__ == "__main__":
  unittest.main()
