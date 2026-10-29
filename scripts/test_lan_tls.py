import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("lan_tls", Path(__file__).with_name("lan-tls.py"))
module = importlib.util.module_from_spec(spec)
sys.modules["lan_tls"] = module
spec.loader.exec_module(module)


class AddressTest(unittest.TestCase):
    def test_only_private_network_addresses_survive(self):
        found = module.private_ipv4(["192.168.1.115", "10.0.0.7", "172.16.5.4", "127.0.0.1",
                                     "8.8.8.8", "192.168.1.115", "не-адрес", "172.32.0.1"])
        self.assertEqual(found, ["192.168.1.115", "10.0.0.7", "172.16.5.4"])

    def test_certificate_covers_network_loopback_and_local_name(self):
        entries = module.san_entries(["192.168.1.115", "192.168.1.115", "127.0.0.1"], "porukam.local")
        self.assertEqual(entries, ["IP:192.168.1.115", "IP:127.0.0.1", "DNS:localhost", "DNS:porukam.local"])
        self.assertEqual(len(entries), len(set(entries)))


@unittest.skipUnless(module.shutil.which("openssl"), "нужен openssl")
class CertificateTest(unittest.TestCase):
    def prepare(self, directory: Path):
        return module.prepare(directory, ["192.168.1.115"], "porukam.local", days=397, ca_days=3650, out=lambda _: None)

    def test_ca_and_leaf_are_private_and_cover_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "tls"
            self.prepare(directory)
            self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(directory / "ca.key").st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(directory / "privkey.pem").st_mode & 0o777, 0o600)
            san = subprocess.run(["openssl", "x509", "-noout", "-ext", "subjectAltName",
                                  "-in", str(directory / "leaf.pem")],
                                 capture_output=True, text=True, check=True).stdout
            self.assertIn("IP Address:192.168.1.115", san)
            self.assertIn("DNS:porukam.local", san)
            chain = (directory / "fullchain.pem").read_text()
            self.assertEqual(chain.count("BEGIN CERTIFICATE"), 2)

    def test_repeat_run_reuses_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "tls"
            self.prepare(directory)
            leaf = (directory / "leaf.pem").read_bytes()
            self.prepare(directory)
            self.assertEqual((directory / "leaf.pem").read_bytes(), leaf)

    def test_new_address_forces_reissue(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "tls"
            self.prepare(directory)
            first = (directory / "leaf.pem").read_bytes()
            module.prepare(directory, ["192.168.1.115", "10.1.2.3"], "porukam.local", out=lambda _: None)
            leaf = directory / "leaf.pem"
            self.assertNotEqual(leaf.read_bytes(), first)
            san = module.current_sans(leaf)
            self.assertIn("IP:10.1.2.3", san)
            ca = (directory / "ca.pem").read_text()
            self.assertIn("BEGIN CERTIFICATE", ca)


if __name__ == "__main__":
    unittest.main()
