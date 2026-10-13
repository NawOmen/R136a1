import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("backend_runner", Path(__file__).with_name("test-backend.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class DisposableBackendTests(unittest.TestCase):
    def test_database_and_secrets_override_parent_without_mutating_it(self):
        original = {"DATABASE_URL": "application-database", "TEST_DATABASE_URL": "wrong-database",
                    "JWT_SECRET": "parent-key", "ENABLE_DEMO_SEED": "true", "RUN_OLLAMA_SMOKE": "1"}
        with patch.dict(os.environ, original):
            child = runner.test_environment("isolated-test-database")
            self.assertEqual(child["DATABASE_URL"], "isolated-test-database")
            self.assertEqual(child["TEST_DATABASE_URL"], "isolated-test-database")
            self.assertNotEqual(child["JWT_SECRET"], original["JWT_SECRET"])
            self.assertEqual(child["ENABLE_DEMO_SEED"], "false")
            self.assertNotIn("RUN_OLLAMA_SMOKE", child)
            self.assertEqual(os.environ["DATABASE_URL"], original["DATABASE_URL"])

    def test_exception_in_suite_removes_only_owned_container(self):
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as execute, \
             patch.object(runner.subprocess, "check_output", return_value="127.0.0.1:65432\n"):
            with self.assertRaisesRegex(RuntimeError, "suite failed"):
                with runner.temporary_postgres() as url:
                    self.assertIn("@127.0.0.1:65432/porukam_test", url)
                    raise RuntimeError("suite failed")
            launch = execute.call_args_list[0]
            arguments = launch.args[0]
            self.assertIn("127.0.0.1::5432", arguments)
            self.assertIn("--tmpfs", arguments)
            self.assertNotIn("--volume", arguments)
            self.assertNotIn("-v", arguments)
            self.assertNotIn("POSTGRES_PASSWORD=", " ".join(arguments))
            name = arguments[arguments.index("--name") + 1]
            self.assertTrue(name.startswith("porukam-tests-"))
            self.assertEqual(execute.call_args_list[-1].args[0], ["docker", "rm", "-f", name])

    def test_postgres_timeout_still_cleans_up(self):
        def execute(arguments, **kwargs):
            return subprocess.CompletedProcess(arguments, int(arguments[1] == "exec"))
        with patch.object(runner.subprocess, "run", side_effect=execute) as commands, \
             patch.object(runner.subprocess, "check_output", return_value="127.0.0.1:65432\n"), \
             patch.object(runner.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(RuntimeError, "60 секунд"):
                with runner.temporary_postgres():
                    self.fail("Must not start tests without PostgreSQL")
            self.assertEqual(commands.call_args_list[-1].args[0][:3], ["docker", "rm", "-f"])

    def test_suite_failure_exit_code_is_not_replaced_by_cleanup_success(self):
        from contextlib import nullcontext
        with patch.object(runner, "temporary_postgres", return_value=nullcontext("isolated")), \
             patch.object(runner.subprocess, "call", return_value=5) as execute:
            self.assertEqual(runner.run_suite("marketplace", ["-q", "tests/test_seed_catalog.py"]), 5)
            self.assertEqual(execute.call_args.kwargs["env"]["TEST_DATABASE_URL"], "isolated")


if __name__ == "__main__":
    unittest.main()
