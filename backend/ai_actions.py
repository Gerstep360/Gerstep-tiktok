"""Authenticated, bounded cues to the connected PC; no model text or file paths.

POST /Gerstep/api/bridge/ai/actions requires the independent bridge Bearer key.
POST /Gerstep/api/admin/ai/effect requires an admin session and matching Origin.
Both accept {action_id, effect_id, turn_id?}, share a 4s cooldown and 12/min cap,
and use the existing two-item bridge queue. Retries with the same ID never replay.
HTTP 409 means offline/disabled/paused, 429 quota, and 503 full: none are buffered.
Successful cues expire in five seconds during transport and are not persisted.

The PC remains responsible for mapping these IDs to its approved sound catalog,
waiting for the associated speech to finish, and honoring its emergency switch.
"""
from collections import OrderedDict, deque
import re
import time
from uuid import UUID

from aiohttp import web

EFFECTS = frozenset({'laugh', 'baby_laugh', 'shock', 'fail', 'high_fail', 'meme'})
ACTION_ID = re.compile(r'^[A-Za-z0-9:_-]{8,64}$')
TTL_SECONDS = 5
COOLDOWN_SECONDS = 4


class AIEffects:
    def __init__(self, *, clock=time.monotonic, wall_clock=time.time):
        self.clock, self.wall_clock = clock, wall_clock
        self.recent = OrderedDict()
        self.sent = deque(maxlen=12)
        self.last_sent = float('-inf')

    def enqueue(self, hub, payload):
        if not isinstance(payload, dict) or not {'action_id', 'effect_id'} <= set(payload) or set(payload) - {'action_id', 'effect_id', 'turn_id'}:
            raise ValueError('Usá únicamente action_id, effect_id y turn_id opcional.')
        action_id, effect_id = payload['action_id'], payload['effect_id']
        if not isinstance(action_id, str) or not ACTION_ID.fullmatch(action_id):
            raise ValueError('Identificador de acción inválido.')
        if not isinstance(effect_id, str) or effect_id not in EFFECTS:
            raise ValueError('Efecto no permitido.')
        turn_id = payload.get('turn_id', '')
        if not isinstance(turn_id, str) or len(turn_id) > 44:
            raise ValueError('Turno de voz inválido.')
        if turn_id:
            prefix, separator, suffix = turn_id.partition(':')
            if separator != ':' or prefix not in {'ai', 'preview'} or len(suffix) not in {32, 36}:
                raise ValueError('Turno de voz inválido.')
            try:
                UUID(suffix)
            except ValueError:
                raise ValueError('Turno de voz inválido.') from None
        now = self.clock()
        while self.recent and next(iter(self.recent.values()))['until'] <= now:
            self.recent.popitem(last=False)
        previous = self.recent.get(action_id)
        if previous:
            if previous['message']['effect_id'] != effect_id or previous['message'].get('turn_id', '') != turn_id:
                raise ValueError('Ese identificador ya pertenece a otro efecto.')
            return {'accepted': False, 'duplicate': True, 'action_id': action_id}
        peer = hub.bridge
        if peer is None or getattr(peer.socket, 'closed', False):
            raise web.HTTPConflict(text='El programa del PC está desconectado.')
        if hub.domain.suspended or hub.cache.get('live', {}).get('emergency'):
            raise web.HTTPConflict(text='Las interacciones están en pausa.')
        catalog = getattr(peer, 'ai_effects', {})
        if catalog.get('enabled') is not True or effect_id not in catalog.get('available', []):
            raise web.HTTPConflict(text='Ese efecto no está habilitado en el PC.')
        if peer.queue.full():
            raise web.HTTPServiceUnavailable(text='El PC tiene acciones pendientes. No se guardó el efecto.')
        while self.sent and self.sent[0] <= now - 60:
            self.sent.popleft()
        wait = COOLDOWN_SECONDS - (now - self.last_sent)
        if wait > 0 or len(self.sent) >= self.sent.maxlen:
            retry = max(1, int(wait + .999), int(60 - (now - self.sent[0]) + .999) if len(self.sent) >= self.sent.maxlen else 1)
            raise web.HTTPTooManyRequests(text='Esperá antes de reproducir otro efecto.', headers={'Retry-After': str(retry)})
        created = self.wall_clock()
        message = {'type': 'ai_effect', 'action_id': action_id, 'effect_id': effect_id,
                   'created': created, 'expires': created + TTL_SECONDS}
        if turn_id:
            message['turn_id'] = turn_id
        peer.queue.put_nowait(message)
        self.sent.append(now)
        self.last_sent = now
        self.recent[action_id] = {'until': now + 60, 'message': message}
        while len(self.recent) > 128:
            self.recent.popitem(last=False)
        return {'accepted': True, 'action_id': action_id, 'effect_id': effect_id, 'expires': message['expires']}


def update_catalog(hub, events):
    """Use only the current authenticated PC's advertised whitelist, never paths."""
    if hub.bridge is None:
        return
    for event in events:
        if event.get('kind') != 'state':
            continue
        state = event.get('state')
        catalog = state.get('ai_effects') if isinstance(state, dict) else None
        if not isinstance(catalog, dict):
            hub.bridge.ai_effects = {'enabled': False, 'available': []}
            continue
        values = catalog.get('available')
        available = sorted(EFFECTS.intersection(item for item in values if isinstance(item, str))) if isinstance(values, list) and len(values) <= 32 else []
        hub.bridge.ai_effects = {'enabled': catalog.get('enabled') is True, 'available': available}


async def bridge_action(request):
    from .server import HUB, body, machine
    machine(request)
    return web.json_response(request.app[HUB].ai_effects.enqueue(request.app[HUB], await body(request)), status=202)


async def admin_effect(request):
    from .server import HUB, actor, body
    actor(request, 'admin')
    # This is an explicit operator action, never part of the admin test-chat reply.
    return web.json_response(request.app[HUB].ai_effects.enqueue(request.app[HUB], await body(request)), status=202)


def register(app, prefix):
    app.add_routes([web.post(prefix + '/api/bridge/ai/actions', bridge_action),
                    web.post(prefix + '/api/admin/ai/effect', admin_effect)])
