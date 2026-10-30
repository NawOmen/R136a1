import contextlib
import importlib.util
import json
import plistlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("local_model", Path(__file__).with_name("local_model.py"))
module = importlib.util.module_from_spec(spec)
sys.modules["local_model"] = module  # dataclass ищет модуль в sys.modules
spec.loader.exec_module(module)


def settings_for(root: Path, **overrides):
    fields = dict(
        repo=root / "repo",
        python=root / "python",
        model_dir=root / "model",
        adapter_dir=root / "adapter",
        host="127.0.0.1",
        port=18080,
    )
    fields.update(overrides)
    return module.Settings(**fields)


def ready_project(root: Path):
    """Каталоги и файлы, которые проверяет запуск; весов и MLX здесь нет."""
    (root / "repo" / "infra").mkdir(parents=True, exist_ok=True)
    (root / "repo" / "infra" / "build_local_model.py").write_text("# проверка\n", encoding="utf-8")
    (root / "model").mkdir()
    (root / "adapter").mkdir()
    python = root / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    return settings_for(root, port=1)


@contextlib.contextmanager
def isolated(root: Path, agent_loaded=False):
    """Тесты не трогают настоящий launchd, домашние каталоги и порт 8080."""
    (root / "agents").mkdir(parents=True, exist_ok=True)
    with mock.patch.object(module, "AGENTS_DIR", root / "agents"), \
         mock.patch.object(module, "SUPPORT_DIR", root / "support"), \
         mock.patch.object(module, "LOG_DIR", root / "logs"), \
         mock.patch.object(module, "agent_loaded", return_value=agent_loaded), \
         mock.patch.object(module, "agent_pid", return_value=None):
        yield


class ModelServer:
    """Минимальный двойник MLX-сервера: только /v1/models."""

    def __init__(self, ids=("default_model",)):
        payload = json.dumps({"object": "list", "data": [{"id": name} for name in ids]}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/v1/models":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_error(404)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class SettingsTest(unittest.TestCase):
    def test_dotenv_reads_values_without_running_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# комментарий\n"
                "MLX_MODEL_DIR=\"/weights/base\"\n"
                "export MLX_ADAPTER_DIR='/weights/adapter'\n"
                "MLX_PORT=9090\n"
                "$(touch /tmp/porukam-should-not-exist)\n",
                encoding="utf-8",
            )
            self.assertEqual(module.read_dotenv(path), {
                "MLX_MODEL_DIR": "/weights/base",
                "MLX_ADAPTER_DIR": "/weights/adapter",
                "MLX_PORT": "9090",
            })
            self.assertFalse(Path("/tmp/porukam-should-not-exist").exists())

    def test_environment_wins_over_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".env").write_text("MLX_MODEL_DIR=/from/file\nMLX_ADAPTER_DIR=/adapter\n", encoding="utf-8")
            loaded = module.settings_from(
                {"MLX_MODEL_DIR": "/from/env", "MLX_ADAPTER_DIR": "/adapter"}, repo)
            self.assertEqual(loaded.model_dir, Path("/from/env"))

    def test_settings_require_paths_and_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(module.ConfigError):
                module.settings_from({"MLX_ADAPTER_DIR": "/adapter"}, root)
            with self.assertRaises(module.ConfigError):
                module.settings_from(
                    {"MLX_MODEL_DIR": "/m", "MLX_ADAPTER_DIR": "/a", "MLX_HOST": "0.0.0.0"}, root)
            with self.assertRaises(module.ConfigError):
                module.settings_from(
                    {"MLX_MODEL_DIR": "/m", "MLX_ADAPTER_DIR": "/a", "MLX_PORT": "port"}, root)

    def test_run_reports_configuration_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            messages = []
            code = module.run(["--repo", tmp, "status"], env={}, out=messages.append)
            self.assertEqual(code, module.EX_CONFIG)
            self.assertIn("MLX_MODEL_DIR", messages[-1])


