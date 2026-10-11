"""Bounded subprocesses, atomic config writes and transactional rollback."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

MANAGED = '# Managed: Gerstep Interactive'


def atomic_write(path, data, mode=0o644, owner=None):
    path = Path(path)
    if owner is None and path.exists():
        info = path.stat()
        owner = info.st_uid, info.st_gid
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.gerstep-', dir=path.parent)
    try:
        os.fchmod(fd, mode) if hasattr(os, 'fchmod') else None
        with os.fdopen(fd, 'wb') as stream: stream.write(data.encode() if isinstance(data, str) else data)
        os.chmod(name, mode)
        if owner is not None and hasattr(os, 'chown'): os.chown(name, *owner)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def read_env(path):
    result = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key.startswith('GERSTEP_'): result[key] = value
    return result


def write_env(path, values):
    if any('\n' in value or '\r' in value for value in values.values()): raise ValueError('Configuración inválida.')
    atomic_write(path, ''.join(f'{key}={value}\n' for key, value in sorted(values.items())), 0o600)


def free_port(start=9081):
    for port in range(start, start + 50):
        with socket.socket() as listener:
            try: listener.bind(('127.0.0.1', port)); return port
            except OSError: pass
    raise RuntimeError('No hay un puerto local disponible para Gerstep.')


class Runner:
    def __init__(self, log):
        self.log = Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.log, '', 0o600)

    def run(self, args, *, timeout=600, cwd=None, check=True):
        # Never use a shell. Credentials are never supplied on subprocess command lines.
        with self.log.open('ab') as output:
            output.write(('\n[' + time.strftime('%H:%M:%S') + '] ' + str(args[0]) + '\n').encode())
            output.flush()
            process = subprocess.Popen([str(arg) for arg in args], cwd=cwd, stdout=output, stderr=output, stdin=subprocess.DEVNULL,
                                       env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'}, start_new_session=os.name != 'nt')
            try: code = process.wait(timeout=timeout)
            except BaseException:
                if os.name != 'nt':
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                else: process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    else: process.kill()
                    process.wait()
                raise
        if code and check: raise RuntimeError(f'{Path(str(args[0])).name} falló. Registro privado: {self.log}')
        return code

    def capture(self, args, timeout=30):
        value = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, timeout=timeout)
        if value.returncode: raise RuntimeError(f'{args[0]} falló; revisá su configuración antes de continuar.')
        return value.stdout or value.stderr


class Transaction:
    def __init__(self, backup):
        self.originals, self.backup = {}, Path(backup)

    def write(self, path, data, mode=None, *, managed=False):
        path = Path(path)
        if managed and path.exists() and not path.read_text().startswith(MANAGED):
            raise RuntimeError(f'El archivo {path} pertenece a otra aplicación.')
        if path not in self.originals:
            info = path.stat() if path.exists() else None
            original = (path.read_bytes(), info.st_mode & 0o777, info.st_uid, info.st_gid) if info else None
            self.originals[path] = original
            if original:
                target = self.backup / str(path).replace(':', '').lstrip('/\\')
                atomic_write(target, original[0], 0o600)
        original = self.originals[path]
        atomic_write(path, data, mode if mode is not None else original[1] if original else 0o644)

    def rollback(self):
        for path, original in reversed(list(self.originals.items())):
            if original: atomic_write(path, original[0], original[1], (original[2], original[3]))
            elif path.exists(): path.unlink()

    def is_restored(self):
        return all((not path.exists() if original is None else path.is_file() and path.read_bytes() == original[0])
                   for path, original in self.originals.items())

    @contextmanager
    def guard(self):
        try: yield self
        except BaseException:
            self.rollback()
            raise


def packages(runner):
    missing = []
    if not shutil.which('nginx'): missing.append('nginx')
    venv_missing = runner.run([sys.executable, '-c', 'import venv, ensurepip'], check=False) != 0
    if shutil.which('apt-get'):
        if venv_missing: missing.append('python3-venv')
        if not Path('/etc/ssl/certs/ca-certificates.crt').is_file(): missing.append('ca-certificates')
        if missing:
            runner.run(['apt-get', 'update'])
            runner.run(['apt-get', 'install', '--no-upgrade', '-y', *missing])
    elif shutil.which('dnf'):
        if venv_missing: missing.append('python3-pip')
        if not Path('/etc/pki/tls/certs/ca-bundle.crt').is_file(): missing.append('ca-certificates')
        if missing: runner.run(['dnf', 'install', '-y', *missing])
    else: raise RuntimeError('Instalación automática disponible para Debian/Ubuntu y sistemas con dnf.')
