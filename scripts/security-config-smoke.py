"""Validate published ports, mandatory secrets, and real nginx TLS configuration in CI."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update({key: secrets.token_hex(32) for key in (
        "JWT_SECRET", "OPTIMIZER_TOKEN", "POSTGRES_PASSWORD",
        "PGADMIN_DEFAULT_PASSWORD", "MINIO_ROOT_PASSWORD")})
    with tempfile.TemporaryDirectory(prefix="porukam-tls-test-") as directory:
        env["TLS_CERT_DIR"] = directory
        command = ["docker", "compose", "-f", "infra/docker-compose.yml",
                   "-f", "infra/docker-compose.https.yml", "config", "--format", "json"]
        config = json.loads(subprocess.check_output(command, cwd=root, env=env, text=True))
        assert not config["services"]["optimizer"].get("ports")
        for name, service in config["services"].items():
            if name != "edge":
                assert all(port["host_ip"] == "127.0.0.1" for port in service.get("ports", [])), name
        for secret in ("JWT_SECRET", "OPTIMIZER_TOKEN", "POSTGRES_PASSWORD",
                       "PGADMIN_DEFAULT_PASSWORD", "MINIO_ROOT_PASSWORD"):
            missing = dict(env, **{secret: ""})
            result = subprocess.run(command, cwd=root, env=missing, capture_output=True)
            assert result.returncode != 0, secret
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", directory + "/privkey.pem", "-out", directory + "/fullchain.pem",
                        "-days", "1", "-subj", "/CN=localhost"], check=True, capture_output=True)
        hosts = [item for name in ("web", "gateway-auth", "marketplace", "llm-gateway")
                 for item in ("--add-host", name + ":127.0.0.1")]
        subprocess.run(["docker", "run", "--rm", *hosts,
                        "-v", str(root / "infra/nginx-security.conf") + ":/etc/nginx/conf.d/default.conf:ro",
                        "-v", directory + ":/etc/nginx/tls:ro",
                        "nginx:stable-alpine", "nginx", "-t"], check=True)
    print("Секреты обязательны, служебные порты закрыты, конфигурация TLS корректна.")


if __name__ == "__main__":
    main()
