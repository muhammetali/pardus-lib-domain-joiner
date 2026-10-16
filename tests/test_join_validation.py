"""Regression tests for validation before domain join side effects.

Run with: python3 -m unittest discover -s tests -v
Only logging and the privileged/network boundaries are substituted.
"""
import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


# Load the source package without installing it or opening a user log file.
source = Path(os.environ.get(
    "PARDUS_DOMAIN_JOINER_SOURCE", Path(__file__).resolve().parents[1] / "src"
))
spec = importlib.util.spec_from_file_location(
    "pardus_domain_joiner", source / "__init__.py",
    submodule_search_locations=[str(source)],
)
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
log_module = ModuleType("pardus_domain_joiner.logger")
test_logger = logging.getLogger("join-validation-tests")
test_logger.addHandler(logging.NullHandler())
test_logger.propagate = False
log_module.get_logger = lambda name: test_logger
sys.modules[log_module.__name__] = log_module

from pardus_domain_joiner import domain_operations as operations


class JoinValidationTests(unittest.TestCase):
    def setUp(self):
        self.realmd_handler = operations.handle_realmd_join
        self.winbind_handler = operations.handle_winbind_join
        self.start_sssd = self.patch(operations.config_manager, "start_sssd_service")
        self.start_winbind = self.patch(operations.config_manager, "start_winbind_service")
        self.restore_hostname = self.patch(operations.config_manager, "restore_hostname")
        self.run = self.patch(operations.subprocess, "run")
        self.realmd = self.patch(operations, "handle_realmd_join")
        self.winbind = self.patch(operations, "handle_winbind_join")
        self.realmd.return_value = "realmd result"
        self.winbind.return_value = "winbind result"

    def patch(self, target, name):
        patcher = patch.object(target, name)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def call_join(self, ouaddress, **method):
        return operations.join(
            "client", "example.test", "administrator", "test-password",
            ouaddress=ouaddress, workgroup="EXAMPLE", **method
        )

    def assert_no_side_effects(self):
        for mock in (self.start_sssd, self.start_winbind, self.run,
                     self.realmd, self.winbind, self.restore_hostname):
            mock.assert_not_called()

    def test_invalid_ou_is_rejected_before_services_pam_or_backend(self):
        for method in ("realmd", "winbind"):
            for ou in ("computers", "OU=Workstations", "OU=,DC=example,DC=test"):
                with self.subTest(method=method, ou=ou):
                    result = self.call_join(ou, **{method: True})
                    self.assertEqual(
                        result, operations._("Organizational Unit format is not correct.")
                    )
                    self.assert_no_side_effects()

    def test_valid_and_default_ou_keep_backend_arguments_and_result(self):
        for method in ("realmd", "winbind"):
            for ou in (None, "", "CN=Computers,DC=example,DC=test",
                       "OU=Clients,OU=Office,DC=example,DC=test"):
                with self.subTest(method=method, ou=ou):
                    for mock in (self.start_sssd, self.start_winbind, self.run,
                                 self.realmd, self.winbind, self.restore_hostname):
                        mock.reset_mock()
                    result = self.call_join(ou, **{method: True})
                    expected = self.realmd if method == "realmd" else self.winbind
                    other = self.winbind if method == "realmd" else self.realmd
                    arguments = ("client", "example.test", "administrator",
                                 "test-password", ou)
                    if method == "winbind":
                        arguments += ("EXAMPLE",)
                    expected.assert_called_once_with(*arguments)
                    other.assert_not_called()
                    self.assertEqual(result, expected.return_value)
                    selected = self.start_sssd if method == "realmd" else self.start_winbind
                    unselected = self.start_winbind if method == "realmd" else self.start_sssd
                    selected.assert_called_once_with()
                    unselected.assert_not_called()
                    self.run.assert_called_once_with(
                        ["pam-auth-update", "--enable" if method == "realmd" else "--disable", "sss"],
                        capture_output=True,
                    )
                    self.restore_hostname.assert_not_called()

    def test_missing_method_keeps_existing_error_without_side_effects(self):
        for ou in (None, "computers"):
            with self.subTest(ou=ou):
                result = self.call_join(ou)
                self.assertEqual(result, operations._(
                    "No domain join method selected. Please specify either realmd or winbind."
                ))
                self.assert_no_side_effects()

    def test_direct_handlers_reject_invalid_ou_before_discovery(self):
        # Direct callers need the same validation before any configuration access.
        with patch.object(operations.os.path, "isfile", return_value=False) as isfile, \
                patch.object(operations, "discover_domain", return_value="") as discover:
            for method, handler in (("realmd", self.realmd_handler),
                                    ("winbind", self.winbind_handler)):
                with self.subTest(method=method):
                    arguments = ("client", "example.test", "administrator",
                                 "test-password", "computers")
                    if method == "winbind":
                        arguments += ("EXAMPLE",)
                    result = handler(*arguments)
                    self.assertEqual(result, operations._(
                        "Organizational Unit format is not correct."
                    ))
                    isfile.assert_not_called()
                    discover.assert_not_called()
                    self.assert_no_side_effects()

    def test_backend_process_failure_keeps_existing_error(self):
        for method, backend in (("realmd", self.realmd), ("winbind", self.winbind)):
            with self.subTest(method=method):
                backend.side_effect = subprocess.CalledProcessError(
                    1, "join", stderr="controlled failure"
                )
                result = self.call_join(None, **{method: True})
                self.assertEqual(result, operations._(
                    "An error occurred during the join process: {}"
                ).format("controlled failure"))


if __name__ == "__main__":
    unittest.main()
