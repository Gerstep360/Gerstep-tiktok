"""Zero-argument Linux menu. Only Gerstep owns its service, files and data."""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import sys
import time
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener, urlopen

SOURCE = Path(__file__).resolve().parents[1]
if str(SOURCE) not in sys.path: sys.path.insert(0, str(SOURCE))
from backend.passwords import hash_password
from deploy.ui import UI
from deploy.system import MANAGED, Runner, Transaction, atomic_write, free_port, packages, read_env, write_env
from deploy import nginx, tls
from deploy.frontend import ensure_frontend
from deploy.code_backup import CodeBackup
from deploy.repository import refresh as refresh_repository

APP = Path('/opt/gerstep-interactive')
ENV = Path('/etc/gerstep-interactive.env')
SERVICE = 'gerstep-interactive'


def origin(value):
    value = value.strip().rstrip('/')
    if '://' not in value: value = 'https://' + value
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.path not in ('', '/Gerstep') or parsed.query or parsed.fragment:
        raise ValueError('Usá una IP/dominio HTTPS sin puerto especial; la ruta es /Gerstep.')
    host = parsed.hostname
    try: address = ipaddress.ip_address(host)
    except ValueError:
        if not host or not re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}', host):
            raise ValueError('IP pública o dominio inválido.')
    else:
        if address.version != 4 or not address.is_global: raise ValueError('Usá una IPv4 pública para HTTPS automático.')
    return 'https://' + host


def copy_application(source, target):
    if Path(source).resolve() == Path(target).resolve(): return
    target.mkdir(parents=True, exist_ok=True)
    for name in ('backend', 'deploy', 'frontend', 'ai_common'):
        shutil.copytree(source / name, target / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('node_modules', '__pycache__', '.git', '.env', 'data'))
        # Uploaded directories can have private modes; the unprivileged service needs read access.
        for path in (target / name).rglob('*'):
            if not path.is_symlink(): os.chmod(path, 0o755 if path.is_dir() else 0o644)
        os.chmod(target / name, 0o755)
    for name in ('install', 'README.md', '.env.example'):
        shutil.copy2(source / name, target / name)
    os.chmod(target / 'install', 0o755)


def health(port):
    with urlopen(f'http://127.0.0.1:{port}/Gerstep/api/health', timeout=3) as response:
        if response.status != 200: raise RuntimeError('El servidor no responde correctamente.')


