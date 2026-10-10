from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    origin: str
    secret: str
    bridge_token: str
    admin_token: str
    database: str = 'data/interactive.sqlite3'
    prefix: str = '/Gerstep'
    development: bool = False
    frontend: Path = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'

    def __post_init__(self):
        parsed = urlparse(self.origin)
        if not parsed.hostname: raise ValueError('Origin requires a valid host.')
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Origin must contain only scheme and host.')
        if parsed.scheme != 'https' and not (self.development and parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}):
            raise ValueError('HTTPS is required outside local development.')
        if any(len(value) < 32 for value in (self.secret, self.bridge_token, self.admin_token)):
            raise ValueError('Configure three independent secrets of at least 32 characters.')
        if len({self.secret, self.bridge_token, self.admin_token}) != 3:
            raise ValueError('Admin, signing and bridge secrets must be different.')
        if self.prefix != '/Gerstep':
            raise ValueError('This installation uses the /Gerstep path.')

    @classmethod
    def from_env(cls):
        return cls(origin=os.environ.get('GERSTEP_ORIGIN', 'https://167.86.106.105'),
                   secret=os.environ.get('GERSTEP_SESSION_SECRET', ''), bridge_token=os.environ.get('GERSTEP_BRIDGE_TOKEN', ''),
                   admin_token=os.environ.get('GERSTEP_ADMIN_TOKEN', ''), database=os.environ.get('GERSTEP_DB', 'data/interactive.sqlite3'),
                   development=os.environ.get('GERSTEP_DEVELOPMENT') == '1')
