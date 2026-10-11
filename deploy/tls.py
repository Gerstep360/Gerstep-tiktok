"""Isolated ACME account and safe TLS routing for an IP on shared Nginx."""
import json
import ipaddress
import hashlib
import os
from pathlib import Path
import re
import socket
import ssl
import sys
from . import nginx
from .system import MANAGED, atomic_write

ACME = Path('/etc/gerstep-interactive/acme')
TLS = Path('/etc/gerstep-interactive/tls')
STATE = Path('/etc/gerstep-interactive/tls.json')
STAMP = Path('/etc/gerstep-interactive/certificate.stamp')
WEBROOT = Path('/var/lib/gerstep-interactive/acme')
CERTBOT = Path('/opt/gerstep-interactive/.certbot/bin/certbot')


def trusted(host):
    try:
        with socket.create_connection((host, 443), timeout=5) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=host): return True
    except (OSError, ValueError): return False


def certbot_args():
    return [str(CERTBOT), '--config-dir', str(ACME), '--work-dir', '/var/lib/gerstep-interactive/certbot',
            '--logs-dir', '/var/log/gerstep-interactive/certbot']


def prepare_http(files, host, ui, tx, runner):
    WEBROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(WEBROOT, 0o755)
    choice = nginx.choose(nginx.servers(files, 80), host, ui)
    if choice:
        tx.write(choice.path, nginx.attach(files[choice.path], choice, host, nginx.CHALLENGE))
    else:
        # Included explicitly in http context, independent of distro include conventions.
        tx.write('/etc/nginx/gerstep-interactive-acme.conf', MANAGED + '\nserver { listen 80; server_name ' + host + ';\n'
                 + nginx.CHALLENGE + '\nlocation / { return 404; }\n}\n', managed=True)
    runner.run(['nginx', '-t'])
    runner.run(['systemctl', 'reload', 'nginx'])


def issue(host, email, runner, ui):
    if not CERTBOT.is_file():
        with ui.step('Preparar Certbot aislado'):
            runner.run([sys.executable, '-m', 'venv', str(CERTBOT.parents[1])])
            runner.run([str(CERTBOT.with_name('python')), '-m', 'pip', 'install', '--disable-pip-version-check', 'certbot>=5.4,<7'])
    args = certbot_args() + ['certonly', '--non-interactive', '--agree-tos', '--email', email,
                            '--webroot', '--webroot-path', str(WEBROOT), '--cert-name', 'gerstep', '--keep-until-expiring']
    if re.fullmatch(r'[0-9.]+', host): args += ['--preferred-profile', 'shortlived', '--ip-address', host]
    else: args += ['-d', host]
    with ui.step('Solicitar certificado público y verificable'):
        runner.run(args, timeout=180)
    return ACME / 'live/gerstep/fullchain.pem', ACME / 'live/gerstep/privkey.pem'


def pairs(block):
    cert, key = block.values('ssl_certificate'), block.values('ssl_certificate_key')
    if len(cert) != 1 or len(key) != 1 or len(cert[0]) != 1 or len(key[0]) != 1:
        raise ValueError('El servidor TLS usa certificados heredados/múltiples. No se modificará automáticamente.')
    values = cert[0][0], key[0][0]
    if any('$' in value or not Path(value).is_absolute() or not Path(value).is_file() for value in values):
        raise ValueError('El certificado TLS existente no es un par de archivos estáticos; se requiere revisar ese servidor.')
    return values


def default_server(items):
    # Mixed specific-address listeners require an explicit review; don't guess TLS defaults.
    if any(values and values[0] not in {'443', '[::]:443', '0.0.0.0:443'} for b in items for values in b.values('listen')):
        raise ValueError('Nginx usa direcciones TLS específicas; el instalador no alterará ese esquema automáticamente.')
    defaults = [b for b in items if any('default_server' in values and values[0] != '[::]:443' for values in b.values('listen'))]
    return defaults[0] if defaults else items[0]


