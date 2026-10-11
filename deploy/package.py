"""This packager belongs to the independent VPS repository."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'node_modules', '__pycache__', '.git', '.vite', 'data', 'release', '.venv', '.certbot', '.pytest_cache'}


def package(target=None):
    target = Path(target) if target else ROOT / 'release/gerstep-interactive.zip'
    if not (ROOT / 'frontend/dist/index.html').is_file(): raise RuntimeError('Compilá el frontend antes de empaquetar.')
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob('*')):
            relative = path.relative_to(ROOT)
            if any(part in IGNORED for part in relative.parts) or not path.is_file() or path.is_symlink(): continue
            if path.name.startswith('.env') and path.name != '.env.example': continue
            if path.suffix in {'.pyc', '.log', '.zip', '.sqlite3', '.db'} or '.sqlite3-' in path.name: continue
            name, data = relative.as_posix(), path.read_bytes()
            item = zipfile.ZipInfo(name)
            item.create_system = 3
            item.external_attr = (0o100755 if name == 'install' else 0o100644) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data)
            manifest[name] = hashlib.sha256(data).hexdigest()
        archive.writestr('MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(target) as archive:
        if archive.testzip(): raise RuntimeError('ZIP corrupto.')
    return {'archive': str(target), 'files': len(manifest), 'bytes': target.stat().st_size}


if __name__ == '__main__': print(json.dumps(package(), indent=2))
