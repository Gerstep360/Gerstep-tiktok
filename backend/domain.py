"""Moderated interactions, polls and donation statistics; never executes PC actions."""
from collections import deque
import json
import re
import secrets
import time

from .security import clean_text

COMMANDS = ('!bsod', '!error', '!windows', '!caos', '!gerstep', '!help')
FEATURES = ('question', 'proposal', 'command', 'music', 'poll')


class Domain:
    def __init__(self, security):
        self.security = security
        self.features = dict.fromkeys(FEATURES, True)
        self.features['music'] = False
        self.suspended = False
        self.cooldown = 20
        self.max_length = 1200
        self.live = {'connected': False, 'username': 'gerstep_official', 'stream_id': '', 'started_at': None, 'stats': {}}
        self.chat = deque(maxlen=40)
        self.active = None
        self.wheel = None
        self._poll_cache = None
        self._poll_dirty = True
        self._voter_cache = []

    def load(self, db):
        row = db.execute("SELECT value FROM settings WHERE key='preferences'").fetchone()
        if row:
            values = json.loads(row['value'])
            self.features.update(values['features'])
            self.suspended, self.cooldown, self.max_length = values['suspended'], values['cooldown'], values['max_length']
        self.maintain(db)

    def allowed(self, db, owner):
        if self.suspended: raise ValueError('Las interacciones están en pausa.')
        if db.execute('SELECT 1 FROM blocks WHERE owner=? AND expires>?', (owner, time.time())).fetchone():
            raise ValueError('Esta sesión está bloqueada.')

    def submit(self, db, owner, nickname, payload, ip=None):
        self.allowed(db, owner)
        if ip: self.allowed(db, ip)
        kind = payload.get('kind', 'question')
        if kind not in FEATURES or kind == 'poll' or not self.features[kind]:
            raise ValueError('Esa interacción no está disponible.')
        text = clean_text(payload.get('text'), self.max_length if kind == 'question' else 800, minimum=3)
        if re.search(r'(.)\1{14,}', text): raise ValueError('Evitá mensajes repetitivos.')
        if kind == 'command' and text not in COMMANDS: raise ValueError('Comando no permitido.')
        if kind == 'music':
            from .validation import youtube_id
            if not youtube_id(text): raise ValueError('Usá un enlace https válido de YouTube.')
        now = time.time()
        self.maintain(db)
        if db.execute("SELECT COUNT(*) FROM requests WHERE status IN ('pending','approved','selected')").fetchone()[0] >= 200:
            raise ValueError('La cola está llena. Probá más tarde.')
        rows = db.execute("SELECT text,created FROM requests WHERE owner=? OR ip=? ORDER BY created DESC LIMIT 5", (owner, ip)).fetchall()
        if rows and now - rows[0]['created'] < self.cooldown: raise ValueError('Esperá antes de enviar otra interacción.')
        if any(row['text'].casefold() == text.casefold() for row in rows): raise ValueError('Esa propuesta ya está en la cola.')
        if db.execute("SELECT COUNT(*) FROM requests WHERE (owner=? OR ip=?) AND status='pending'", (owner, ip)).fetchone()[0] >= 3:
            raise ValueError('Ya tenés tres mensajes pendientes.')
        identifier = secrets.token_hex(12)
        db.execute('INSERT INTO requests(id,owner,nickname,kind,text,status,created,expires,ip) VALUES (?,?,?,?,?,?,?,?,?)',
                   (identifier, owner, clean_text(nickname, 32), kind, text, 'pending', now, now + 86400, ip))
        return {'id': identifier}

    def support(self, db, owner, identifier, ip=None):
        self.allowed(db, owner)
        if ip: self.allowed(db, ip)
        row = db.execute("SELECT id FROM requests WHERE id=? AND status IN ('approved','selected') AND expires>?", (identifier, time.time())).fetchone()
        if not row: raise ValueError('La pregunta ya no está disponible.')
        if db.execute('SELECT COUNT(*) FROM supports WHERE request_id=?', (identifier,)).fetchone()[0] >= 2000:
            raise ValueError('Esta pregunta llegó al límite de apoyos.')
        db.execute('INSERT OR IGNORE INTO supports(request_id,owner,ip) VALUES (?,?,?)', (identifier, owner, ip))
        return {'ok': True}

    def vote(self, db, owner, choice, poll_id=None, ip=None, nickname=''):
        self.allowed(db, owner)
        if ip: self.allowed(db, ip)
        if not self.features['poll']: raise ValueError('Las encuestas están desactivadas.')
        poll = db.execute('SELECT * FROM polls WHERE active=1 AND closes>? ORDER BY closes DESC LIMIT 1', (time.time(),)).fetchone()
        if not poll or (poll_id is not None and poll_id != poll['id']): raise ValueError('No hay una encuesta activa para ese voto.')
        if type(choice) is not int or not 1 <= choice <= len(json.loads(poll['options'])):
            raise ValueError('Elegí un número de opción válido.')
        if db.execute('SELECT COUNT(*) FROM votes WHERE poll_id=?', (poll['id'],)).fetchone()[0] >= 50000:
            raise ValueError('La encuesta alcanzó su capacidad.')
        previous = db.execute('SELECT owner FROM votes WHERE poll_id=? AND ip=?', (poll['id'], ip)).fetchone() if ip else None
        if previous and previous['owner'] != owner:
            raise ValueError('Esta IP ya tiene un voto registrado en la encuesta.')
        db.execute('INSERT INTO votes(poll_id,owner,choice,ip,nickname,source,created) VALUES (?,?,?,?,?,?,?) ON CONFLICT(poll_id,owner) DO UPDATE SET choice=excluded.choice,nickname=excluded.nickname,created=excluded.created,ip=COALESCE(votes.ip,excluded.ip)',
                   (poll['id'], owner, choice, ip, str(nickname)[:32], 'web' if ip else 'tiktok', time.time()))
        self._poll_dirty = True
        return {'ok': True, 'poll_id': poll['id']}

    def moderate(self, db, action, payload):
        now = time.time()
        if action == 'preferences':
            flags = payload.get('features', {})
            if not isinstance(flags, dict) or any(k not in FEATURES or type(v) is not bool for k, v in flags.items()): raise ValueError('Funciones inválidas.')
            suspended = payload.get('suspended', self.suspended)
            cooldown, length = payload.get('cooldown', self.cooldown), payload.get('max_length', self.max_length)
            if type(suspended) is not bool or type(cooldown) is not int or not 10 <= cooldown <= 120 or type(length) is not int or not 200 <= length <= 2000:
                raise ValueError('Límites inválidos.')
            self.features.update(flags)
            self.suspended, self.cooldown, self.max_length = suspended, cooldown, length
            db.execute("INSERT INTO settings VALUES ('preferences',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps({'features': self.features, 'suspended': suspended, 'cooldown': cooldown, 'max_length': length}),))
            return {'ok': True}
        if action == 'clear':
            db.execute('DELETE FROM requests')
            self.active = self.wheel = None
            return {'ok': True}
        if action == 'hide':
            self.active = None
            return {'ok': True}
        if action == 'block':
            row = db.execute('SELECT owner,ip FROM requests WHERE id=?', (payload.get('id'),)).fetchone()
            if not row: raise ValueError('Mensaje no encontrado.')
            db.execute('INSERT INTO blocks VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET expires=excluded.expires', (row['owner'], now + 86400))
            if row['ip']:
                db.execute('INSERT INTO blocks VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET expires=excluded.expires', (row['ip'], now + 86400))
            db.execute("UPDATE requests SET status='rejected' WHERE owner=? AND status IN ('pending','approved')", (row['owner'],))
            if self.active and self.active['owner'] == row['owner']: self.active = None
            return {'ok': True}
        if action == 'poll_create':
            title = clean_text(payload.get('title'), 160, minimum=3)
            options = payload.get('options')
            duration = payload.get('duration', 120)
            if not isinstance(options, list) or not 2 <= len(options) <= 6 or type(duration) is not int or not 30 <= duration <= 3600:
                raise ValueError('Usá 2–6 opciones y una duración de 30–3600 segundos.')
            options = [clean_text(option, 80) for option in options]
            if len(set(option.casefold() for option in options)) != len(options): raise ValueError('Las opciones deben ser diferentes.')
            db.execute('UPDATE polls SET active=0')
            identifier = secrets.token_hex(12)
            db.execute('INSERT INTO polls VALUES (?,?,?,?,1)', (identifier, title, json.dumps(options), now + duration))
            self._poll_dirty = True
            return {'ok': True}
        if action == 'poll_close':
            db.execute('UPDATE polls SET active=0')
            self._poll_dirty = True
            return {'ok': True}
        if action == 'roulette':
            candidates = [dict(row) for row in db.execute("SELECT id,nickname,text FROM requests WHERE status='approved' AND kind='question' AND expires>? LIMIT 30", (now,))]
            if len(candidates) < 2: raise ValueError('Aprobá al menos dos preguntas para la ruleta.')
            selected = secrets.choice(candidates)
            self.wheel = {'id': secrets.token_hex(8), 'candidates': candidates, 'selected': selected['id'], 'expires': now + 45}
            # A draw highlights the selected question in the moderation panel, never speaks it.
            return {'ok': True, 'selected': selected['id']}
        if action == 'marker':
            label = clean_text(payload.get('label', 'Momento del directo'), 120)
            start = self.live.get('started_at')
            offset = max(0, now - start) if isinstance(start, (int, float)) else None
            db.execute('INSERT INTO markers VALUES (?,?,?,?)', (secrets.token_hex(12), label, now, offset))
            return {'ok': True}
        if action not in {'approve', 'reject', 'highlight', 'personal', 'bot', 'answered', 'ack'}:
            raise ValueError('Acción administrativa no permitida.')
        row = db.execute('SELECT * FROM requests WHERE id=? AND expires>?', (payload.get('id'), now)).fetchone()
        if not row: raise ValueError('El mensaje no existe o venció.')
        if action == 'ack':
            status = payload.get('status')
            if status not in {'answered', 'error', 'selected'} or row['status'] != 'selected': return {'ok': True}
        else:
            if row['status'] in {'rejected', 'answered', 'error'} and action not in {'reject', 'answered'}:
                raise ValueError('El mensaje ya fue cerrado.')
            status = {'approve': 'approved', 'reject': 'rejected', 'highlight': 'selected', 'personal': 'selected', 'bot': 'selected', 'answered': 'answered'}[action]
        response = clean_text(payload['response'], 220) if payload.get('response') else ''
        db.execute('UPDATE requests SET status=?,response=? WHERE id=?', (status, response, row['id']))
        if action in {'highlight', 'personal', 'bot'}:
            self.active = {**dict(row), 'status': 'selected', 'expires': now + 90}
        elif self.active and self.active['id'] == row['id']:
            self.active['status'] = status
        return {'ok': True, 'request': {**dict(row), 'status': status, 'response': response}}

    def ingest(self, db, events):
        for event in events[:50]:
            kind = event.get('kind')
            if kind == 'state':
                payload = event.get('state', {})
                self.live = {'connected': payload.get('connected') is True, 'username': str(payload.get('username', 'gerstep_official'))[:50],
                             'stream_id': str(payload.get('stream_id', ''))[:64], 'started_at': payload.get('started_at'),
                             'stats': {key: min(10**12, max(0, int(value))) for key, value in payload.get('stats', {}).items() if key in {'coins','gifts','likes','comments','viewers'} and type(value) is int},
                             'emergency': payload.get('emergency') is True, 'music_enabled': payload.get('music_enabled') is True}
            elif kind == 'profiles':
                rows = event.get('profiles')
                if not isinstance(rows, list) or len(rows) > 50: continue
                for row in rows:
                    if not isinstance(row, dict): continue
                    stable = str(row.get('user_id', ''))[:32]
                    if not stable.isdecimal() or int(stable) <= 0: continue
                    if any(type(row.get(key)) is not int or not 0 <= row[key] <= 10**12 for key in ('xp', 'level')): continue
                    owner = self.security.digest('tiktok:' + stable)
                    db.execute('INSERT INTO chat_profiles(owner,nickname,xp,level,rank,seen) VALUES (?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET nickname=excluded.nickname,xp=MAX(xp,excluded.xp),level=CASE WHEN excluded.xp>=xp THEN excluded.level ELSE level END,rank=CASE WHEN excluded.xp>=xp THEN excluded.rank ELSE rank END,seen=excluded.seen',
                               (owner, str(row.get('nickname', 'Espectador'))[:80], row['xp'], row['level'], str(row.get('rank', ''))[:80], time.time()))
            elif kind in {'comment', 'gift'}:
                metadata = event.get('metadata', {})
                stable = str(metadata.get('user_id', ''))[:32]
                nick = str(metadata.get('nickname') or event.get('user') or 'Espectador')[:32]
                if kind == 'comment':
                    text = str(event.get('message', ''))[:2000]
                    self.chat.append({'nickname': nick, 'text': text[:350], 'created': time.time()})
                    owner = self.security.digest('tiktok:' + stable)
                    if stable.isdecimal() and int(stable) > 0:
                        if event.get('_collector_profile') is True:
                            from .profiles import award
                            award(db, owner, nick, 'comment')
                        match = re.fullmatch(r'/encuesta\s+([1-6])', text.strip(), re.I)
                        try:
                            if match and self.security.allow(('chat-vote', owner), period=3): self.vote(db, owner, int(match[1]),nickname=nick)
                            elif text.startswith(('/pregunta ', '/propuesta ')) and self.security.allow(('chat-request', owner), period=self.cooldown):
                                command, body = text.split(' ', 1)
                                self.submit(db, owner, nick, {'kind': 'question' if command == '/pregunta' else 'proposal', 'text': body})
                        except ValueError: pass
                elif stable.isdecimal() and int(stable) > 0:
                    mid = str(metadata.get('event_id', ''))[:80]
                    coins = event.get('coins', 0)
                    if not mid or type(coins) is not int or not 0 < coins <= 1000000: continue
                    if not db.execute('INSERT OR IGNORE INTO gifts VALUES (?,?)', (self.security.digest(mid), time.time())).rowcount: continue
                    owner = self.security.digest('tiktok:' + stable)
                    if event.get('_collector_profile') is True:
                        from .profiles import award
                        award(db, owner, nick, 'gift', coins)
                    db.execute('INSERT INTO donors VALUES (?,?,?,?) ON CONFLICT(owner) DO UPDATE SET coins=coins+excluded.coins,nickname=excluded.nickname,seen=excluded.seen', (owner, nick, coins, time.time()))
                    db.execute('INSERT INTO stream_donors VALUES (?,?,?,?) ON CONFLICT(owner,stream) DO UPDATE SET coins=coins+excluded.coins,seen=excluded.seen', (owner, self.live['stream_id'], coins, time.time()))
        return {'ok': True}

    def maintain(self, db):
        now = time.time()
        db.execute('DELETE FROM requests WHERE expires<?', (now,))
        db.execute("DELETE FROM requests WHERE status NOT IN ('pending','approved','selected') AND id IN (SELECT id FROM requests ORDER BY created DESC LIMIT -1 OFFSET 2000)")
        deleted=db.execute('DELETE FROM polls WHERE closes<?', (now - 86400,)).rowcount
        deleted+=db.execute('DELETE FROM polls WHERE id IN (SELECT id FROM polls ORDER BY closes DESC LIMIT -1 OFFSET 100)').rowcount
        if deleted: self._poll_dirty = True
        if db.execute('UPDATE polls SET active=0 WHERE active=1 AND closes<?', (now,)).rowcount:
            self._poll_dirty = True
        db.execute('DELETE FROM blocks WHERE expires<?', (now,))
        db.execute('DELETE FROM identities WHERE seen<?', (now - 30 * 86400,))
        db.execute('DELETE FROM chat_profiles WHERE seen<?', (now - 30 * 86400,))
        db.execute('DELETE FROM collector_activity WHERE seen<?', (now - 30 * 86400,))
        db.execute('DELETE FROM markers WHERE created<?', (now - 7 * 86400,))
        db.execute('DELETE FROM markers WHERE id IN (SELECT id FROM markers ORDER BY created DESC LIMIT -1 OFFSET 500)')
        db.execute('DELETE FROM donors WHERE seen<?', (now - 30 * 86400,))
        db.execute('DELETE FROM stream_donors WHERE seen<?', (now - 30 * 86400,))
        db.execute('DELETE FROM gifts WHERE created<?', (now - 30 * 86400,))
        db.execute('DELETE FROM gifts WHERE event_id IN (SELECT event_id FROM gifts ORDER BY created DESC LIMIT -1 OFFSET 50000)')
        if self.active and self.active['expires'] < now: self.active = None
        if self.wheel and self.wheel['expires'] < now: self.wheel = None

    def snapshot(self, db):
        requests = [{k: v for k,v in dict(row).items() if k != 'ip'} for row in db.execute("SELECT requests.*,COUNT(supports.owner) AS supports FROM requests LEFT JOIN supports ON supports.request_id=requests.id GROUP BY requests.id ORDER BY CASE WHEN requests.status IN ('pending','approved','selected') THEN 0 ELSE 1 END,requests.created DESC LIMIT 200")]
        if self._poll_dirty:
            self._poll_cache = self._poll_snapshot(db)
            poll_id=self._poll_cache['id'] if self._poll_cache else ''
            self._voter_cache = self.voters(db,poll_id,limit=200,descending=True)
            self._poll_dirty = False
        poll_state = self._poll_cache
        global_donors = [dict(row) for row in db.execute('SELECT nickname,coins FROM donors ORDER BY coins DESC LIMIT 10')]
        stream_donors = [dict(row) for row in db.execute('SELECT donors.nickname,stream_donors.coins FROM stream_donors JOIN donors USING(owner) WHERE stream=? ORDER BY stream_donors.coins DESC LIMIT 10', (self.live['stream_id'],))]
        return {'live': self.live.copy(), 'requests': requests, 'features': self.features.copy(), 'suspended': self.suspended,
                'cooldown': self.cooldown, 'max_length': self.max_length, 'poll': poll_state, 'active': self.active.copy() if self.active else None,
                'wheel': self.wheel, 'donors': {'stream': stream_donors, 'global': global_donors}, 'commands': list(COMMANDS),
                'levels': [dict(row) for row in db.execute('SELECT nickname,xp,level,rank FROM chat_profiles ORDER BY xp DESC,owner LIMIT 10')],
                'voters': self._voter_cache,
                'chat': list(self.chat), 'markers': [dict(row) for row in db.execute('SELECT * FROM markers ORDER BY created DESC LIMIT 500')]}

    @staticmethod
    def _poll_snapshot(db):
        poll = db.execute('SELECT * FROM polls ORDER BY closes DESC LIMIT 1').fetchone()
        poll_state = None
        if poll:
            counts = dict(db.execute('SELECT choice,COUNT(*) FROM votes WHERE poll_id=? GROUP BY choice', (poll['id'],)).fetchall())
            options = [{'number': i+1, 'label': label, 'votes': counts.get(i+1, 0)} for i, label in enumerate(json.loads(poll['options']))]
            poll_state = {'id': poll['id'], 'title': poll['title'], 'options': options, 'closes': poll['closes'], 'active': bool(poll['active']), 'total': sum(option['votes'] for option in options)}
        return poll_state

    @staticmethod
    def voters(db,poll_id,*,after=0,limit=500,descending=False):
        order='DESC' if descending else 'ASC'
        rows=db.execute(f'''SELECT votes.rowid AS sequence,votes.owner AS participant_id,
            COALESCE(NULLIF(identities.nickname,''),NULLIF(chat_profiles.nickname,''),NULLIF(votes.nickname,''),'Anónimo') AS nickname,
            votes.choice,votes.source,votes.created FROM votes
            LEFT JOIN identities ON votes.owner=identities.owner LEFT JOIN chat_profiles ON votes.owner=chat_profiles.owner
            WHERE poll_id=? AND votes.rowid>? ORDER BY votes.rowid {order} LIMIT ?''',(poll_id,after,limit))
        return [dict(row) for row in rows]
