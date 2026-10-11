"""Keep a recoverable copy of application code; SQLite and venv are untouched."""
from pathlib import Path
import shutil


class CodeBackup:
    def __init__(self, app, backup):
        self.app, self.backup, self.saved = Path(app), Path(backup), []

    def save(self):
        for name in ('backend', 'deploy', 'frontend', 'ai_common'):
            if (self.app / name).is_dir():
                shutil.copytree(self.app / name, self.backup / name,
                    ignore=shutil.ignore_patterns('node_modules', '__pycache__', '.env', '.git', 'data'))
                self.saved.append(name)

    def restore(self):
        for name in self.saved:
            shutil.copytree(self.backup / name, self.app / name, dirs_exist_ok=True)