def install_certificate(files, host, certificate, key, ui, tx, runner):
    items = nginx.servers(files, 443)
    if not items:
        tx.write('/etc/nginx/gerstep-interactive-site.conf', MANAGED + '\nserver {\nlisten 443 ssl;\nserver_name ' + host + ';\n'
                 + 'ssl_certificate ' + str(certificate) + ';\nssl_certificate_key ' + str(key) + ';\nssl_protocols TLSv1.2 TLSv1.3;\n'
                 + nginx.INCLUDE + '\nlocation / { return 404; }\n}\n', managed=True)
        return
    # IP clients generally send no SNI. Preserve existing domain certificates via maps.
    try: ipaddress.ip_address(host); is_ip = True
    except ValueError: is_ip = False
    default = default_server(items) if is_ip else None
    target = nginx.choose(items, host, ui)
    if STATE.is_file() and Path('/etc/nginx/gerstep-interactive-tls.conf').is_file():
        refresh_copies(json.loads(STATE.read_text()))
        tx.write(target.path, nginx.attach(files[target.path], target, host))
        return
    affected = { (b.path, b.start): b for b in ((default, target) if is_ip else (target,)) }
    version = re.search(r'nginx/(\d+)\.(\d+)\.(\d+)', runner.capture(['nginx', '-v']))
    if not version or tuple(map(int, version.groups())) < (1, 15, 9):
        raise ValueError('El HTTPS compartido por IP requiere Nginx 1.15.9 o superior.')
    target_index = [b.start for b in nginx.blocks(files[target.path]) if b.name == 'server'].index(target.start)
    copies, maps, modifications = [], [], {}
    dump = runner.capture(['nginx', '-T'])
    match = re.search(r'^\s*user\s+([^;\s]+)(?:\s+([^;\s]+))?\s*;', dump, re.M)
    if not match: raise ValueError('No se pudo identificar el usuario de Nginx para proteger las claves TLS.')
    import grp
    import pwd
    gid = grp.getgrnam(match[2]).gr_gid if match[2] else pwd.getpwnam(match[1]).pw_gid
    TLS.mkdir(parents=True, exist_ok=True)
    os.chmod(TLS.parent, 0o755)
    os.chown(TLS, 0, gid)
    os.chmod(TLS, 0o750)
    copies.extend([(str(certificate), str(TLS / 'ip.crt')), (str(key), str(TLS / 'ip.key'))])
    for index, block in enumerate(affected.values()):
        old_cert, old_key = pairs(block)
        copies.extend([(old_cert, str(TLS / f'previous-{index}.crt')), (old_key, str(TLS / f'previous-{index}.key'))])
        for kind, suffix in (('certificate', 'crt'), ('certificate_key', 'key')):
            variable = f'$gerstep_tls_{suffix}_{index}'
            no_sni = f'{TLS}/ip.{suffix}' if is_ip else f'{TLS}/previous-{index}.{suffix}'
            maps.append(f'map $ssl_server_name {variable} {{\n default "{TLS}/previous-{index}.{suffix}";\n "" "{no_sni}";\n {host} "{TLS}/ip.{suffix}";\n}}')
            directive = next(d for d in block.directives if d[0] == 'ssl_' + kind)
            modifications.setdefault(block.path, []).append((directive[2], directive[3], 'ssl_' + kind + ' ' + variable + ';'))
        if tuple(map(int, version.groups())) >= (1, 27, 4) and not block.values('ssl_certificate_cache'):
            modifications.setdefault(block.path, []).append((block.opening, block.opening, '\n    ssl_certificate_cache max=8 inactive=20s valid=1m;\n'))
    for path, edits in modifications.items():
        text = files[path]
        for begin, end, replacement in sorted(edits, reverse=True): text = text[:begin] + replacement + text[end:]
        tx.write(path, text)
    tx.write('/etc/nginx/gerstep-interactive-tls.conf', MANAGED + '\n' + '\n'.join(maps) + '\n', managed=True)
    tx.write(STATE, json.dumps({'copies': copies, 'gid': gid}), 0o600)
    refresh_copies(json.loads(STATE.read_text()))
    # Offsets changed; rediscover the exact target in its modified file.
    text = target.path.read_text()
    fresh = [b for b in nginx.blocks(text) if b.name == 'server'][target_index]
    tx.write(target.path, nginx.attach(text, fresh, host))


def refresh_copies(state):
    for source, destination in state['copies']:
        if not Path(destination).resolve().is_relative_to(TLS): raise ValueError('Destino TLS inválido.')
        data = Path(source).read_bytes()
        if not Path(destination).is_file() or Path(destination).read_bytes() != data:
            atomic_write(destination, data, 0o640)
            os.chown(destination, 0, state['gid'])


def renew(runner):
    if not CERTBOT.is_file() and not STATE.is_file(): return
    if CERTBOT.is_file(): runner.run(certbot_args() + ['renew', '--non-interactive'], timeout=300)
    state = json.loads(STATE.read_text()) if STATE.is_file() else None
    sources = [Path(source) for source, _ in state['copies']] if state else list((ACME / 'live/gerstep').glob('*.pem'))
    if not sources: return
    signature = hashlib.sha256(b''.join(path.read_bytes() for path in sources)).hexdigest()
    if state: refresh_copies(state)
    if STAMP.is_file() and STAMP.read_text() == signature: return
    runner.run(['nginx', '-t'])
    runner.run(['systemctl', 'reload', 'nginx'])
    atomic_write(STAMP, signature, 0o600)
