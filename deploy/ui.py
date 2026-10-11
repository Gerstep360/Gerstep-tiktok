"""TTY-only animation; no curses dependency or noisy animation in logs."""
from contextlib import contextmanager
import getpass
import os
import sys
import threading


class UI:
    def __init__(self): self.color = sys.stdout.isatty() and not os.environ.get('NO_COLOR')

    def say(self, text, color='36'):
        print(f'\033[{color}m{text}\033[0m' if self.color else text, flush=True)

    def banner(self):
        self.say('\n  ╭──────────────────────────────────────╮\n  │  GERSTEP / INTERACTIVE                │\n  │  Instalación y mantenimiento          │\n  ╰──────────────────────────────────────╯', '95')

    def ask(self, text, default=''):
        value = input(f'{text}' + (f' [{default}]' if default else '') + ': ').strip()
        return value or default

    def yes(self, text, default=False):
        return self.ask(text + ' (s/n)', 's' if default else 'n').lower() in {'s', 'si', 'sí', 'y', 'yes'}

    def password(self):
        while True:
            first = getpass.getpass('Contraseña del panel (12–256 caracteres): ')
            second = getpass.getpass('Repetir contraseña: ')
            if first == second and 12 <= len(first) <= 256: return first
            self.say('Las contraseñas deben coincidir y cumplir la longitud.', '33')

    @contextmanager
    def step(self, label):
        self.say('  → ' + label)
        stop = threading.Event()
        def animate():
            frames, index = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏', 0
            while not stop.wait(.12):
                sys.stdout.write('\r\033[36m  ' + frames[index % len(frames)] + ' ' + label + '\033[0m\033[K')
                sys.stdout.flush()
                index += 1
        worker = threading.Thread(target=animate, daemon=True) if self.color else None
        if worker: worker.start()
        try:
            yield
        except BaseException:
            stop.set()
            if worker: worker.join(); print('\r\033[K', end='')
            self.say('  ✕ ' + label, '31')
            raise
        else:
            stop.set()
            if worker: worker.join(); print('\r\033[K', end='')
            self.say('  ✓ ' + label, '32')
