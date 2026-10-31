"""Выбор нативного вычислителя без требования MLX на машине CI."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "build_local_model_tested", Path(__file__).resolve().parents[1] / "infra/build_local_model.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeRuntimeTests(unittest.TestCase):
    def test_linux_cpu_avoids_gpu_memory_and_device_info(self):
        mx = mock.Mock(cpu="cpu", gpu="gpu", __version__="0.32.3")
        mx.metal.is_available.return_value = False
        mx.is_available.return_value = False
        mx.default_device.return_value = mx.cpu
        server = mock.Mock()
        model, tokenizer = mock.Mock(), mock.Mock()
        server.load.return_value = model, tokenizer
        module.configure_runtime(mx, server)
        mx.set_default_device.assert_called_once_with(mx.cpu)
        mx.set_memory_limit.assert_not_called()
        self.assertEqual(server.get_system_fingerprint(), "mlx-0.32.3-cpu")
        mx.device_info.assert_not_called()
        self.assertEqual(server.load("base", adapter_path="adapter"), (model, tokenizer))
        model.set_dtype.assert_called_once_with(mx.float32)

    def test_apple_metal_keeps_existing_gpu_configuration(self):
        mx = mock.Mock(cpu="cpu", gpu="gpu")
        mx.metal.is_available.return_value = True
        mx.default_device.return_value = mx.gpu
        server = mock.Mock()
        original = server.get_system_fingerprint
        module.configure_runtime(mx, server)
        mx.set_memory_limit.assert_called_once_with(9 * 1024**3)
        mx.set_default_device.assert_not_called()
        self.assertIs(server.get_system_fingerprint, original)


if __name__ == "__main__":
    unittest.main()