class PlistTest(unittest.TestCase):
    def test_agent_starts_script_on_host_and_restarts_only_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(Path(tmp))
            agent = plistlib.loads(module.render_plist(settings))
            self.assertEqual(agent["Label"], "ru.porukam.mlx-server")
            self.assertEqual(agent["ProgramArguments"][0], str(settings.python))
            self.assertEqual(agent["ProgramArguments"][1:],
                             [str(settings.repo / "scripts" / "local_model.py"), "serve"])
            self.assertTrue(agent["RunAtLoad"])
            self.assertEqual(agent["KeepAlive"], {"SuccessfulExit": False})
            self.assertEqual(agent["EnvironmentVariables"]["MLX_MODEL_DIR"], str(settings.model_dir))
            self.assertEqual(agent["EnvironmentVariables"]["MLX_ADAPTER_DIR"], str(settings.adapter_dir))
            self.assertEqual(agent["EnvironmentVariables"]["MLX_PORT"], "18080")
            self.assertNotIn("SECRET", json.dumps(agent["EnvironmentVariables"]).upper())

    def test_agent_keeps_normal_priority_for_gpu_work(self):
        # ProcessType=Background снижает приоритет и режет MLX до 7–8 токенов/с.
        with tempfile.TemporaryDirectory() as tmp:
            agent = plistlib.loads(module.render_plist(settings_for(Path(tmp))))
            self.assertNotEqual(agent.get("ProcessType"), "Background")


class LaunchdTest(unittest.TestCase):
    def test_linux_never_invokes_launchctl(self):
        with mock.patch.object(module.sys, "platform", "linux"), mock.patch.object(module.subprocess, "run") as run:
            self.assertIsNone(module.agent_pid())
            self.assertFalse(module.agent_loaded())
            run.assert_not_called()

    def test_agent_pid_is_read_from_launchctl(self):
        output = "gui/501/ru.porukam.mlx-server = {\n\tactive count = 1\n\tpid = 4242\n}\n"
        finished = subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr="")
        with mock.patch.object(module.sys, "platform", "darwin"), mock.patch.object(module.subprocess, "run", return_value=finished):
            self.assertEqual(module.agent_pid(), 4242)

    def test_unloaded_agent_has_no_pid(self):
        missing = subprocess.CompletedProcess(args=[], returncode=113, stdout="", stderr="Could not find service")
        with mock.patch.object(module.subprocess, "run", return_value=missing):
            self.assertIsNone(module.agent_pid())
            self.assertFalse(module.agent_loaded())


