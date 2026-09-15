"""A credential must never be attached unless it was asked for by name.

Auto-picking `registries[0]` made the run depend on whatever the RunPod
account happened to list first. After an account switch that entry held a
stale Docker Hub login, and every pod died in ~12s with `unauthorized:
incorrect username or password` — on a public image that needs no login
at all, because Docker Hub rejects bad credentials instead of falling
back to an anonymous pull.
"""

import unittest
from unittest import mock

import test_images as T
from runpod_smoke import config


REGISTRIES = [
    {"id": "clstale0000", "name": "dockerhub-old"},
    {"id": "clgood11111", "name": "dockerhub-ci"},
]


class RegistryAuthResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(
            setattr, config, "REGISTRY_AUTH_ID", config.REGISTRY_AUTH_ID
        )
        self.addCleanup(
            setattr, config, "REGISTRY_AUTH_NAME", config.REGISTRY_AUTH_NAME
        )
        config.REGISTRY_AUTH_ID = ""
        config.REGISTRY_AUTH_NAME = ""

    def test_no_name_pulls_anonymously_without_listing(self):
        with mock.patch.object(T, "list_registries") as listed:
            self.assertIsNone(T._init_registry_auth())
        self.assertEqual(config.REGISTRY_AUTH_ID, "")
        listed.assert_not_called()

    def test_name_resolves_to_its_own_id(self):
        config.REGISTRY_AUTH_NAME = "dockerhub-ci"
        with mock.patch.object(T, "list_registries", return_value=REGISTRIES):
            self.assertIsNone(T._init_registry_auth())
        self.assertEqual(config.REGISTRY_AUTH_ID, "clgood11111")

    def test_name_match_ignores_case(self):
        config.REGISTRY_AUTH_NAME = "DockerHub-CI"
        with mock.patch.object(T, "list_registries", return_value=REGISTRIES):
            T._init_registry_auth()
        self.assertEqual(config.REGISTRY_AUTH_ID, "clgood11111")

    def test_unknown_name_is_fatal_and_attaches_nothing(self):
        config.REGISTRY_AUTH_NAME = "dockerhub-typo"
        with mock.patch.object(T, "list_registries", return_value=REGISTRIES):
            self.assertEqual(T._init_registry_auth(), 1)
        self.assertEqual(config.REGISTRY_AUTH_ID, "")

    def test_empty_account_is_fatal_when_a_name_was_asked_for(self):
        config.REGISTRY_AUTH_NAME = "dockerhub-ci"
        with mock.patch.object(T, "list_registries", return_value=[]):
            self.assertEqual(T._init_registry_auth(), 1)

    def test_failed_listing_is_fatal(self):
        config.REGISTRY_AUTH_NAME = "dockerhub-ci"
        with mock.patch.object(T, "list_registries", return_value=None):
            self.assertEqual(T._init_registry_auth(), 1)

    def test_explicit_id_skips_the_lookup(self):
        config.REGISTRY_AUTH_ID = "clpinned0000"
        with mock.patch.object(T, "list_registries") as listed:
            self.assertIsNone(T._init_registry_auth())
        self.assertEqual(config.REGISTRY_AUTH_ID, "clpinned0000")
        listed.assert_not_called()


class MainStopsBeforeSpendingMoney(unittest.TestCase):
    def test_unresolved_name_returns_before_any_pod_is_planned(self):
        with mock.patch.object(T, "_parse_args", return_value=("images", None)), \
             mock.patch.object(T, "_check_prereqs", return_value=None), \
             mock.patch.object(T, "_init_registry_auth", return_value=1), \
             mock.patch.object(T, "parse_manifest") as parsed, \
             mock.patch.object(T, "_run_jobs") as ran:
            self.assertEqual(T.main(), 1)
        parsed.assert_not_called()
        ran.assert_not_called()


if __name__ == "__main__":
    unittest.main()
