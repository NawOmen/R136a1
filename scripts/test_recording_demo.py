import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("recording_demo", Path(__file__).with_name("recording-demo.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RecordingSetupTest(unittest.TestCase):
    def test_secrets_are_private_and_initialization_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(module, "ENV", Path(tmp) / ".env.recording"):
            with mock.patch("builtins.print"):
                module.initialize()
            first = module.ENV.read_bytes()
            values = module.configuration()
            self.assertEqual(os.stat(module.ENV).st_mode & 0o777, 0o600)
            self.assertGreaterEqual(len(values["SEED_DEMO_PASSWORD"]), 16)
            self.assertNotEqual(values["SEED_DEMO_PASSWORD"], values["SEED_SELLER_PASSWORD"])
            with self.assertRaises(FileExistsError):
                module.initialize()
            self.assertEqual(module.ENV.read_bytes(), first)

    def test_working_database_is_rejected_before_docker_runs(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(module, "ENV", Path(tmp) / ".env.recording"):
            module.ENV.write_text("POSTGRES_DB=sborka\nENABLE_DEMO_SEED=true\n")
            with mock.patch.object(module.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    module.compose("up", "-d")
                run.assert_not_called()

    def test_compose_cannot_inherit_working_database_overrides(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(module, "ENV", Path(tmp) / ".env.recording"):
            with mock.patch("builtins.print"):
                module.initialize()
            with mock.patch.dict(os.environ, POSTGRES_DB="production", COMPOSE_FILE="other.yml"), \
                    mock.patch.object(module.subprocess, "run") as run:
                module.compose("up", "-d")
                args = run.call_args
                self.assertIn("r136-recording", args.args[0])
                self.assertNotIn("POSTGRES_DB", args.kwargs["env"])
                self.assertNotIn("COMPOSE_FILE", args.kwargs["env"])

    def test_existing_snapshot_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(module, "STATE", Path(tmp)), \
                mock.patch.object(module, "assert_owned_database"), mock.patch.object(module, "compose") as compose:
            (Path(tmp) / "baseline.dump").write_bytes(b"initial state")
            with self.assertRaises(ValueError):
                module.snapshot()
            compose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