class ProbeAndRunTest(unittest.TestCase):
    def test_probe_reads_models_and_reports_silence(self):
        with tempfile.TemporaryDirectory() as tmp, ModelServer(("default_model",)) as server:
            settings = settings_for(Path(tmp), port=server.port)
            self.assertEqual(module.probe(settings), ["default_model"])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(module.probe(settings_for(Path(tmp), port=1), timeout=1.0))

    def test_status_fails_when_model_is_not_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(Path(tmp), port=1)
            messages = []
            with isolated(Path(tmp)):
                self.assertEqual(module.report_status(settings, messages.append), 1)
            self.assertIn("не отвечает", "\n".join(messages))

    def test_status_fails_when_models_endpoint_works_but_generation_is_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with isolated(root), mock.patch.object(module, "probe", return_value=["default_model"]), \
                    mock.patch.object(module, "probe_generation", return_value="generation thread died"):
                messages = []
                self.assertEqual(module.report_status(settings_for(root), messages.append), 1)
                self.assertIn("сбой", "\n".join(messages))

    def test_generation_probe_requires_an_actual_text_answer(self):
        import io
        with tempfile.TemporaryDirectory() as tmp:
            for choice in [{},False,{"message":{}},{"message":{"content":""}},{"message":{"content":"  "}},{"message":{"content":17}}]:
                with self.subTest(choice=choice):
                    opener=mock.Mock()
                    opener.open.return_value=io.BytesIO(json.dumps({"choices":[choice]}).encode())
                    with mock.patch.object(module.urllib.request,"build_opener",return_value=opener):
                        self.assertIsNotNone(module.probe_generation(settings_for(Path(tmp)),timeout=1))
            opener=mock.Mock()
            opener.open.return_value=io.BytesIO(json.dumps({"choices":[{"message":{"content":"ок"}}]}).encode())
            with mock.patch.object(module.urllib.request,"build_opener",return_value=opener):
                self.assertIsNone(module.probe_generation(settings_for(Path(tmp)),timeout=1))

    def test_start_refuses_broken_checksums_and_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = ready_project(root)
            spawn = mock.Mock()
            failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="SHA256 не совпадает")
            messages = []
            with isolated(root), mock.patch.object(module, "agent_bootstrapped", return_value=False):
                code = module.start(settings, messages.append, wait=1,
                                    runner=mock.Mock(return_value=failed), spawn=spawn)
            self.assertEqual(code, 1)
            self.assertIn("SHA256 не совпадает", "\n".join(messages))
            spawn.assert_not_called()

    def test_start_waits_for_model_and_stores_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = ready_project(root)
            spawn = mock.Mock(return_value=type("P", (), {"pid": 4242})())
            passed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            messages = []
            with isolated(root), \
                 mock.patch.object(module, "agent_bootstrapped", return_value=False), \
                 mock.patch.object(module, "probe", side_effect=[None, None, ["default_model"]]), \
                 mock.patch.object(module, "time") as clock:
                clock.monotonic.side_effect = [0.0, 1.0, 2.0, 3.0]
                clock.sleep = lambda _: None
                clock.strftime.return_value = "now"
                code = module.start(settings, messages.append, wait=60,
                                    runner=mock.Mock(return_value=passed), spawn=spawn)
            self.assertEqual(code, 0)
            self.assertEqual((root / "support" / "mlx-server.pid").read_text(), "4242")
            command = spawn.call_args.args[0]
            self.assertIn("--serve", command)
            self.assertIn(str(settings.model_dir), command)
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            self.assertIn("default_model", "\n".join(messages))

    def test_start_reuses_installed_agent_instead_of_spawning_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = ready_project(root)
            spawn = mock.Mock()
            passed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            messages = []
            with isolated(root), \
                 mock.patch.object(module, "agent_bootstrapped", return_value=True), \
                 mock.patch.object(module, "bootstrap_agent", return_value=True) as bootstrap, \
                 mock.patch.object(module, "probe", side_effect=[None, ["default_model"]]), \
                 mock.patch.object(module, "time") as clock:
                clock.monotonic.side_effect = [0.0, 1.0, 2.0, 3.0]
                clock.sleep = lambda _: None
                code = module.start(settings, messages.append, wait=60,
                                    runner=mock.Mock(return_value=passed), spawn=spawn)
            self.assertEqual(code, 0)
            bootstrap.assert_called_once()
            spawn.assert_not_called()

    def test_stop_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(Path(tmp), port=1)
            messages = []
            with isolated(Path(tmp)):
                self.assertEqual(module.stop(settings, messages.append), 0)
            self.assertIn("уже остановлен", messages[-1])

    def test_stop_unloads_agent_but_keeps_autostart_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root, port=1)
            messages = []
            with isolated(root, agent_loaded=True), \
                 mock.patch.object(module.subprocess, "run") as launchctl, \
                 mock.patch.object(module, "probe", return_value=None):
                self.assertEqual(module.stop(settings, messages.append), 0)
            self.assertEqual(launchctl.call_args.args[0][:2], ["launchctl", "bootout"])
            self.assertIn("автозапуск", messages[-1].lower())

    def test_serve_does_not_exec_broken_model(self):
        # Код 0 при ошибке настройки: launchd не должен перезапускать нерабочий запуск.
        with tempfile.TemporaryDirectory() as tmp:
            settings = ready_project(Path(tmp))
            with mock.patch.object(module, "verify", return_value=(False, "Ревизия не совпала")), \
                 mock.patch.object(module.os, "execv") as execv:
                self.assertEqual(module.serve(settings), 0)
                execv.assert_not_called()

    def test_cache_directory_is_created_for_model_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            messages = []
            with mock.patch.object(module.Path, "home", return_value=Path(tmp)):
                module.ensure_cache_dir(messages.append)
            self.assertTrue((Path(tmp) / ".cache" / "huggingface" / "hub").is_dir())


if __name__ == "__main__":
    unittest.main()
