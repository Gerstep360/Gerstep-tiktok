"""Offline checks runnable from this repository alone."""
import asyncio
from contextlib import contextmanager
import dataclasses
import json
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from backend.config import Config
from backend.database import Database
from backend.domain import Domain
from backend.freshness import Freshness
from backend.passwords import hash_password, verify_password
from backend.security import Security
from backend.server import create_app, HUB
from backend.tiktok_intake import Intake
from backend.validation import youtube_id
from deploy import nginx, tls
from deploy import cli
from deploy.ui import UI
from deploy.cli import copy_application, origin, settings
from deploy.code_backup import CodeBackup
from deploy.package import package
from deploy.system import Transaction, read_env, write_env


def config(**kwargs):
    return Config('http://127.0.0.1:9081', 's'*48, 'b'*48, 'a'*48, database=':memory:', development=True, **kwargs)


class DeploymentTests(unittest.TestCase):
    def test_menu_restarts_with_downloaded_code_before_installing(self):
        repo = Path('/test/standalone-source')
        ui = SimpleNamespace(banner=lambda: None, say=lambda *args: None, ask=lambda *args: '1')
        with patch.object(cli.sys, 'platform', 'linux'), patch.object(cli.os, 'geteuid', return_value=0, create=True), \
                patch.object(cli, 'UI', return_value=ui), patch.object(cli, 'Runner'), \
                patch.object(cli, 'read_env', return_value={}), patch.object(cli, 'refresh_repository', return_value=repo), \
                patch.object(cli, 'install') as install, patch.object(cli.os, 'execv', side_effect=SystemExit) as execute, \
                patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit): cli.main()
            execute.assert_called_once_with(sys.executable, [sys.executable, str(repo / 'deploy/cli.py')])
            install.assert_not_called()
            self.assertEqual(os.environ['GERSTEP_INSTALL_AFTER_SYNC'], '1')

    def test_restarted_menu_installs_once_without_fetch_loop(self):
        ui = SimpleNamespace(banner=lambda: None, say=lambda *args: None, ask=lambda *args: '0')
        with patch.object(cli.sys, 'platform', 'linux'), patch.object(cli.os, 'geteuid', return_value=0, create=True), \
                patch.object(cli, 'UI', return_value=ui), patch.object(cli, 'Runner'), \
                patch.object(cli, 'refresh_repository') as refresh, patch.object(cli, 'install') as install, \
                patch.dict(os.environ, {'GERSTEP_INSTALL_AFTER_SYNC': '1'}, clear=True):
            cli.main()
            install.assert_called_once()
            refresh.assert_not_called()
            self.assertNotIn('GERSTEP_INSTALL_AFTER_SYNC', os.environ)

    def test_public_health_reports_nginx_failure_and_does_not_accept_html(self):
        endpoint = 'https://example.org/Gerstep/api/health'
        for failure in (HTTPError(endpoint, 404, 'Not Found', {}, None), ValueError('HTML page')):
            opener = SimpleNamespace(open=lambda *args, **kwargs: None)
            with patch.object(cli, 'build_opener', return_value=opener), \
                    patch.object(opener, 'open', side_effect=failure), patch.object(cli.time, 'sleep'), \
                    self.assertRaisesRegex(RuntimeError, 'backend local responde.*' + endpoint):
                cli.public_health('https://example.org')

    def test_public_health_checks_json_and_refuses_redirects(self):
        response = io.BytesIO(b'{"ok": true}')
        response.status = 200
        opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        with patch.object(cli, 'build_opener', return_value=opener):
            cli.public_health('https://example.org')
        self.assertIsNone(cli.NoRedirect().redirect_request(None, None, 301, '', {}, 'https://other.org'))

    def test_menu_password_explains_length_and_mismatch_without_printing_secrets(self):
        output = io.StringIO()
        with patch('sys.stdout', output), patch('getpass.getpass', side_effect=[
                'short', 'valid-password-123', 'different-password-123', 'valid-password-123', 'valid-password-123']):
            self.assertEqual(UI().password(), 'valid-password-123')
        self.assertIn('de 12 a 256 caracteres', output.getvalue())
        self.assertIn('no coinciden', output.getvalue())
        self.assertNotIn('valid-password', output.getvalue())

    def test_step_status_is_readable_without_unicode_symbols(self):
        output = io.StringIO()
        with patch('sys.stdout', output):
            ui = UI()
            with ui.step('Preparar'): pass
            with self.assertRaises(RuntimeError), ui.step('Validar'): raise RuntimeError('test')
        self.assertIn('[OK] Preparar', output.getvalue())
        self.assertIn('[ERROR] Validar', output.getvalue())
        self.assertNotIn('\033', output.getvalue())

    def test_code_backup_restores_existing_program_without_touching_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app/backend').mkdir(parents=True)
            (root / 'app/backend/server.py').write_text('old program')
            (root / 'app/data').mkdir()
            (root / 'app/data/db').write_text('votes')
            backup = CodeBackup(root / 'app', root / 'backup')
            backup.save()
            (root / 'app/backend/server.py').write_text('new program')
            backup.restore()
            self.assertEqual((root / 'app/backend/server.py').read_text(), 'old program')
            self.assertEqual((root / 'app/data/db').read_text(), 'votes')

    def test_installer_plan_with_existing_https_and_simulated_nginx_failure(self):
        # No Linux service or real /etc file is changed by this plan test.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, env, site = root / 'app', root / 'env', root / 'nginx.conf'
            original = 'events {} http { server { listen 443 ssl; server_name 167.86.106.105; location / { return 200 "other"; } } }'
            site.write_text(original)
            values = {'GERSTEP_ORIGIN': 'https://167.86.106.105', 'GERSTEP_PORT': '9081',
                      'GERSTEP_DB': str(app / 'data/interactive.sqlite3'), 'GERSTEP_COLLECT_TIKTOK': '0'}
            commands, writes, snapshots = [], {}, []
            fail = [True]
            public_fail = [False]
            def public_health(*args):
                if public_fail[0]: raise RuntimeError('simulated public route 404')
            class UI:
                def say(self, *args): pass
                def yes(self, *args): return True
                @contextmanager
                def step(self, *args): yield
            class Runner:
                def capture(self, args):
                    snapshots.append(site.read_text())
                    return 'loaded config'
                def run(self, args, **kwargs):
                    commands.append([str(value) for value in args])
                    if fail[0] and args == ['nginx', '-t'] and kwargs.get('check', True): raise RuntimeError('simulated Nginx failure')
                    return 0
            class Tx(Transaction):
                def __init__(self, backup): super().__init__(root / 'backup/config')
                def write(self, path, data, *args, **kwargs):
                    path = Path(path)
                    if not path.resolve().is_relative_to(root):
                        path = root / 'virtual' / path.as_posix().replace(':', '').lstrip('/')
                    writes[str(path)] = data
                    return super().write(path, data, *args, **kwargs)
            real_exists = Path.exists
            def exists(path):
                return True if str(path).replace('\\', '/') == '/run/systemd/system' else real_exists(path)
            with patch.object(cli, 'APP', app), patch.object(cli, 'ENV', env), patch.object(cli, 'settings', lambda *args: values), \
                    patch.object(cli, 'packages', lambda *args: None), patch.object(cli, 'ensure_frontend', lambda *args: None), \
                    patch.object(cli, 'Transaction', Tx), patch.object(cli, 'CodeBackup', lambda *args: CodeBackup(app, root / 'backup/code' / str(len(commands)))), \
                    patch.object(cli.shutil, 'which', lambda name: '/usr/bin/' + name), patch.object(Path, 'exists', exists), \
                    patch.object(tls, 'trusted', lambda *args: True), \
                    patch.object(nginx, 'loaded_files', lambda *args: {site: site.read_text()}), \
                    patch.object(cli, 'await_health', lambda *args: None), \
                    patch.object(cli, 'public_health', public_health):
                with self.assertRaisesRegex(RuntimeError, 'simulated Nginx failure'): cli.install(UI(), Runner())
                self.assertEqual(site.read_text(), original)
                self.assertFalse(env.exists())
                fail[0] = False
                public_fail[0] = True
                with self.assertRaisesRegex(RuntimeError, 'simulated public route 404'): cli.install(UI(), Runner())
                self.assertEqual(site.read_text(), original)
                self.assertFalse(env.exists())
                public_fail[0] = False
                cli.install(UI(), Runner())
            self.assertIn(nginx.INCLUDE, site.read_text())
            self.assertTrue(env.exists())
            self.assertEqual(snapshots[0], original)
            self.assertIn(['systemctl', 'restart', 'gerstep-interactive'], commands)
            self.assertNotIn(['systemctl', 'stop', 'nginx'], commands)
            unit = next(value for path, value in writes.items() if path.endswith('gerstep-interactive.service'))
            self.assertIn('-m backend.server', unit)
            self.assertNotIn('-m vps.backend.server', unit)

    def test_origin_and_input_validation(self):
        self.assertEqual(origin('https://167.86.106.105/Gerstep/'), 'https://167.86.106.105')
        self.assertEqual(origin('example.org'), 'https://example.org')
        for value in ('http://example.org', 'https://user:pw@example.org', 'https://example.org:42', 'https://example.org/other', '127.0.0.1', '10.2.3.4', 'bad;system()'):
            with self.subTest(value=value), self.assertRaises(ValueError): origin(value)

    def test_environment_is_data_not_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials'
            write_env(path, {'GERSTEP_ADMIN_PASSWORD_HASH': 'literal$hash', 'GERSTEP_OTHER': '$(not-a-command)'})
            self.assertEqual(read_env(path)['GERSTEP_ADMIN_PASSWORD_HASH'], 'literal$hash')
            self.assertEqual(read_env(path)['GERSTEP_OTHER'], '$(not-a-command)')
            with self.assertRaises(ValueError): write_env(path, {'GERSTEP_OTHER': 'line\nbreak'})

    def test_transaction_restores_every_file_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing, created = root / 'nginx.conf', root / 'snippet.conf'
            existing.write_text('other application')
            tx = Transaction(root / 'backup')
            with self.assertRaises(RuntimeError), tx.guard():
                tx.write(existing, 'modified')
                tx.write(created, 'new')
                raise RuntimeError('nginx -t failed')
            self.assertEqual(existing.read_text(), 'other application')
            self.assertFalse(created.exists())
            self.assertTrue(list((root / 'backup').rglob('nginx.conf')))

    def test_transaction_rolls_back_on_keyboard_interrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_text('original')
            with self.assertRaises(KeyboardInterrupt), Transaction(Path(directory) / 'backup').guard() as tx:
                tx.write(path, 'change')
                raise KeyboardInterrupt()
            self.assertEqual(path.read_text(), 'original')

    def test_refuses_unrelated_managed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'service'
            path.write_text('other application')
            with self.assertRaises(RuntimeError): Transaction(Path(directory) / 'backup').write(path, 'Gerstep', managed=True)
            self.assertEqual(path.read_text(), 'other application')

    def test_copy_never_includes_desktop_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            for name in ('backend', 'deploy', 'frontend', 'ai_common', 'gerstep_live'):
                (source / name).mkdir(parents=True)
                (source / name / 'sample.py').write_text('sample')
            for name in ('install', 'README.md', '.env.example'): (source / name).write_text('sample')
            (source / 'frontend/node_modules').mkdir()
            (source / 'frontend/node_modules/private').write_text('exclude')
            (target / 'data').mkdir(parents=True)
            (target / 'data/interactive.sqlite3').write_text('keep')
            copy_application(source, target)
            self.assertFalse((target / 'gerstep_live').exists())
            self.assertTrue((target / 'ai_common/sample.py').is_file())
            self.assertFalse((target / 'frontend/node_modules').exists())
            self.assertEqual((target / 'data/interactive.sqlite3').read_text(), 'keep')

    def test_archive_is_repository_root_and_has_executable_install(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'app.zip'
            result = package(output)
            self.assertGreater(result['files'], 25)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertIn('install', names)
                self.assertIn('backend/server.py', names)
                self.assertIn('frontend/dist/index.html', names)
                self.assertFalse(any(name.startswith(('vps/', 'gerstep_live/', '.git/')) or '/node_modules/' in name or '__pycache__' in name for name in names))
                self.assertEqual(archive.getinfo('install').external_attr >> 16 & 0o777, 0o755)
                self.assertNotIn(b'\r', archive.read('install'))

    def test_password_hash_and_verification(self):
        encoded = hash_password('my-example-password')
        self.assertNotIn('my-example-password', encoded)
        self.assertTrue(verify_password('my-example-password', encoded))
        self.assertFalse(verify_password('wrong', encoded))
        self.assertFalse(verify_password([], encoded))
        self.assertFalse(verify_password('abc', 'bad-format'))
        with self.assertRaises(ValueError): hash_password('short')

    def test_urls_are_a_strict_allowlist(self):
        for value in ('https://youtu.be/abcdefghijk', 'https://youtube.com/watch?v=abcdefghijk'):
            self.assertEqual(youtube_id(value), 'abcdefghijk')
        for value in ('https://youtube.com:bad/watch?v=abcdefghijk', 'http://youtu.be/abcdefghijk', 'https://evil.example/abcdefghijk', 'https://user@youtu.be/abcdefghijk'):
            self.assertIsNone(youtube_id(value))

    def test_update_keeps_secrets_and_uses_no_password_prompt(self):
        old = {'GERSTEP_ORIGIN': 'https://167.86.106.105', 'GERSTEP_PORT': '9234', 'GERSTEP_SESSION_SECRET': 's'*48,
               'GERSTEP_ADMIN_TOKEN': 'a'*48, 'GERSTEP_BRIDGE_TOKEN': 'b'*48, 'GERSTEP_ADMIN_PASSWORD_HASH': 'existing'}
        ui = SimpleNamespace(ask=lambda label, default='': default, yes=lambda *args: False)
        updated = settings(ui, old)
        for key in old: self.assertEqual(updated[key], old[key])


class NginxTests(unittest.TestCase):
    def test_server_rewrites_are_bypassed_only_for_gerstep_and_updates_repair_old_include(self):
        for rule in ('return 404;', 'return 301 https://$host$request_uri;',
                     'if ($request_method = GET) { return 404 "existing response"; }',
                     'rewrite ^ /other permanent;', 'include /etc/nginx/site-rewrites.conf;'):
            text = 'server { listen 443 ssl; server_name example.org; ' + rule + ' ' + nginx.INCLUDE + ' }'
            changed = nginx.attach(text, nginx.blocks(text)[0], 'example.org')
            with self.subTest(rule=rule):
                self.assertIn(rule, changed)
                self.assertLess(changed.index('break;'), changed.index(rule))
                self.assertIn('"^/Gerstep(/|$)"', changed)
                self.assertEqual(changed.count(nginx.INCLUDE), 1)
                self.assertEqual(nginx.attach(changed, nginx.blocks(changed)[0], 'example.org'), changed)

    def test_renewal_skips_reload_when_certificates_do_not_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'acme/live/gerstep').mkdir(parents=True)
            certificate = root / 'acme/live/gerstep/fullchain.pem'
            certificate.write_text('first')
            (root / 'certbot').write_text('fake binary')
            commands = []
            runner = SimpleNamespace(run=lambda args, **kwargs: commands.append(args))
            with patch.object(tls, 'ACME', root / 'acme'), patch.object(tls, 'CERTBOT', root / 'certbot'), \
                    patch.object(tls, 'STATE', root / 'state'), patch.object(tls, 'STAMP', root / 'stamp'):
                tls.renew(runner)
                self.assertEqual(commands.count(['systemctl', 'reload', 'nginx']), 1)
                tls.renew(runner)
                self.assertEqual(commands.count(['systemctl', 'reload', 'nginx']), 1)
                certificate.write_text('renewed')
                tls.renew(runner)
                self.assertEqual(commands.count(['systemctl', 'reload', 'nginx']), 2)

    def test_only_selected_server_changes_and_is_idempotent(self):
        other = 'server { listen 443 ssl; server_name other.example; location / { return 200 "other"; } }'
        text = other + '\nserver { listen 443 ssl default_server; server_name _; # } fake brace\n location / { return 404; } }'
        blocks = [b for b in nginx.blocks(text) if b.name == 'server']
        result = nginx.attach(text, blocks[1], '167.86.106.105')
        self.assertTrue(result.startswith(other))
        self.assertIn('server_name _ 167.86.106.105;', result)
        self.assertEqual(nginx.attach(result, [b for b in nginx.blocks(result) if b.name == 'server'][1], '167.86.106.105'), result)

    def test_nested_names_do_not_select_another_server(self):
        text = 'server { listen 443 ssl; server_name a.example; location / { set $server_name "167.86.106.105"; } }'
        block = nginx.blocks(text)[0]
        self.assertEqual(block.values('server_name'), [['a.example']])

    def test_acme_bypasses_server_redirect_only_for_challenge(self):
        text = 'server { listen 80; server_name a.example; return 301 https://$host$request_uri; }'
        changed = nginx.attach(text, nginx.blocks(text)[0], '167.86.106.105', nginx.CHALLENGE)
        self.assertIn('if ($uri ~', changed)
        self.assertLess(changed.index('break;'), changed.index('return 301'))
        self.assertIn('return 301 https://$host$request_uri;', changed)
        self.assertIn(nginx.CHALLENGE, changed)
        self.assertEqual(len(nginx.blocks(changed)), 1)

    def test_route_conflict_is_not_overwritten(self):
        text = 'server { listen 443 ssl; location /Gerstep/ { proxy_pass http://other; } }'
        with self.assertRaises(ValueError): nginx.attach(text, nginx.blocks(text)[0], '167.86.106.105')

    def test_http_include_is_added_once(self):
        path = Path('/etc/nginx/nginx.conf')
        text = 'events {} http { include /etc/nginx/conf.d/*.conf; server { listen 80; } }'
        _, candidate = nginx.http_include({path: text})
        self.assertEqual(candidate.count(nginx.HTTP_INCLUDE), 1)
        self.assertEqual(nginx.http_include({path: candidate})[1], candidate)

    def test_ip_tls_maps_preserve_other_domain_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site, certificate, key = root / 'site.conf', root / 'original.crt', root / 'original.key'
            certificate.write_text('existing-cert'); key.write_text('existing-key')
            issued, issued_key = root / 'new.crt', root / 'new.key'
            issued.write_text('new-cert'); issued_key.write_text('new-key')
            text = f'server {{ listen 443 ssl default_server; server_name other.example; ssl_certificate {certificate.as_posix()}; ssl_certificate_key {key.as_posix()}; }}'
            # A second server in the same file tests offset changes caused by the first edit.
            text += f'\nserver {{ listen 443 ssl; server_name 167.86.106.105; ssl_certificate {certificate.as_posix()}; ssl_certificate_key {key.as_posix()}; }}'
            site.write_text(text)
            writes = {}
            class Tx:
                def write(self, path, data, *args, **kwargs):
                    writes[str(path)] = data
                    if Path(path) in {site, root / 'state.json'}: Path(path).write_text(data)
            runner = SimpleNamespace(capture=lambda args: 'nginx/1.24.0' if args[-1] == '-v' else 'user www-data;')
            ui = SimpleNamespace(say=lambda *args: None)
            fake_group = SimpleNamespace(getgrnam=lambda name: SimpleNamespace(gr_gid=0))
            fake_user = SimpleNamespace(getpwnam=lambda name: SimpleNamespace(pw_gid=0))
            with patch.object(tls, 'TLS', root / 'tls'), patch.object(tls, 'STATE', root / 'state.json'), \
                    patch.dict(sys.modules, {'grp': fake_group, 'pwd': fake_user}), patch.object(os, 'chown', lambda *args: None, create=True):
                tls.install_certificate({site: text}, '167.86.106.105', issued, issued_key, ui, Tx(), runner)
                self.assertEqual((root / 'tls/previous-0.key').read_text(), 'existing-key')
                self.assertEqual((root / 'tls/ip.key').read_text(), 'new-key')
            changed = site.read_text()
            self.assertIn('server_name other.example;', changed)
            self.assertEqual(changed.count(nginx.INCLUDE), 1)
            maps = writes['/etc/nginx/gerstep-interactive-tls.conf']
            self.assertIn('default ', maps)
            self.assertIn('167.86.106.105 ', maps)
            self.assertIn('"" ', maps)


