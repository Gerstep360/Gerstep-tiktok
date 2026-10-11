"""Update only the standalone source checkout; runtime data live elsewhere."""
from pathlib import Path
import re
import shutil


def refresh(source, app, values, ui, runner):
    source, app = Path(source).resolve(), Path(app).resolve()
    if (source / '.git').exists():
        repo = source
    elif values.get('GERSTEP_SOURCE_REPO'):
        repo = Path(values['GERSTEP_SOURCE_REPO']).resolve()
    else:
        ui.say('Sin copia Git registrada. Se instalará el código disponible; para actualizar, ejecutá el menú desde el repositorio clonado.', '33')
        return None
    if repo == app or repo.is_relative_to(app):
        raise RuntimeError('La copia Git debe estar fuera de /opt/gerstep-interactive, donde están los datos del servicio.')
    if not (repo / '.git').exists() or not (repo / 'backend/server.py').is_file() or not (repo / 'frontend/package.json').is_file():
        raise RuntimeError('No se encontró el repositorio independiente de Gerstep. Ejecutá ./install desde la copia clonada.')
    if not shutil.which('git'):
        with ui.step('Preparar Git'):
            if shutil.which('apt-get'):
                runner.run(['apt-get', 'update'])
                runner.run(['apt-get', 'install', '--no-upgrade', '-y', 'git'])
            elif shutil.which('dnf'):
                runner.run(['dnf', 'install', '-y', 'git'])
            else:
                raise RuntimeError('Instalá Git para actualizar el repositorio.')
    git = ['git', '-C', str(repo)]
    # Never let Git discover and reset a parent repository (e.g. desktop TikTok).
    actual = Path(runner.capture([*git, 'rev-parse', '--show-toplevel']).strip()).resolve()
    if actual != repo:
        raise RuntimeError('El repositorio Git detectado no coincide con la carpeta independiente de Gerstep.')
    ui.say('Actualización forzada desde origin/main: se sobrescriben los cambios locales versionados. Los datos y claves del servicio están fuera de esta copia.', '33')
    with ui.step('Descargar la última versión (git fetch)'):
        runner.run([*git, 'fetch', '--prune', 'origin', '+refs/heads/main:refs/remotes/origin/main'], timeout=120)
        commit = runner.capture([*git, 'rev-parse', '--verify', 'refs/remotes/origin/main^{commit}']).strip()
        if not re.fullmatch(r'[0-9a-f]{40,64}', commit):
            raise RuntimeError('Git no devolvió una versión válida. No se modificó la copia local.')
    with ui.step('Aplicar la versión descargada (git reset --hard)'):
        runner.run([*git, 'reset', '--hard', commit])
    ui.say('Versión descargada: ' + commit[:12] + '. Reiniciando el menú para instalar el código nuevo.', '32')
    return repo
