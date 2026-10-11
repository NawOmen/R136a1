"""The restart probe must resolve its own services before any HTTP write."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runtime_recovery', Path(__file__).with_name('check-runtime-recovery.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
PROJECT = 'r136-s15-test'
AUTH = 'http://localhost:18001'
LLM = 'http://localhost:18003'


def docker_reader(missing=None, seed=True, remote=False):
    def output(args, **kwargs):
        if args[1:3] == ['context', 'inspect']:
            return json.dumps([{'Endpoints': {'docker': {'Host': 'tcp://remote:2376' if remote else 'unix:///synthetic.sock'}}}])
        if args[1] == 'ps':
            service = args[-1].split('=')[-1]
            return '' if missing == service else service + '-id'
        if args[1] == 'inspect':
            service = args[-1].removesuffix('-id')
            port = '8001/tcp' if service == 'gateway-auth' else '8003/tcp'
            host_port = '18001' if service == 'gateway-auth' else '18003'
            return json.dumps([{'State': {'Running': True}, 'Config': {'Env': ['ENABLE_DEMO_SEED=true'] if seed else [],
                'Labels': {'com.docker.compose.project': PROJECT, 'com.docker.compose.service': service}},
                'NetworkSettings': {'Ports': {port: [{'HostIp': '127.0.0.1', 'HostPort': host_port}]}}}])
        raise AssertionError('Unexpected Docker read')
    return output


class RestartIsolation(unittest.TestCase):
    def main_args(self, auth=AUTH, llm=LLM):
        return ['check-runtime-recovery.py', '--project', PROJECT, '--auth-url', auth, '--llm-url', llm]

    def test_bad_project_ports_seed_or_daemon_fail_before_http(self):
        for reader, auth, llm in [(docker_reader(missing='llm-gateway'), AUTH, LLM),
            (docker_reader(), 'http://localhost:19001', LLM), (docker_reader(), AUTH, 'http://localhost:19003'),
            (docker_reader(seed=False), AUTH, LLM), (docker_reader(remote=True), AUTH, LLM),
            (docker_reader(), 'http://foreign.invalid:18001', LLM),
            (docker_reader(), AUTH, 'http://localhost:18003/private')]:
            with self.subTest(auth=auth, llm=llm), patch.dict(os.environ, {'ENABLE_DEMO_SEED': 'true'}, clear=True), \
                patch.object(sys, 'argv', self.main_args(auth, llm)), \
                patch.object(runtime.subprocess, 'check_output', side_effect=reader), \
                patch.object(runtime.subprocess, 'run') as restart, \
                patch.object(runtime.urllib.request, 'build_opener') as http:
                with self.assertRaises(ValueError):
                    runtime.main()
                http.assert_not_called()
                restart.assert_not_called()

    def test_valid_urls_are_pinned_to_explicit_published_ipv4(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime.subprocess, 'check_output', side_effect=docker_reader()):
            self.assertEqual(runtime.isolated_endpoints(PROJECT, AUTH, LLM),
                ('llm-gateway-id', 'http://127.0.0.1:18001', 'http://127.0.0.1:18003'))
            with self.assertRaises(ValueError):
                runtime.isolated_endpoints(PROJECT, AUTH, 'http://[::1]:18003')

    def test_redirect_cannot_send_credentials_to_another_endpoint(self):
        req = runtime.urllib.request.Request('http://127.0.0.1:18001/api/v1/auth/login')
        with self.assertRaises(runtime.urllib.error.HTTPError):
            runtime.NoRedirect().redirect_request(req, None, 307, 'redirect', {}, 'http://foreign.invalid')

    def test_valid_project_restarts_only_its_gateway_and_preserves_task(self):
        calls = []
        task = {'task_id': 'synthetic-task', 'state': 'running', 'input_revision': 1,
                'idempotency_key': 'synthetic', 'attempts': 1, 'linked_run_id': None,
                'approval': None, 'result_artifact': None}
        def http(req, **kwargs):
            calls.append(req.full_url)
            path = runtime.urllib.parse.urlsplit(req.full_url).path
            if path.endswith('/login'): value = {'access_token': 'synthetic-only'}
            elif path.endswith('/me'): value = {'companies': [{'id': 'synthetic-company', 'inn': '0000000001', 'membership': {'can_buy': True}}]}
            elif path.endswith('/resume'): raise runtime.urllib.error.HTTPError(req.full_url, 409, 'alive', {}, None)
            elif path == '/health': value = {'status': 'ok'}
            else: value = task
            return io.BytesIO(json.dumps(value).encode())
        with patch.dict(os.environ, {'ENABLE_DEMO_SEED': 'true', 'E2E_BUYER_PASSWORD': 'synthetic-only'}, clear=True), \
            patch.object(sys, 'argv', self.main_args()), \
            patch.object(runtime.subprocess, 'check_output', side_effect=docker_reader()), \
            patch.object(runtime.subprocess, 'run') as restart, \
            patch.object(runtime.urllib.request, 'build_opener', return_value=SimpleNamespace(open=http)):
            runtime.main()
        self.assertEqual(restart.call_args.args[0], ['docker', 'restart', 'llm-gateway-id'])
        self.assertTrue(all(url.startswith(('http://127.0.0.1:18001/', 'http://127.0.0.1:18003/')) for url in calls))


if __name__ == '__main__':
    unittest.main()