class FreshnessTests(unittest.TestCase):
    def test_history_warmup_duplicates_and_reconnect(self):
        now, wall = [0], [1800000000]
        gate = Freshness(lambda: now[0], lambda: wall[0])
        event = SimpleNamespace(base_message=SimpleNamespace(create_time=0, message_id='1'))
        self.assertFalse(gate.accept(event))
        gate.connect()
        self.assertFalse(gate.accept(event))
        now[0] = 4
        self.assertTrue(gate.accept(event))
        self.assertFalse(gate.accept(event))
        gate.disconnect(); gate.connect(); now[0] = 8
        self.assertFalse(gate.accept(event))
        event.base_message.message_id = '2'
        event.base_message.create_time = wall[0] - 100
        self.assertFalse(gate.accept(event))

    def test_memory_is_bounded(self):
        gate = Freshness(lambda: 10, lambda: 1800000000)
        gate.connect(); gate.started = 0
        for number in range(5000):
            gate.accept(SimpleNamespace(base_message=SimpleNamespace(create_time=0, message_id=str(number))))
        self.assertEqual(len(gate.ids), 4096)


class StandaloneFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_export_requires_admin_and_is_not_cached(self):
        conf = config(admin_password_hash=hash_password('example-panel-password'))
        client = TestClient(TestServer(create_app(conf)), cookie_jar=CookieJar(unsafe=True))
        await client.start_server()
        try:
            response = await client.get('/Gerstep/api/admin/connection')
            self.assertEqual(response.status, 401)
            response = await client.get('/Gerstep/api/admin/connection', headers={'X-Gerstep-Admin': conf.bridge_token})
            self.assertEqual(response.status, 401)
            response = await client.post('/Gerstep/api/admin/login', json={'token': 'example-panel-password'}, headers={'Origin': conf.origin})
            self.assertEqual(response.status, 200)
            response = await client.get('/Gerstep/api/admin/connection')
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(await response.json(), {'url': conf.origin + '/Gerstep', 'bridge_token': conf.bridge_token, 'admin_api_token': conf.admin_token})
            response = await client.get('/Gerstep/api/state')
            public = await response.text()
            self.assertNotIn(conf.bridge_token, public)
            self.assertNotIn(conf.admin_token, public)
        finally: await client.close()

    async def test_http_websocket_moderation_and_hashed_login(self):
        conf = config(admin_password_hash=hash_password('example-panel-password'))
        client = TestClient(TestServer(create_app(conf)), cookie_jar=CookieJar(unsafe=True))
        await client.start_server()
        headers = {'Origin': conf.origin}
        try:
            response = await client.post('/Gerstep/api/admin/login', json={'token': conf.admin_token}, headers=headers)
            self.assertEqual(response.status, 401)
            response = await client.post('/Gerstep/api/admin/login', json={'token': 'example-panel-password'}, headers=headers)
            self.assertEqual(response.status, 200)
            response = await client.post('/Gerstep/api/session', json={}, headers=headers)
            self.assertEqual(response.status, 200)
            response = await client.post('/Gerstep/api/viewer/submit', json={'text': 'Pregunta desde un paquete independiente'}, headers=headers)
            identifier = (await response.json())['id']
            response = await client.post('/Gerstep/api/admin/action', json={'action': 'approve', 'id': identifier}, headers=headers)
            self.assertEqual(response.status, 200)
            await asyncio.sleep(.1)
            socket = await client.ws_connect('/Gerstep/api/viewer/ws', headers=headers)
            state = await socket.receive_json(timeout=2)
            self.assertIn('Pregunta desde un paquete independiente', json.dumps(state))
            await socket.close()
            response = await client.get('/Gerstep/')
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.text()).startswith('<!doctype html>'))
        finally: await client.close()

    async def test_optional_intake_registers_once_and_closes_clients(self):
        records, closed = [], []
        async def emit(kind, payload): records.append((kind, payload))
        async def close(): closed.append(True)
        handlers = []
        client = SimpleNamespace(on=lambda kind, handler: handlers.append((kind, handler)), connected=False,
                                 web=SimpleNamespace(httpx_client=SimpleNamespace(aclose=close), curl_cffi_client=None))
        gate = Freshness(lambda: 10, lambda: 1800000000)
        intake = Intake('gerstep', emit, gate, client=client, event_types={name: name for name in ('Connect', 'Disconnect', 'Comment', 'Gift', 'Like', 'Join')})
        self.assertEqual(len(handlers), 6)
        await intake.connect(None)
        gate.started = 0
        event = SimpleNamespace(user=SimpleNamespace(id=123, unique_id='changed-handle', nickname='Name'), comment='hello',
                                base_message=SimpleNamespace(create_time=0, message_id='one'))
        await intake.comment(event); await intake.comment(event)
        self.assertEqual(sum(kind == 'comment' for kind, _ in records), 1)
        await intake.stop()
        event.base_message.message_id = 'new'
        await intake.comment(event)
        self.assertEqual(sum(kind == 'comment' for kind, _ in records), 1)
        self.assertEqual(closed, [True])

    async def test_local_levels_deduplicate_gifts_and_keep_stable_id(self):
        db = Database(':memory:'); await db.start()
        domain = Domain(Security(config()))
        try:
            comment = {'kind': 'comment', 'message': 'hello', 'metadata': {'user_id': '123', 'nickname': 'First'}, '_collector_profile': True}
            await db.call(domain.ingest, [comment, comment])
            gift = {'kind': 'gift', 'coins': 4, 'metadata': {'user_id': '123', 'nickname': 'Renamed', 'event_id': 'gift1'}, '_collector_profile': True}
            await db.call(domain.ingest, [gift, gift])
            rows = await db.call(lambda connection: [dict(row) for row in connection.execute('SELECT * FROM chat_profiles')])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['xp'], 13)
            self.assertEqual(rows[0]['nickname'], 'Renamed')
            await db.call(domain.ingest, [{'kind': 'profiles', 'profiles': [{'user_id': '123', 'nickname': 'Desktop', 'xp': 15, 'level': 3, 'rank': 'Insoportable'}]}])
            await db.call(domain.ingest, [gift])
            self.assertEqual(await db.call(lambda connection: connection.execute('SELECT xp FROM chat_profiles').fetchone()[0]), 15)
        finally: await db.close()

    async def test_music_submission_needs_no_desktop_module(self):
        db = Database(':memory:'); await db.start()
        domain = Domain(Security(config()))
        domain.features['music'] = True
        try:
            submitted = await db.call(domain.submit, 'owner', 'Viewer', {'kind': 'music', 'text': 'https://youtu.be/abcdefghijk'}, 'ip')
            self.assertIn('id', submitted)
            with self.assertRaises(ValueError):
                await db.call(domain.submit, 'other', 'Viewer', {'kind': 'music', 'text': 'https://youtube.com:bad/watch?v=abcdefghijk'}, 'other-ip')
        finally: await db.close()


if __name__ == '__main__': unittest.main()
