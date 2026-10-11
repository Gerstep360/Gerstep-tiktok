import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3


class Database:
    """One SQLite owner thread and at most 64 outstanding operations."""
    def __init__(self, path):
        self.path = path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='interactive-sqlite')
        self.connection = None
        self.pending = 0

    def _open(self):
        if self.path != ':memory:': Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=2)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, owner TEXT, nickname TEXT, kind TEXT, text TEXT,
                status TEXT, created REAL, expires REAL, response TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS request_expiry ON requests(expires);
            CREATE TABLE IF NOT EXISTS supports(request_id TEXT REFERENCES requests(id) ON DELETE CASCADE, owner TEXT,
                PRIMARY KEY(request_id,owner));
            CREATE TABLE IF NOT EXISTS polls(id TEXT PRIMARY KEY, title TEXT, options TEXT, closes REAL, active INTEGER);
            CREATE TABLE IF NOT EXISTS votes(poll_id TEXT REFERENCES polls(id) ON DELETE CASCADE, owner TEXT, choice INTEGER,
                PRIMARY KEY(poll_id,owner));
            CREATE TABLE IF NOT EXISTS gifts(event_id TEXT PRIMARY KEY, created REAL);
            CREATE TABLE IF NOT EXISTS donors(owner TEXT PRIMARY KEY, nickname TEXT, coins INTEGER, seen REAL);
            CREATE TABLE IF NOT EXISTS stream_donors(owner TEXT, stream TEXT, coins INTEGER, seen REAL, PRIMARY KEY(owner,stream));
            CREATE TABLE IF NOT EXISTS blocks(owner TEXT PRIMARY KEY, expires REAL);
            CREATE TABLE IF NOT EXISTS markers(id TEXT PRIMARY KEY, label TEXT, created REAL, offset REAL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS identities(number INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT UNIQUE,
                token_hash TEXT UNIQUE, nickname TEXT, created REAL, seen REAL);
            CREATE TABLE IF NOT EXISTS chat_profiles(owner TEXT PRIMARY KEY, nickname TEXT, xp INTEGER, level INTEGER,
                rank TEXT, seen REAL);
            CREATE INDEX IF NOT EXISTS donor_coins ON donors(coins DESC);
            CREATE INDEX IF NOT EXISTS stream_coins ON stream_donors(stream,coins DESC);
            CREATE INDEX IF NOT EXISTS chat_xp ON chat_profiles(xp DESC);
            CREATE TABLE IF NOT EXISTS collector_activity(owner TEXT PRIMARY KEY,last_comment REAL,seen REAL);
        ''')
        for table in ('votes', 'supports', 'requests'):
            if 'ip' not in {row[1] for row in self.connection.execute(f'PRAGMA table_info({table})')}:
                self.connection.execute(f'ALTER TABLE {table} ADD COLUMN ip TEXT')
        self.connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS vote_ip ON votes(poll_id,ip) WHERE ip IS NOT NULL')
        self.connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS support_ip ON supports(request_id,ip) WHERE ip IS NOT NULL')
        columns={row[1] for row in self.connection.execute('PRAGMA table_info(votes)')}
        for column,definition in (('nickname',"TEXT DEFAULT ''"),('source',"TEXT DEFAULT ''"),('created','REAL DEFAULT 0')):
            if column not in columns: self.connection.execute(f'ALTER TABLE votes ADD COLUMN {column} {definition}')
        self.connection.commit()

    async def start(self):
        await asyncio.get_running_loop().run_in_executor(self.executor, self._open)

    async def call(self, operation, *args):
        if self.pending >= 64: raise ValueError('El servidor está ocupado. Reintentá en un momento.')
        self.pending += 1
        def run():
            with self.connection: return operation(self.connection, *args)
        try:
            return await asyncio.get_running_loop().run_in_executor(self.executor, run)
        finally:
            self.pending -= 1

    async def close(self):
        if self.connection:
            await asyncio.get_running_loop().run_in_executor(self.executor, self.connection.close)
        self.executor.shutdown(wait=True)
