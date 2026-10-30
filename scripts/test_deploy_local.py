"""Проверки границ установщика: данные, локальные секреты и подлинность модели."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("deploy_local_tested", Path(__file__).with_name("deploy-local.py"))
deploy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = deploy
spec.loader.exec_module(deploy)


class DeployLocalTests(unittest.TestCase):
    def test_unsupported_host_fails_before_installation(self):
        with mock.patch.object(deploy.platform, "system", return_value="Linux"), \
                mock.patch.object(deploy, "ensure_docker") as docker:
            with self.assertRaisesRegex(deploy.DeployError, "Apple Silicon"):
                deploy.deploy()
            docker.assert_not_called()

    def test_apple_silicon_is_supported(self):
        with mock.patch.object(deploy.platform, "system", return_value="Darwin"), \
                mock.patch.object(deploy.platform, "machine", return_value="arm64"), \
                mock.patch.object(deploy.platform, "mac_ver", return_value=("15.0", (), "")):
            deploy.supported_host()

    def test_macos_intel_does_not_silently_select_base_qwen(self):
        with mock.patch.object(deploy.platform, "system", return_value="Darwin"), \
                mock.patch.object(deploy.platform, "machine", return_value="x86_64"):
            with self.assertRaises(deploy.DeployError):
                deploy.supported_host()

    def test_cli_without_daemon_or_desktop_still_installs_docker(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy, "STATE", Path(tmp)), \
                mock.patch.object(deploy.Path, "home", return_value=Path(tmp)), \
                mock.patch.object(deploy.shutil, "which", return_value="/usr/local/bin/docker"), \
                mock.patch.object(deploy, "download") as download, \
                mock.patch.object(deploy, "wait_for"), mock.patch("builtins.print"), \
                mock.patch.dict(os.environ, {}, clear=True):
            def result(args, **kwargs):
                if "info" in args:
                    return subprocess.CompletedProcess(args, 1)
                return subprocess.CompletedProcess(args, 0, stdout="unix:///local-docker.sock")
            with mock.patch.object(deploy, "run", side_effect=result):
                deploy.ensure_docker()
            self.assertEqual(download.call_args.args[0], deploy.DOCKER_DMG)

    def test_credentials_are_only_sent_to_loopback(self):
        for url in ["https://example.org", "http://evil.example", "http://localhost@evil.example", "http://user@localhost"]:
            with self.subTest(url=url), mock.patch.object(deploy.urllib.request, "build_opener") as opener:
                with self.assertRaises(deploy.DeployError):
                    deploy.local_json(url, {"password": "private"})
                opener.assert_not_called()

    def test_local_redirect_is_never_followed_with_credentials(self):
        with self.assertRaises(deploy.DeployError):
            deploy.NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://example.org")

    def test_credentials_not_printed_if_any_account_fails(self):
        values = {"SEED_DEMO_PASSWORD": "private-one", "SEED_SELLER_PASSWORD": "private-two",
                  "SEED_ADMIN_PASSWORD": "private-admin"}
        with mock.patch.object(deploy, "local_json", side_effect=[{"access_token": "ok"}, {"access_token": "ok"}, OSError("bad")]), \
                mock.patch.object(deploy.recording, "compose", return_value=subprocess.CompletedProcess([], 0, stdout="127.0.0.1:8001\n")), \
                mock.patch("builtins.print") as output:
            with self.assertRaisesRegex(deploy.DeployError, "Не подтверждён вход"):
                deploy.verify_accounts(values, show=True)
            output.assert_not_called()

    def test_four_accounts_and_legacy_second_password_are_checked(self):
        values = {"SEED_DEMO_PASSWORD": "private-one", "SEED_SELLER_PASSWORD": "private-two",
                  "SEED_ADMIN_PASSWORD": "private-admin"}
        with mock.patch.object(deploy, "local_json", return_value={"access_token": "ok"}) as request, \
                mock.patch.object(deploy.recording, "compose", return_value=subprocess.CompletedProcess([], 0, stdout="127.0.0.1:8001\n")), \
                mock.patch("builtins.print"):
            deploy.verify_accounts(values, show=True)
            self.assertEqual(request.call_count, 4)
            self.assertEqual(request.call_args_list[2].args[1], {"email": "supplier@demo.ru", "password": "private-two"})

    def test_credentials_not_sent_to_auth_of_another_project(self):
        with mock.patch.object(deploy.recording, "compose", return_value=subprocess.CompletedProcess([], 0, stdout="")), \
                mock.patch.object(deploy, "local_json") as request:
            with self.assertRaisesRegex(deploy.DeployError, "обслуживает Auth"):
                deploy.verify_accounts({})
            request.assert_not_called()

    def test_private_atomic_update_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            deploy.atomic_private(path, b"one")
            deploy.atomic_private(path, b"two")
            self.assertEqual(path.read_bytes(), b"two")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with self.assertRaises(deploy.DeployError):
                deploy.atomic_private(link, b"three")
            self.assertEqual(path.read_bytes(), b"two")

    def test_missing_env_never_rotates_passwords_of_existing_volume(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy.recording, "ENV", Path(tmp) / ".env.recording"), \
                mock.patch.object(deploy, "run", return_value=subprocess.CompletedProcess([], 0, stdout="r136-recording_postgres_data\n")), \
                mock.patch.object(deploy.recording, "initialize") as initialize:
            with self.assertRaisesRegex(deploy.DeployError, "Восстановите исходный файл"):
                deploy.configuration()
            initialize.assert_not_called()

    def test_repeat_configuration_preserves_password_and_working_env(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy.recording, "ENV", Path(tmp) / ".env.recording"):
            with mock.patch("builtins.print"):
                deploy.recording.initialize()
            before = deploy.recording.ENV.read_bytes()
            first = deploy.configuration()
            deploy.save_configuration(first)
            second = deploy.configuration()
            self.assertEqual(first["SEED_DEMO_PASSWORD"], second["SEED_DEMO_PASSWORD"])
            self.assertEqual(first["POSTGRES_PASSWORD"], second["POSTGRES_PASSWORD"])
            self.assertIn(b"SEED_SELLER2_PASSWORD=", before)
            self.assertEqual(second["DEEPSEEK_API_KEY"], "")

    def test_different_database_or_backend_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy.recording, "ENV", Path(tmp) / ".env.recording"):
            deploy.recording.ENV.write_text("POSTGRES_DB=production\nENABLE_DEMO_SEED=true\n")
            with self.assertRaises(ValueError):
                deploy.configuration()
            with mock.patch("builtins.print"):
                deploy.recording.ENV.unlink()
                deploy.recording.initialize()
            values = deploy.local_model.read_dotenv(deploy.recording.ENV)
            values["LOCAL_LLM_BACKEND"] = "ollama"
            deploy.save_configuration(values)
            with self.assertRaisesRegex(deploy.DeployError, "LOCAL_LLM_BACKEND"):
                deploy.configuration()

    def test_custom_ports_are_rejected_instead_of_checking_the_wrong_stand(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy.recording, "ENV", Path(tmp) / ".env.recording"):
            with mock.patch("builtins.print"):
                deploy.recording.initialize()
            values = deploy.local_model.read_dotenv(deploy.recording.ENV)
            values["GATEWAY_AUTH_PORT"] = "12345"
            deploy.save_configuration(values)
            with self.assertRaisesRegex(deploy.DeployError, "GATEWAY_AUTH_PORT"):
                deploy.configuration()

    def test_path_injection_and_dotenv_interpolation_rejected(self):
        for value in ["../secret", "/etc/secret", "folder/../../secret", "folder\\secret"]:
            with self.subTest(value=value), self.assertRaises(deploy.DeployError):
                deploy.safe_name(value)
        for value in ["/path/$HOME/model", "valid\nPOSTGRES_DB=other"]:
            with self.assertRaises(deploy.DeployError):
                deploy.save_configuration({"MLX_MODEL_DIR": value})

    def test_failed_download_keeps_last_verified_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights"
            path.write_bytes(b"previous")
            with mock.patch.object(deploy.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt")):
                with self.assertRaisesRegex(deploy.DeployError, "SHA256"):
                    deploy.download("https://example.org/weights", path, sha256="0" * 64)
            self.assertEqual(path.read_bytes(), b"previous")
            self.assertFalse(path.with_name("weights.part").exists())

    def test_valid_cached_weights_are_not_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights"
            path.write_bytes(b"verified")
            with mock.patch.object(deploy.urllib.request, "urlopen") as request:
                deploy.download("https://example.org/weights", path, sha256=deploy.digest(path), size=8)
                request.assert_not_called()

    def test_new_revision_refreshes_cached_base_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / "ml/training/porukam-trained-current"
            metadata.mkdir(parents=True)
            (root / "infra").mkdir()
            (root / "infra/models.lock.json").write_text(json.dumps({"local_llm": {"base_revision": "new", "base_model": "repo/model"}}))
            (metadata / "base-download-manifest.json").write_text(json.dumps({"sha": "new", "siblings": [{"rfilename": "config.json"}]}))
            base = root / "base";base.mkdir()
            (base / "config.json").write_text("old config")
            (base / "download-manifest.json").write_text(json.dumps({"sha": "old"}))
            def download(url, path, **kwargs):
                self.assertIn("/resolve/new/config.json", url)
                path.write_text("new config")
            with mock.patch.object(deploy, "ROOT", root), mock.patch.object(deploy, "download", side_effect=download) as fetch:
                deploy.install_base(base)
                deploy.install_base(base)
                self.assertEqual(fetch.call_count, 1)
            self.assertEqual((base / "config.json").read_text(), "new config")

    def test_adapter_archive_symlink_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy, "STATE", Path(tmp)), \
                mock.patch.object(deploy, "download"):
            archive = Path(tmp) / "porukam-model.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("link");info.type = tarfile.SYMTYPE;info.linkname = "/tmp/outside"
                tar.addfile(info)
            with self.assertRaisesRegex(deploy.DeployError, "ссылку"):
                deploy.install_adapter(Path(tmp) / "destination")
            self.assertFalse((Path(tmp) / "destination").exists())

    def test_prepare_never_rewrites_started_purchase(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy, "STATE", Path(tmp)), \
                mock.patch.object(deploy.recording, "assert_owned_database"), \
                mock.patch.object(deploy.recording, "compose", return_value=subprocess.CompletedProcess([], 0, stdout="2\n")) as compose, \
                mock.patch("builtins.print"):
            deploy.prepare_once()
            self.assertEqual(compose.call_count, 2)
            self.assertNotIn("prepare_recording.py", str(compose.call_args))

    def test_initial_preparation_only_once(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy, "STATE", Path(tmp)), \
                mock.patch.object(deploy.recording, "assert_owned_database"), \
                mock.patch.object(deploy.recording, "compose", return_value=subprocess.CompletedProcess([], 0, stdout="0\n")) as compose:
            deploy.prepare_once()
            self.assertIn("prepare_recording.py", str(compose.call_args_list[2]))
            deploy.prepare_once()
            self.assertEqual(compose.call_count, 4)

    def test_new_database_instance_is_prepared_despite_old_local_marker(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy, "STATE", Path(tmp)), \
                mock.patch.object(deploy.recording, "assert_owned_database"), \
                mock.patch.object(deploy.recording, "compose", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout="200\n"),
                    subprocess.CompletedProcess([], 0, stdout="0\n"),
                    subprocess.CompletedProcess([], 0, stdout="готово")]) as compose:
            (Path(tmp) / "prepared.json").write_text(json.dumps({"instance": "100"}))
            deploy.prepare_once()
            self.assertIn("prepare_recording.py", str(compose.call_args_list[2]))
            self.assertEqual(json.loads((Path(tmp) / "prepared.json").read_text())["instance"], "200")

    def test_occupied_foreign_port_never_stops_other_stack(self):
        with mock.patch.object(deploy.recording, "compose", return_value=subprocess.CompletedProcess([], 0, stdout="")) as compose, \
                mock.patch.object(deploy.socket, "socket") as socket:
            socket.return_value.__enter__.return_value.connect_ex.return_value = 0
            with self.assertRaisesRegex(deploy.DeployError, "Порт 3000"):
                deploy.check_ports()
            self.assertEqual(compose.call_count, 1)

    def test_shell_model_paths_do_not_override_recording_settings(self):
        values = {"MLX_MODEL_DIR": "/own/base", "MLX_ADAPTER_DIR": "/own/adapter", "MLX_SERVE_PYTHON": "/own/python"}
        with mock.patch.dict(os.environ, MLX_MODEL_DIR="/other", MLX_HOST="0.0.0.0", MLX_PORT="9999"):
            env = deploy.model_environment(values)
            self.assertEqual(env["MLX_MODEL_DIR"], "/own/base")
            self.assertEqual(env["MLX_HOST"], "127.0.0.1")
            self.assertEqual(env["MLX_PORT"], "8080")

    def test_cached_ollama_model_does_not_contact_registry_on_restart(self):
        tags = {"models": [{"name": deploy.MODEL}]}
        with mock.patch.object(deploy.shutil, "which", return_value="/installed/ollama"), \
                mock.patch.object(deploy, "wait_for"), mock.patch.object(deploy, "run") as run, \
                mock.patch.object(deploy, "local_json", side_effect=[tags, tags, {"message": {"content": "готово"}}]) as request:
            deploy.ensure_ollama()
            run.assert_not_called()
            self.assertEqual(request.call_args.args[1]["keep_alive"], 0)

    def test_missing_ollama_model_is_pulled_and_generation_checked(self):
        tags = {"models": [{"name": deploy.MODEL}]}
        with mock.patch.object(deploy.shutil, "which", return_value="/installed/ollama"), \
                mock.patch.object(deploy, "wait_for"), mock.patch.object(deploy, "run") as run, \
                mock.patch.object(deploy, "local_json", side_effect=[{}, {}, tags, {"message": {"content": "готово"}}]):
            deploy.ensure_ollama()
            self.assertEqual(run.call_args.args[0][1:], ["pull", deploy.MODEL])


if __name__ == "__main__":
    unittest.main()