def await_health(port):
    for _ in range(20):
        try: health(port); return
        except OSError: time.sleep(.5)
    raise RuntimeError('El servicio no inició. Revisá el registro del menú.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def public_health(base):
    endpoint = base + '/Gerstep/api/health'
    # Test the actual VPS route, without shell proxy settings or redirect fallback.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    detail = ''
    for attempt in range(3):
        try:
            with opener.open(endpoint, timeout=3) as response:
                payload = json.loads(response.read(1024))
                if response.status != 200 or not isinstance(payload, dict) or payload.get('ok') is not True:
                    raise ValueError('respuesta inesperada')
            return
        except HTTPError as exc:
            detail = f'Nginx respondió HTTP {exc.code}'
            exc.close()
        except (URLError, OSError):
            detail = 'no se pudo conectar o validar HTTPS'
        except (ValueError, UnicodeError):
            detail = 'la ruta no devolvió la respuesta de salud de Gerstep'
        if attempt < 2: time.sleep(.5)
    raise RuntimeError(f'El backend local responde, pero {detail} en {endpoint}. '
                       'Revisá el servidor Nginx seleccionado y sus reglas de /Gerstep. '
                       'Se cancelará la instalación y se restaurará la configuración anterior.')


def settings(ui, old):
    values = dict(old)
    if (SOURCE / '.git').exists(): values['GERSTEP_SOURCE_REPO'] = str(SOURCE.resolve())
    values['GERSTEP_ORIGIN'] = origin(ui.ask('IP o dominio público', old.get('GERSTEP_ORIGIN', 'https://167.86.106.105')))
    if 'GERSTEP_PORT' not in values: values['GERSTEP_PORT'] = str(free_port())
    if not values['GERSTEP_PORT'].isdecimal() or not 1024 <= int(values['GERSTEP_PORT']) <= 65535:
        raise ValueError('El puerto guardado es inválido; usá un valor de 1024 a 65535.')
    values['GERSTEP_DB'] = str(APP / 'data/interactive.sqlite3')
    values['GERSTEP_DEVELOPMENT'] = '0'
    for name in ('SESSION_SECRET', 'BRIDGE_TOKEN', 'ADMIN_TOKEN'):
        key = 'GERSTEP_' + name
        if not values.get(key): values[key] = secrets.token_urlsafe(48)
    if not values.get('GERSTEP_ADMIN_PASSWORD_HASH'):
        values['GERSTEP_ADMIN_PASSWORD_HASH'] = hash_password(ui.password())
    from backend.config import Config
    Config(values['GERSTEP_ORIGIN'], values['GERSTEP_SESSION_SECRET'], values['GERSTEP_BRIDGE_TOKEN'], values['GERSTEP_ADMIN_TOKEN'])
    collect = ui.yes('¿Leer TikTok desde el VPS cuando el programa esté desconectado?', old.get('GERSTEP_COLLECT_TIKTOK') == '1')
    values['GERSTEP_COLLECT_TIKTOK'] = '1' if collect else '0'
    if collect:
        username = ui.ask('Usuario de TikTok', old.get('GERSTEP_TIKTOK_USERNAME', 'gerstep_official')).lstrip('@')
        if not re.fullmatch(r'[A-Za-z0-9_.]{2,50}', username): raise ValueError('Usuario de TikTok inválido.')
        values['GERSTEP_TIKTOK_USERNAME'] = username
    return values


def install(ui, runner):
    values = settings(ui, read_env(ENV))
    host = urlparse(values['GERSTEP_ORIGIN']).hostname
    reuse_tls = tls.trusted(host)
    email = ''
    if not reuse_tls:
        ui.say('Hace falta un certificado válido. Se solicitará con una cuenta ACME propia; el puerto 80 debe ser accesible.', '33')
        email = ui.ask('Email para avisos del certificado')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email): raise ValueError('Email inválido.')
        ui.say('Condiciones de Let’s Encrypt: https://letsencrypt.org/repository/')
        if not ui.yes('¿Aceptás esas condiciones para emitir el certificado?'): return
    ui.say(f'\nDestino: {APP}\nWeb: {values["GERSTEP_ORIGIN"]}/Gerstep/\nLogin privado: /Gerstep/login\nPuerto interno: {values["GERSTEP_PORT"]}\nSe conservan claves, votos y datos al actualizar.')
    if not ui.yes('¿Aplicar esta configuración?', True): return
    with ui.step('Preparar paquetes del sistema'):
        packages(runner)
        if not shutil.which('systemctl') or not Path('/run/systemd/system').exists(): raise RuntimeError('Se requiere Linux con systemd.')
        if sys.version_info < (3, 10): raise RuntimeError('Se requiere Python 3.10 o superior.')
        runner.run(['systemctl', 'enable', '--now', 'nginx'])
    ensure_frontend(SOURCE, runner, ui)
    backup_dir = Path('/var/backups/gerstep-interactive') / (time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
    tx = Transaction(backup_dir)
    code = CodeBackup(APP, backup_dir / 'code')
    with ui.step('Guardar versión anterior del programa'):
        code.save()
    was_active = runner.run(['systemctl', 'is-active', '--quiet', SERVICE], check=False) == 0
    was_enabled = runner.run(['systemctl', 'is-enabled', '--quiet', SERVICE], check=False) == 0
    timer_enabled = runner.run(['systemctl', 'is-enabled', '--quiet', 'gerstep-interactive-renew.timer'], check=False) == 0
    try:
        if was_active: runner.run(['systemctl', 'stop', SERVICE])
        with ui.step('Instalar únicamente backend, React y herramientas VPS'):
            copy_application(SOURCE, APP)
            if runner.run(['id', SERVICE], check=False): runner.run(['useradd', '--system', '--home-dir', str(APP), '--shell', '/usr/sbin/nologin', SERVICE])
            runner.run([sys.executable, '-m', 'venv', str(APP / '.venv')])
            requirement = 'requirements-collector.txt' if values['GERSTEP_COLLECT_TIKTOK'] == '1' else 'requirements.txt'
            runner.run([APP / '.venv/bin/python', '-m', 'pip', 'install', '--disable-pip-version-check', '-r', APP / 'backend' / requirement])
            data = APP / 'data'
            data.mkdir(exist_ok=True)
            os.chmod(data, 0o700)
            runner.run(['chown', '-R', SERVICE + ':' + SERVICE, str(data)])
        with tx.guard():
            # Preserve credentials before a failed change; no plaintext admin password is saved.
            tx.write(ENV, ''.join(f'{key}={value}\n' for key, value in sorted(values.items())), 0o600)
            with ui.step('Preparar configuración aislada de Nginx'):
                files = nginx.loaded_files(runner.capture(['nginx', '-T']))
                for name in ('acme', 'site', 'tls'):
                    path = Path(f'/etc/nginx/gerstep-interactive-{name}.conf')
                    if not path.exists(): tx.write(path, MANAGED + '\n', managed=True)
                limit = Path('/etc/nginx/conf.d/gerstep-interactive-limits.conf')
                if limit.exists(): tx.write(limit, MANAGED + '\n', managed=True)
                snippet = (SOURCE / 'deploy/nginx-location.conf').read_text().replace('127.0.0.1:9081', '127.0.0.1:' + values['GERSTEP_PORT'])
                tx.write('/etc/nginx/snippets/gerstep-interactive.conf', snippet, managed=True)
                limits = (SOURCE / 'deploy/nginx-limits.conf').read_text()
                limits += ''.join(f'\ninclude /etc/nginx/gerstep-interactive-{name}.conf;' for name in ('acme', 'tls', 'site')) + '\n'
                tx.write('/etc/nginx/gerstep-interactive-http.conf', limits, managed=True)
                path, text = nginx.http_include(files)
                tx.write(path, text)
            if not reuse_tls:
                files = nginx.loaded_files(runner.capture(['nginx', '-T']))
                tls.prepare_http(files, host, ui, tx, runner)
                certificate, key = tls.issue(host, email, runner, ui)
                files = nginx.loaded_files(runner.capture(['nginx', '-T']))
                tls.install_certificate(files, host, certificate, key, ui, tx, runner)
            else:
                files = nginx.loaded_files(runner.capture(['nginx', '-T']))
                chosen = nginx.choose(nginx.servers(files, 443), host, ui)
                if not chosen: raise RuntimeError('El HTTPS público no pertenece a este Nginx; configurá el proxy que lo termina.')
                tx.write(chosen.path, nginx.attach(files[chosen.path], chosen, host))
            with ui.step('Validar Nginx y arrancar Gerstep'):
                tx.write('/etc/systemd/system/gerstep-interactive.service', (SOURCE / 'deploy/gerstep-interactive.service').read_text(), managed=True)
                renewal_units(tx)
                runner.run(['nginx', '-t'])
                runner.run(['systemctl', 'daemon-reload'])
                runner.run(['systemctl', 'enable', SERVICE])
                runner.run(['systemctl', 'restart', SERVICE])
                await_health(int(values['GERSTEP_PORT']))
                runner.run(['systemctl', 'reload', 'nginx'])
                if not tls.trusted(host): raise RuntimeError('La verificación HTTPS pública falló. No se dará por completa la instalación.')
                public_health(values['GERSTEP_ORIGIN'])
                if tls.CERTBOT.is_file() or tls.STATE.is_file():
                    runner.run(['systemctl', 'enable', '--now', 'gerstep-interactive-renew.timer'])
                elif timer_enabled:
                    runner.run(['systemctl', 'disable', '--now', 'gerstep-interactive-renew.timer'])
    except BaseException:
        # The transaction restores Nginx, environment and units, including on Ctrl+C.
        code.restore()
        if not was_enabled: runner.run(['systemctl', 'disable', SERVICE], check=False)
        if not timer_enabled: runner.run(['systemctl', 'disable', '--now', 'gerstep-interactive-renew.timer'], check=False)
        runner.run(['systemctl', 'daemon-reload'], check=False)
        runner.run(['systemctl', 'restart' if was_active else 'stop', SERVICE], check=False)
        valid = runner.run(['nginx', '-t'], check=False) == 0
        if valid: runner.run(['systemctl', 'reload', 'nginx'], check=False)
        if valid and tx.is_restored(): ui.say('Se restauró la configuración anterior y el código. Los datos se conservaron.', '33')
        else: ui.say('La recuperación requiere revisión. Copias disponibles en ' + str(backup_dir), '31')
        raise
    ui.say(f'\nListo: {values["GERSTEP_ORIGIN"]}/Gerstep/\nAdministración: {values["GERSTEP_ORIGIN"]}/Gerstep/login', '32')
    ui.say('Podés cerrar SSH: systemd mantiene el servicio en segundo plano. Conexión al PC: opción 5 del menú.')


def renewal_units(tx):
    tx.write('/etc/systemd/system/gerstep-interactive-renew.service', MANAGED + '\n[Unit]\nDescription=Gerstep isolated certificate refresh\nAfter=nginx.service\n[Service]\nType=oneshot\nExecStart=/opt/gerstep-interactive/.venv/bin/python /opt/gerstep-interactive/deploy/renew.py\n', managed=True)
    tx.write('/etc/systemd/system/gerstep-interactive-renew.timer', MANAGED + '\n[Unit]\nDescription=Gerstep hourly certificate renewal check\n[Timer]\nOnBootSec=5min\nOnUnitActiveSec=1h\nRandomizedDelaySec=5min\nPersistent=true\n[Install]\nWantedBy=timers.target\n', managed=True)


def backup(ui):
    values = read_env(ENV)
    database = Path(values.get('GERSTEP_DB', APP / 'data/interactive.sqlite3'))
    if not database.is_file(): raise RuntimeError('Todavía no hay una base de datos instalada.')
    target = Path('/var/backups/gerstep-interactive') / ('interactive-' + time.strftime('%Y%m%d-%H%M%S') + '.sqlite3')
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as source, sqlite3.connect(target) as destination: source.backup(destination)
    os.chmod(target, 0o600)
    ui.say('Copia consistente de SQLite: ' + str(target), '32')


def export_connection(ui):
    values = read_env(ENV)
    if not values: raise RuntimeError('Primero instalá Gerstep.')
    path = Path('/root/gerstep-pc-connection.json')
    atomic_write(path, json.dumps({'url': values['GERSTEP_ORIGIN'] + '/Gerstep',
                 'bridge_token': values['GERSTEP_BRIDGE_TOKEN'], 'admin_api_token': values['GERSTEP_ADMIN_TOKEN']}, indent=2), 0o600)
    ui.say('Claves guardadas sin mostrarlas: ' + str(path) + '\nUsalas en el panel Interactive del programa del PC. No publiques este archivo.')


def main():
    ui = UI()
    if sys.platform != 'linux' or os.geteuid() != 0: raise SystemExit('Ejecutá ./install en el VPS Linux; se solicitará sudo si hace falta.')
    if sys.version_info < (3, 10): raise SystemExit('Python 3.10+ requerido (Debian 12+, Ubuntu 22.04+ o equivalente).')
    runner = Runner('/var/log/gerstep-interactive/install-' + time.strftime('%Y%m%d-%H%M%S') + '.log')
    after_sync = os.environ.pop('GERSTEP_INSTALL_AFTER_SYNC', '') == '1'
    while True:
        ui.banner()
        ui.say('  1  Instalar / actualizar\n  2  Estado y diagnóstico\n  3  Reiniciar Gerstep\n  4  Cambiar contraseña del administrador\n  5  Exportar conexión para el PC\n  6  Activar / desactivar lector de TikTok\n  7  Ver últimas incidencias\n  8  Copia de seguridad de los datos\n  9  Configurar NVIDIA (IA privada)\n  0  Salir')
        try:
            synced = after_sync
            choice = '1' if synced else ui.ask('Opción', '1')
            after_sync = False
            if choice == '0': return
            if choice == '1':
                if not synced:
                    repo = refresh_repository(SOURCE, APP, read_env(ENV), ui, runner)
                    if repo:
                        os.environ['GERSTEP_INSTALL_AFTER_SYNC'] = '1'
                        os.execv(sys.executable, [sys.executable, str(repo / 'deploy/cli.py')])
                        return
                install(ui, runner)
            elif choice == '2':
                code = runner.run(['systemctl', 'is-active', '--quiet', SERVICE], check=False)
                ui.say('Gerstep: ' + ('activo' if code == 0 else 'inactivo'), '32' if code == 0 else '33')
                values = read_env(ENV)
                if values:
                    health(int(values['GERSTEP_PORT']))
                    ui.say('Backend: responde. HTTPS: ' + ('válido' if tls.trusted(urlparse(values['GERSTEP_ORIGIN']).hostname) else 'falló'))
                    ui.say('URL: ' + values['GERSTEP_ORIGIN'] + '/Gerstep/')
            elif choice == '3': runner.run(['systemctl', 'restart', SERVICE]); ui.say('Servicio reiniciado.', '32')
            elif choice == '4':
                values = read_env(ENV)
                if not values: raise RuntimeError('Primero instalá Gerstep.')
                values['GERSTEP_ADMIN_PASSWORD_HASH'] = hash_password(ui.password())
                write_env(ENV, values)
                runner.run(['systemctl', 'restart', SERVICE])
                ui.say('Contraseña actualizada; sesiones administrativas anteriores cerradas.', '32')
            elif choice == '5': export_connection(ui)
            elif choice == '6':
                values = read_env(ENV)
                if not values: raise RuntimeError('Primero instalá Gerstep.')
                enabled = ui.yes('¿Habilitar lector de TikTok?', values.get('GERSTEP_COLLECT_TIKTOK') != '1')
                if enabled:
                    username = ui.ask('Usuario de TikTok', values.get('GERSTEP_TIKTOK_USERNAME', 'gerstep_official')).lstrip('@')
                    if not re.fullmatch(r'[A-Za-z0-9_.]{2,50}', username): raise ValueError('Usuario inválido.')
                    values['GERSTEP_TIKTOK_USERNAME'] = username
                    with ui.step('Instalar dependencias opcionales de TikTok'):
                        runner.run([APP / '.venv/bin/python', '-m', 'pip', 'install', '-r', APP / 'backend/requirements-collector.txt'])
                values['GERSTEP_COLLECT_TIKTOK'] = '1' if enabled else '0'
                write_env(ENV, values)
                runner.run(['systemctl', 'restart', SERVICE])
            elif choice == '7': ui.say(runner.capture(['journalctl', '-u', SERVICE, '--no-pager', '-n', '40']))
            elif choice == '8': backup(ui)
            elif choice == '9':
                import getpass
                values = read_env(ENV)
                if not values: raise ValueError('Instalá Gerstep primero.')
                ui.say('La clave se guarda en el entorno privado del servicio. Nunca se envía al navegador.')
                secret = getpass.getpass('API key NVIDIA (vacío conserva la actual): ').strip()
                if secret:
                    if len(secret)>512 or not secret.isascii() or any(c.isspace() for c in secret):
                        raise ValueError('Formato de clave inválido.')
                    values['NVIDIA_API_KEY'] = secret
                values['GERSTEP_AI_ENABLED'] = 'true' if ui.yes('Habilitar pruebas IA privadas',True) else 'false'
                values.setdefault('GERSTEP_AI_REQUESTS_PER_MINUTE','6')
                values.setdefault('GERSTEP_AI_RESERVED_REQUESTS','0')
                ui.say('La skill completa usa aproximadamente 10–11 mil tokens estimados de contexto por consulta. El uso real lo informa NVIDIA.')
                context=int(ui.ask('Presupuesto total de contexto IA (16000–24000)',str(max(16000,int(values.get('GERSTEP_AI_CONTEXT_TOKENS','16000'))))))
                tokens=int(ui.ask('Presupuesto operativo de tokens/minuto (12000–100000)',str(max(60000,int(values.get('GERSTEP_AI_TOKENS_PER_MINUTE','60000'))))))
                if not 16000<=context<=24000 or not 12000<=tokens<=100000:
                    raise ValueError('Presupuesto fuera del rango. No se guardaron cambios.')
                values['GERSTEP_AI_CONTEXT_TOKENS']=str(context)
                values['GERSTEP_AI_TOKENS_PER_MINUTE']=str(tokens)
                write_env(ENV,values)
                runner.run(['systemctl','restart',SERVICE])
                ui.say('IA privada configurada. Abrí la pestaña IA del administrador.','32')
            else: ui.say('Elegí una opción del menú.', '33')
        except (KeyboardInterrupt, EOFError):
            ui.say('\nOperación cancelada.'); return
        except Exception as exc: ui.say(str(exc), '31')
        ui.ask('Enter para volver al menú')


if __name__ == '__main__': main()
