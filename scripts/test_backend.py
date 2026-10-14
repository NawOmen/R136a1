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
            self.assertEqual(runner.run_suite("marketplace", ["-q", "tests/test_seed_catalog.py"], "native"), 5)
            self.assertEqual(execute.call_args.kwargs["env"]["TEST_DATABASE_URL"], "isolated")


    def test_mac_native_mode_rejected_before_starting_any_service(self):
        with patch.object(runner.sys, "platform", "darwin"), \
             patch.object(runner.sys, "argv", ["test-backend.py", "--runtime", "native"]), \
             patch.object(runner, "run_suite") as suite:
            with self.assertRaises(SystemExit) as raised:
                runner.main()
            self.assertEqual(raised.exception.code, 2)
            suite.assert_not_called()

    def test_mac_defaults_to_docker_without_host_venvs(self):
        with patch.object(runner.sys, "platform", "darwin"), \
             patch.object(runner.sys, "argv", ["test-backend.py", "--service", "marketplace"]), \
             patch.object(runner.shutil, "which", return_value="docker"), \
             patch.object(runner, "run_suite", return_value=0) as suite:
            self.assertEqual(runner.main(), 0)
            suite.assert_called_once_with("marketplace", ["-q"], "docker")

    def test_container_failure_does_not_leak_credentials_and_cleans_up(self):
        with patch.dict(os.environ, {"DATABASE_URL":"private-db", "DEEPSEEK_API_KEY":"private-key", "RUN_OLLAMA_SMOKE":"1"}), \
             patch.object(runner.subprocess,"call", return_value=5) as execute, \
             patch.object(runner.subprocess,"run") as cleanup:
            status=runner.run_container("marketplace", ["-q"], "image", "isolated-network", "isolated-db")
            self.assertEqual(status,5)
            command=execute.call_args.args[0]
            keys=[command[i+1] for i,value in enumerate(command) if value=="--env"]
            self.assertNotIn("DEEPSEEK_API_KEY",keys)
            self.assertNotIn("RUN_OLLAMA_SMOKE",keys)
            self.assertNotIn("private-db"," ".join(command))
            self.assertNotIn("private-key"," ".join(command))
            self.assertIn("readonly"," ".join(command))
            self.assertEqual(execute.call_args.kwargs["env"]["DATABASE_URL"],"isolated-db")
            name=command[command.index("--name")+1]
            self.assertEqual(cleanup.call_args.args[0],["docker","rm","-f",name])

    def test_private_network_postgres_has_no_host_port(self):
        with patch.object(runner.subprocess,"run", return_value=subprocess.CompletedProcess([],0)) as execute, \
             patch.object(runner.subprocess,"check_output") as port:
            with runner.temporary_postgres("private-network") as url:
                self.assertIn("@postgres:5432/porukam_test",url)
            launch=execute.call_args_list[0].args[0]
            self.assertNotIn("-p",launch)
            self.assertIn("private-network",launch)
            port.assert_not_called()

    def test_interrupted_test_container_is_removed_before_network(self):
        with patch.object(runner.subprocess,"call",side_effect=KeyboardInterrupt), \
             patch.object(runner.subprocess,"run") as cleanup:
            with self.assertRaises(KeyboardInterrupt):
                runner.run_container("marketplace",["-q"],"image","network","isolated-db")
            self.assertEqual(cleanup.call_args.args[0][:3],["docker","rm","-f"])


    def test_service_dotenv_is_masked_without_editing_source(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);service=root/"services/marketplace";service.mkdir(parents=True)
            source=service/".env";source.write_text("DEEPSEEK_API_KEY=private-key")
            def execute(command,**kwargs):
                mounts=[command[i+1] for i,value in enumerate(command) if value=="--mount"]
                shadow=next(mount for mount in mounts if "target=/repo/services/marketplace/.env," in mount)
                fields=dict(part.split("=",1) for part in shadow.split(",") if "=" in part)
                self.assertEqual(Path(fields["source"]).read_text(),"")
                self.assertLess(command.index(shadow),command.index("image"))
                return 0
            with patch.object(runner,"ROOT",root),patch.object(runner.subprocess,"call",side_effect=execute), \
                 patch.object(runner.subprocess,"run"):
                self.assertEqual(runner.run_container("marketplace",["-q"],"image","network","isolated-db"),0)
            self.assertEqual(source.read_text(),"DEEPSEEK_API_KEY=private-key")


if __name__ == "__main__":
    unittest.main()
