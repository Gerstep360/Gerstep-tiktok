"""Server-issued browser identities, independent of display names and TikTok IDs."""
import secrets
import time

from .security import clean_text


def session(db, security, values, previous, ip):
    now = time.time()
    row = None
    token = values.get('token')
    if token is not None:
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise ValueError('Token de visitante inválido.')
        row = db.execute('SELECT * FROM identities WHERE token_hash=? AND seen>?',
                         (security.digest(token), now - 30 * 86400)).fetchone()
        if not row:
            raise ValueError('La identidad venció. Creá una sesión nueva.')
    elif previous:
        row = db.execute('SELECT * FROM identities WHERE owner=? AND seen>?',
                         (previous['id'], now - 30 * 86400)).fetchone()
    nickname = values.get('nickname')
    if nickname is not None and nickname != '':
        nickname = clean_text(nickname, 24, minimum=2)
        if nickname.casefold().startswith(('anónimo', 'anonimo')):
            raise ValueError('Ese nombre está reservado para identidades anónimas.')
    if not row:
        if not security.allow(('new-identity', ip), limit=10, period=3600):
            raise ValueError('Esta IP alcanzó el límite de nuevas identidades. Volvé con tu token anterior.')
        if db.execute('SELECT COUNT(*) FROM identities').fetchone()[0] >= 100000:
            raise ValueError('No se pueden crear más sesiones ahora.')
        owner, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        cursor = db.execute('INSERT INTO identities(owner,token_hash,nickname,created,seen) VALUES (?,?,?,?,?)',
                            (owner, security.digest(token), '', now, now))
        number = cursor.lastrowid
        name = nickname or f'Anónimo[{number}]'
    else:
        owner, number = row['owner'], row['number']
        name = row['nickname'] if nickname is None else nickname or f'Anónimo[{number}]'
        if token is None:
            token = secrets.token_urlsafe(32)
            db.execute('UPDATE identities SET token_hash=? WHERE owner=?', (security.digest(token), owner))
    db.execute('UPDATE identities SET nickname=?,seen=? WHERE owner=?', (name, now, owner))
    return {'id': owner, 'nickname': name, 'token': token, 'number': number}
