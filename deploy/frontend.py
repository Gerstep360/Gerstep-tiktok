"""Use bundled React, or build with a checksum-verified official Node LTS."""
import hashlib
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile
from urllib.request import urlopen


def download(url, target, maximum):
    with urlopen(url, timeout=30) as response, Path(target).open('wb') as output:
        total = 0
        while chunk := response.read(65536):
            total += len(chunk)
            if total > maximum: raise RuntimeError('Descarga mayor que el límite permitido.')
            output.write(chunk)


def ensure_frontend(source, runner, ui):
    frontend = Path(source) / 'frontend'
    if (frontend / 'dist/index.html').is_file(): return
    arch = {'x86_64': 'x64', 'aarch64': 'arm64'}.get(platform.machine())
    if not arch: raise RuntimeError('Esta CPU requiere subir frontend/dist precompilado.')
    with ui.step('Construir React (Node solo se utiliza para compilar)'):
        with tempfile.TemporaryDirectory(prefix='gerstep-node-') as temporary:
            temp = Path(temporary)
            download('https://nodejs.org/dist/index.json', temp / 'index.json', 2_000_000)
            versions = json.loads((temp / 'index.json').read_text())
            version = next(v['version'] for v in versions if v['lts'] and int(v['version'][1:].split('.')[0]) >= 22 and f'linux-{arch}' in v['files'])
            name = f'node-{version}-linux-{arch}.tar.xz'
            base = f'https://nodejs.org/dist/{version}/'
            download(base + 'SHASUMS256.txt', temp / 'checksums', 100_000)
            expected = next(line.split()[0] for line in (temp / 'checksums').read_text().splitlines() if line.split()[-1] == name)
            download(base + name, temp / name, 100_000_000)
            actual = hashlib.sha256((temp / name).read_bytes()).hexdigest()
            if actual != expected: raise RuntimeError('La descarga de Node no coincide con su checksum oficial.')
            with tarfile.open(temp / name) as archive:
                for member in archive.getmembers():
                    destination = (temp / member.name).resolve()
                    if not destination.is_relative_to(temp) or member.isdev() or member.isfifo(): raise RuntimeError('Archivo Node inseguro.')
                    if member.issym() and not (destination.parent / member.linkname).resolve().is_relative_to(temp): raise RuntimeError('Enlace Node inseguro.')
                    if member.islnk() and not (temp / member.linkname).resolve().is_relative_to(temp): raise RuntimeError('Enlace Node inseguro.')
                archive.extractall(temp)
            node = temp / name.removesuffix('.tar.xz') / 'bin/node'
            npm = node.parent / '../lib/node_modules/npm/bin/npm-cli.js'
            original = os.environ.get('PATH', '')
            os.environ['PATH'] = str(node.parent) + os.pathsep + original
            try:
                runner.run([node, npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=frontend)
                runner.run([node, npm, 'run', 'build'], cwd=frontend)
            finally: os.environ['PATH'] = original
