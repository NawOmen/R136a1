import argparse
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("final_demo", Path(__file__).with_name("check-final-demo.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FinalDemoPreflightTest(unittest.TestCase):
    def args(self):
        return argparse.Namespace(**{f"{name}_url": f"http://localhost:{port}" for name, port in
            (("web", 3000), ("auth", 8001), ("marketplace", 8002), ("llm", 8003), ("storage", 9000),
             ("ollama", 11434), ("mlx", 8080))}, timeout=1)

    def request(self, url, timeout, **kwargs):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:9b"}]}
        if url.endswith("/v1/models"):
            return {"data": [{"id": "default_model"}]}
        if url.endswith("/api/v3/products"):
            return [{"id": "synthetic"}]
        return {"status": "ok", "local_backend": "ollama", "local_model": "qwen3.5:9b", "vision_model": "qwen3.5:9b"}

    def test_health_is_not_claimed_as_complete_core_flow(self):
        report = module.inspect(self.args(), self.request)
        self.assertTrue(report["infrastructure_passed"])
        self.assertIn("Не проверен", report["live_core_flow"])

    def test_unavailable_service_empty_catalog_or_missing_model_cannot_pass(self):
        for suffix in ("8001/health", "8002/health", "8003/health", "/login", "/minio/health/ready", "/api/tags", "/api/v3/products"):
            def broken(url, timeout, **kwargs):
                if url.endswith(suffix):
                    raise OSError("Unavailable")
                return self.request(url, timeout, **kwargs)
            self.assertFalse(module.inspect(self.args(), broken)["infrastructure_passed"], suffix)
        def empty(url, timeout, **kwargs):
            return [] if url.endswith("/api/v3/products") else self.request(url, timeout, **kwargs)
        self.assertFalse(module.inspect(self.args(), empty)["infrastructure_passed"])
        def wrong_model(url, timeout, **kwargs):
            return {"models": [{"name": "another-model"}]} if url.endswith("/api/tags") else self.request(url, timeout, **kwargs)
        self.assertFalse(module.inspect(self.args(), wrong_model)["infrastructure_passed"])

    def test_mlx_backend_requires_the_served_trained_model_and_vision(self):
        health = {"status": "ok", "local_backend": "mlx", "local_model": "porukam-buyer-qwen3.5", "vision_model": "qwen3.5:9b"}
        def ok(url, timeout, **kw):
            if url.endswith("/health"):
                return health
            return self.request(url, timeout, **kw)
        self.assertTrue(module.inspect(self.args(), ok)["infrastructure_passed"])
        def no_model(url, timeout, **kw):
            if url.endswith("/v1/models"):
                return {"data": [{"id": "another-model"}]}
            return ok(url, timeout, **kw)
        report = module.inspect(self.args(), no_model)
        self.assertFalse(report["infrastructure_passed"])
        self.assertIn("MLX", " ".join(check["name"] for check in report["checks"] if not check["passed"]))
        def no_vision(url, timeout, **kw):
            if url.endswith("/api/tags"):
                return {"models": [{"name": "another-model"}]}
            return ok(url, timeout, **kw)
        self.assertFalse(module.inspect(self.args(), no_vision)["infrastructure_passed"])

    def test_external_urls_credentials_and_query_tokens_are_rejected(self):
        for value in ("https://example.com", "http://localhost@evil.test", "http://localhost/?token=secret", "http://u:p@localhost", "http://localhost/api"):
            with self.assertRaises(argparse.ArgumentTypeError):
                module.local_url(value)
        self.assertEqual(module.local_url("http://localhost:3000/"), "http://localhost:3000")


if __name__ == "__main__":
    unittest.main()
