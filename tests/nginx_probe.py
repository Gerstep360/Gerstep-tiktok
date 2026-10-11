"""Optional REAL local Nginx/TLS/WS probe, using disposable test certificates.

NGINX_BINARY and OPENSSL_BINARY must identify installed binaries. No services
are installed, no public IP is contacted and no production certificate is issued.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aiohttp import ClientSession, CookieJar
from aiohttp.test_utils import TestServer
from backend.config import Config
from backend.server import create_app
from deploy import nginx


def command(args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, timeout=20)
    if result.returncode: raise RuntimeError(result.stderr.decode(errors='replace'))


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def certificate(openssl, folder, name, alternative):
    command([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
             '-subj', '/CN=' + name, '-addext', 'subjectAltName=' + alternative,
             '-keyout', folder / (name + '.key'), '-out', folder / (name + '.crt')])


def routing_response(tls_port, context, host, path, status):
    with socket.create_connection(('127.0.0.1', tls_port), timeout=3) as raw:
        with context.wrap_socket(raw, server_hostname='localhost') as stream:
            stream.sendall(f'GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n'.encode())
            received = b''
            while chunk := stream.recv(4096): received += chunk
            assert received.startswith(f'HTTP/1.1 {status} '.encode()), received


async def probe():
    binary, openssl = os.environ['NGINX_BINARY'], os.environ['OPENSSL_BINARY']
    tls_port = port()
    conf = Config(f'https://127.0.0.1:{tls_port}', 's'*48, 'b'*48, 'a'*48, database=':memory:')
    backend = TestServer(create_app(conf))
    await backend.start_server()
    try:
        with tempfile.TemporaryDirectory(prefix='gerstep-nginx-test-') as temporary:
            folder = Path(temporary)
            (folder / 'logs').mkdir()
            (folder / 'temp').mkdir()
            certificate(openssl, folder, 'localhost', 'DNS:localhost')
            certificate(openssl, folder, 'ip', 'IP:127.0.0.1')
            maps = '\n'.join(f'''map $ssl_server_name $gerstep_tls_{suffix} {{
                default "{folder.as_posix()}/localhost.{suffix}";
                "" "{folder.as_posix()}/ip.{suffix}";
                127.0.0.1 "{folder.as_posix()}/ip.{suffix}";
            }}''' for suffix in ('crt', 'key'))
            proxy = (ROOT / 'deploy/nginx-location.conf').read_text().replace('127.0.0.1:9081', f'127.0.0.1:{backend.port}')
            limits = (ROOT / 'deploy/nginx-limits.conf').read_text()
            original = f'''server {{ listen 127.0.0.1:{tls_port} ssl default_server;
                server_name localhost 127.0.0.1;
                ssl_certificate $gerstep_tls_crt; ssl_certificate_key $gerstep_tls_key;
                ssl_certificate_cache max=8 inactive=20s valid=1m;
                return 404 "original application";
                {nginx.INCLUDE}
            }}'''
            # Real regression: a valid proxy location is unreachable without the
            # server-rewrite bypass. Also preserve unrelated paths and redirects.
            unpatched = original.replace(' ssl default_server;', ' ssl;').replace(
                'server_name localhost 127.0.0.1;', 'server_name unpatched.local;').replace(nginx.INCLUDE, proxy)
            server = nginx.attach(original, nginx.blocks(original)[0], '127.0.0.1')
            server = server.replace(nginx.INCLUDE, proxy)
            for host, rule in (('redirect.local', 'return 301 https://example.org$request_uri;'),
                               ('conditional.local', 'if ($request_method = GET) { return 404; }')):
                candidate = original.replace(' ssl default_server;', ' ssl;').replace(
                    'server_name localhost 127.0.0.1;', f'server_name {host};').replace(
                    'return 404 "original application";', rule)
                server += '\n' + nginx.attach(candidate, nginx.blocks(candidate)[0], host).replace(nginx.INCLUDE, proxy)
            server += '\n' + unpatched
            path = folder / 'nginx.conf'
            path.write_text(f'worker_processes 1;\nevents {{ worker_connections 128; }}\nhttp {{\n{limits}\n{maps}\n{server}\n}}')
            command([binary, '-t', '-p', folder.as_posix() + '/', '-c', path.as_posix()])
            process = subprocess.Popen([binary, '-p', folder.as_posix() + '/', '-c', path.as_posix(), '-g', 'daemon off;'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for _ in range(40):
                    try:
                        with socket.create_connection(('127.0.0.1', tls_port), timeout=.1): break
                    except OSError: await asyncio.sleep(.05)
                ip_context = ssl.create_default_context(cafile=str(folder / 'ip.crt'))
                domain_context = ssl.create_default_context(cafile=str(folder / 'localhost.crt'))
                for host, route, status in (
                    ('unpatched.local', '/Gerstep/api/health', 404),
                    ('localhost', '/', 404), ('localhost', '/Gerstep-other', 404),
                    ('redirect.local', '/Gerstep/api/health', 200),
                    ('redirect.local', '/Gerstep-other', 301),
                    ('conditional.local', '/Gerstep/api/health', 200),
                    ('conditional.local', '/other', 404)):
                    await asyncio.to_thread(routing_response, tls_port, domain_context, host, route, status)
                base = conf.origin + '/Gerstep'
                async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
                    async with client.get(base + '/api/health', ssl=ip_context) as response: assert response.status == 200
                    headers = {'Origin': conf.origin}
                    async with client.post(base + '/api/session', json={}, headers=headers, ssl=ip_context) as response:
                        assert response.status == 200
                    async with client.ws_connect(base + '/api/viewer/ws', headers=headers, ssl=ip_context) as ws:
                        first = await ws.receive_json(timeout=3)
                        assert first['type'] == 'state'
                        async with client.post(base + '/api/viewer/submit', json={'text': 'Pregunta atravesando TLS y Nginx reales'}, headers=headers, ssl=ip_context) as response:
                            assert response.status == 200
                            identifier = (await response.json())['id']
                        async with client.post(base + '/api/admin/action', json={'action': 'approve', 'id': identifier},
                                               headers={**headers, 'X-Gerstep-Admin': conf.admin_token}, ssl=ip_context) as response:
                            assert response.status == 200
                        for _ in range(4):
                            received = await ws.receive_json(timeout=3)
                            if 'Pregunta atravesando TLS' in json.dumps(received): break
                        else: raise AssertionError('No se recibió la aprobación por WSS.')
                    async with client.get(base + '/', ssl=ip_context) as response:
                        assert response.status == 200
                        assert '<!doctype html>' in await response.text()
                return {'nginx_config': 'valid', 'https_ip_without_sni': True, 'existing_domain_with_sni': True,
                        'unpatched_server_return_reproduces_404': True, 'server_return_and_conditional_return_fixed': True,
                        'unrelated_paths_keep_original_status_and_redirect': True,
                        'real_proxy_http': True, 'real_proxy_websocket': True, 'frontend': True,
                        'certificates': 'disposable local fixtures, verified against their test CA', 'linux_systemd_install': False}
            finally:
                try: command([binary, '-p', folder.as_posix() + '/', '-c', path.as_posix(), '-s', 'quit'])
                finally:
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=5)
    finally: await backend.close()


if __name__ == '__main__': print(json.dumps(asyncio.run(probe()), indent=2))
