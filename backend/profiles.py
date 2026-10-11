"""Local levels share the existing SQLite worker."""
import time

RANKS = ((0, 'Y este random'), (5, 'Mucho Texto'), (15, 'Insoportable'),
         (35, 'Desempleado Promedio'), (70, 'Donador de Tiempo'), (120, 'Agarra la pala'))


def award(db, owner, nickname, kind, coins=0):
    now = time.time()
    row = db.execute('''SELECT chat_profiles.xp,COALESCE(collector_activity.last_comment,0) AS last_comment
        FROM chat_profiles LEFT JOIN collector_activity USING(owner) WHERE owner=?''', (owner,)).fetchone()
    xp, last = (row['xp'], row['last_comment']) if row else (0, 0)
    if kind == 'comment':
        if now - last >= 30: xp, last = xp + 1, now
    elif kind == 'gift': xp += min(50, max(0, coins) * 3)
    level = max(i for i, (threshold, _) in enumerate(RANKS) if xp >= threshold) + 1
    db.execute('''INSERT INTO chat_profiles(owner,nickname,xp,level,rank,seen) VALUES (?,?,?,?,?,?)
        ON CONFLICT(owner) DO UPDATE SET nickname=excluded.nickname,xp=excluded.xp,level=excluded.level,
        rank=excluded.rank,seen=excluded.seen''', (owner, nickname, xp, level, RANKS[level - 1][1], now))
    db.execute('''INSERT INTO collector_activity VALUES (?,?,?) ON CONFLICT(owner)
        DO UPDATE SET last_comment=excluded.last_comment,seen=excluded.seen''', (owner, last, now))
