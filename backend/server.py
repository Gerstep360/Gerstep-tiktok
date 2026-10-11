import asyncio
from dataclasses import dataclass, field
import json
import logging
import secrets
import time

from aiohttp import web, WSMsgType
from .config import Config
from .database import Database
from .domain import Domain
from .security import Security, clean_text
from .identities import session as visitor_session

log = logging.getLogger('Interactive')
HUB = web.AppKey('hub', object)


def compact_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


@dataclass(eq=False)
class Peer:
    socket: object
    role: str
    owner: str
    ip: str
    expires: float = float('inf')
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2))
    previous: dict = field(default_factory=dict)


class Hub:
    def __init__(self, config):
        self.config = config
        self.security = Security(config)
        self.db = Database(config.database)
        self.domain = Domain(self.security)
        self.peers = set()
        self.bridge = None
        self.cache = {}
        self.dirty = asyncio.Event()
        self.source_changed = asyncio.Event()
        self.tasks = []
        self.actions = {}
        self.latencies = []
        self.password_workers = asyncio.Semaphore(2)

    async def start(self):
        await self.db.start()
        await self.db.call(self.domain.load)
        await self.db.call(lambda db: db.execute("UPDATE requests SET status='error' WHERE status='selected'"))
        self.cache = await self.db.call(self.domain.snapshot)
        self.tasks = [asyncio.create_task(self._broadcast(), name='web-state-publisher'), asyncio.create_task(self._maintenance(), name='web-retention')]
        import os
        if os.environ.get('GERSTEP_COLLECT_TIKTOK') == '1':
            from .collector import collect
            self.tasks.append(asyncio.create_task(collect(self, os.environ.get('GERSTEP_TIKTOK_USERNAME','gerstep_official')), name='vps-tiktok-intake'))

    async def stop(self):
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.gather(*(peer.socket.close(code=1001, message=b'Server stopping') for peer in list(self.peers)), return_exceptions=True)
        await self.db.close()

    async def call(self, operation, *args):
        result = await self.db.call(operation, *args)
        self.dirty.set()
        return result

    def state(self, role='viewer', owner=''):
        data = self.cache.copy()
        privileged = role in {'admin', 'bridge'}
        rows = data.get('requests', [])
        if not privileged:
            public = [r for r in rows if r['status'] in {'approved', 'selected', 'answered'}]
            public.sort(key=lambda r: (r['status'] == 'selected', r['supports'], r['created']), reverse=True)
            own = [r for r in rows if owner and r['owner'] == owner][:10]
            rows = list({r['id']: r for r in [*own, *public[:20]]}.values())
        data['requests'] = [{k: v for k, v in row.items() if k != 'owner' or privileged} for row in rows]
        if data.get('active'):
            data['active'] = {k: v for k, v in data['active'].items() if k != 'owner'}
        if not privileged:
            data.pop('chat', None)
            data.pop('markers', None)
            data.pop('voters', None)
        data['bridge_online'] = self.bridge is not None
        return data

    async def _broadcast(self):
        while True:
            await self.dirty.wait()
            await asyncio.sleep(.05)  # Coalesce bursts; no idle polling or per-viewer SQL.
            self.dirty.clear()
            self.cache = await self.db.call(self.domain.snapshot)
            for peer in list(self.peers):
                data = self.state(peer.role, peer.owner)
                if data == peer.previous: continue
                message = {'type': 'snapshot', 'state': data}
                # Preserve action messages in the bridge queue; disconnect instead of dropping one.
                if peer.queue.full():
                    if peer.role == 'bridge':
                        asyncio.create_task(peer.socket.close(code=1013, message=b'Backpressure'))
                        continue
                    peer.queue.get_nowait()
                peer.queue.put_nowait(message)

    async def _maintenance(self):
        while True:
            await asyncio.sleep(5)
            before = self.cache
            await self.db.call(self.domain.maintain)
            snapshot = await self.db.call(self.domain.snapshot)
            if snapshot != before: self.dirty.set()
            now = time.time()
            for peer in list(self.peers):
                if peer.expires <= now:
                    await peer.socket.close(code=1008, message=b'Session expired')
            for key, action in list(self.actions.items()):
                if action['expires'] < now:
                    self.actions.pop(key)
                    await self.call(self.domain.moderate, 'ack', {'id': action['request_id'], 'status': 'error'})

    async def admin(self, action, payload):
        if action == 'bot' and any(item['request_id'] == payload.get('id') for item in self.actions.values()):
            raise ValueError('Esta intervención ya está en curso.')
        if action == 'bot' and (not self.bridge or not self.cache.get('live', {}).get('connected') or self.cache.get('live', {}).get('emergency')):
            raise ValueError('Conectá Gerstep LIVE y reanudá el presentador antes de usar el bot.')
        if action == 'bot' and (len(self.actions) >= 8 or self.bridge.queue.full()):
            raise ValueError('El bot está ocupado. Esperá antes de seleccionar otro mensaje.')
        result = await self.call(self.domain.moderate, action, payload)
        if action in {'clear', 'preferences'} and (action == 'clear' or self.domain.suspended):
            self.actions.clear()
            if self.bridge:
                try: self.bridge.queue.put_nowait({'type': 'cancel_web'})
                except asyncio.QueueFull: await self.bridge.socket.close(code=1013)
        if action == 'bot':
            row = result['request']
            task = {'type': 'approved', 'action_id': secrets.token_hex(12), 'request_id': row['id'],
                    'kind': row['kind'], 'text': row['text'], 'nickname': row['nickname'], 'owner': row['owner'],
                    'response': row['response'], 'expires': time.time() + 10, 'created': time.time()}
            self.actions[task['action_id']] = task
            self.bridge.queue.put_nowait(task)
        return {key: value for key, value in result.items() if key != 'request'}


def actor(request, role='viewer'):
    hub = request.app[HUB]
    if role == 'admin' and hub.security.valid_key(request.headers.get('X-Gerstep-Admin', ''), hub.config.admin_token):
        return {'id': 'operator', 'role': 'admin', 'nickname': 'Gerstep'}
    value = hub.security.read(request.cookies.get('gerstep_' + role, ''), role)
    if not value: raise web.HTTPUnauthorized(text='Necesitás iniciar una sesión.')
    return value


def machine(request):
    hub = request.app[HUB]
    if not hub.security.valid_key(request.headers.get('Authorization', '').removeprefix('Bearer '), hub.config.bridge_token):
        raise web.HTTPUnauthorized()


def ip_key(request):
    # Nginx overwrites this header; trust it only on a local reverse-proxy connection.
    address = request.remote or 'unknown'
    if not request.app[HUB].config.development and address in {'127.0.0.1', '::1'}:
        address = request.headers.get('X-Real-IP', address)
    return request.app[HUB].security.digest('ip:' + address)


def rate(request, action, *, limit=1, period=15):
    if not request.app[HUB].security.allow((ip_key(request), action), limit=limit, period=period):
        raise web.HTTPTooManyRequests(text='Esperá antes de volver a intentarlo.', headers={'Retry-After': str(period)})


@web.middleware
async def security_middleware(request, handler):
    hub = request.app[HUB]
    if request.method not in {'GET', 'POST'}: raise web.HTTPMethodNotAllowed(request.method, ['GET', 'POST'])
    if request.method == 'POST' and not request.path.endswith('/api/bridge/events'):
        origin = request.headers.get('Origin')
        # Native administration requires a separate admin key, never the bridge key.
        native_admin = request.path.endswith('/api/admin/action') and hub.security.valid_key(request.headers.get('X-Gerstep-Admin', ''), hub.config.admin_token)
        if origin != hub.config.origin and not native_admin: raise web.HTTPForbidden(text='Origen no permitido.')
    try:
        response = await handler(request)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        response = web.json_response({'error': str(exc) if isinstance(exc, ValueError) else 'Solicitud inválida.'}, status=400)
    except web.HTTPException as exc:
        response = web.json_response({'error': exc.text}, status=exc.status, headers={k:v for k,v in exc.headers.items() if k.lower() not in {'content-type','content-length'}})
    except Exception as exc:
        log.error('Request failed: %s', type(exc).__name__)
        response = web.json_response({'error': 'Error del servidor. Reintentá.'}, status=500)
    if not isinstance(response, web.WebSocketResponse):
        response.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                                 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' " + hub.config.origin.replace('https:', 'wss:').replace('http:', 'ws:') + "; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
    return response


async def body(request):
    value = await request.json()
    if not isinstance(value, dict): raise ValueError('Se esperaba un objeto JSON.')
    return value


async def join(request):
    rate(request, 'join', limit=120, period=3600)
    hub = request.app[HUB]
    values = await body(request)
    previous = hub.security.read(request.cookies.get('gerstep_viewer', ''), 'viewer')
    identity = await hub.db.call(visitor_session, hub.security, values, previous, ip_key(request))
    if 'nickname' in values:
        await hub.db.call(lambda db: setattr(hub.domain,'_poll_dirty',True))
        hub.dirty.set()
    token = hub.security.issue('viewer', user_id=identity['id'], nickname=identity['nickname'], lifetime=30*86400)
    response = web.json_response({k:v for k,v in identity.items() if k != 'id'})
    response.set_cookie('gerstep_viewer', token, httponly=True, secure=not hub.config.development, samesite='Strict', max_age=30*86400, path=hub.config.prefix)
    # A renamed session reconnects with its new display name, retaining its owner ID.
    for peer in list(hub.peers):
        if peer.role == 'viewer' and peer.owner == identity['id']:
            await peer.socket.close(code=1000)
    return response


async def state(request):
    hub = request.app[HUB]
    session = hub.security.read(request.cookies.get('gerstep_viewer', ''), 'viewer')
    result = hub.state(owner=session['id'] if session else '')
    result['me'] = {'nickname': session['nickname']} if session else None
    if result.get('poll') and session:
        row = await hub.db.call(lambda db: db.execute('SELECT choice FROM votes WHERE poll_id=? AND (owner=? OR ip=?) LIMIT 1',
                               (result['poll']['id'], session['id'], ip_key(request))).fetchone())
        result['my_vote'] = {'poll_id':result['poll']['id'], 'choice':row['choice']} if row else None
    return web.json_response(result)


async def viewer_action(request):
    session = actor(request)
    hub = request.app[HUB]
    rate(request, 'viewer-action', limit=12, period=60)
    values = await body(request)
    action = request.match_info['action']
    if action == 'submit': result = await hub.call(hub.domain.submit, session['id'], session['nickname'], values, ip_key(request))
    elif action == 'support': result = await hub.call(hub.domain.support, session['id'], str(values.get('id', '')), ip_key(request))
    elif action == 'vote': result = await hub.call(hub.domain.vote, session['id'], values.get('choice'), values.get('poll_id'), ip_key(request), session['nickname'])
    else: raise web.HTTPNotFound()
    return web.json_response(result)


async def login(request):
    rate(request, 'admin-login', limit=5, period=60)
    hub = request.app[HUB]
    supplied = (await body(request)).get('token', '')
    if hub.config.admin_password_hash:
        from .passwords import verify_password
        if hub.password_workers.locked(): raise web.HTTPTooManyRequests(text='Reintentá en un momento.')
        async with hub.password_workers:
            valid = await asyncio.to_thread(verify_password, supplied, hub.config.admin_password_hash)
    else:
        valid = hub.security.valid_key(supplied, hub.config.admin_token)
    if not valid: raise web.HTTPUnauthorized(text='Clave administrativa incorrecta.')
    response = web.json_response({'ok': True})
    response.set_cookie('gerstep_admin', hub.security.issue('admin', lifetime=8*3600), secure=not hub.config.development, httponly=True, samesite='Strict', max_age=8*3600, path=hub.config.prefix)
    return response


async def admin_state(request):
    actor(request, 'admin')
    return web.json_response(request.app[HUB].state('admin'))


async def connection_export(request):
    actor(request, 'admin')
    rate(request, 'connection-export', limit=3, period=60)
    conf = request.app[HUB].config
    return web.json_response({'url': conf.origin + conf.prefix, 'bridge_token': conf.bridge_token,
                             'admin_api_token': conf.admin_token},
                            headers={'Content-Disposition': 'attachment; filename="gerstep-pc-connection.json"',
                                     'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


async def logout(request):
    session = actor(request, 'admin')
    hub = request.app[HUB]
    hub.security.revoke_admin(session)
    response = web.json_response({'ok':True})
    response.del_cookie('gerstep_admin', path=hub.config.prefix)
    # Close sockets for this login; a replay of its old cookie is rejected too.
    for peer in list(hub.peers):
        if peer.role == 'admin' and peer.owner == session['id']: await peer.socket.close(code=1008)
    return response


async def admin_action(request):
    actor(request, 'admin')
    rate(request, 'admin-action', limit=120, period=60)
    values = await body(request)
    result = await request.app[HUB].admin(values.pop('action', ''), values)
    return web.json_response(result)


async def markers(request):
    actor(request, 'admin')
    return web.json_response({'markers': request.app[HUB].cache.get('markers', [])}, headers={'Content-Disposition': 'attachment; filename="gerstep-markers.json"'})


async def votes_export(request):
    actor(request,'admin')
    rate(request,'vote-export',limit=3,period=60)
    hub=request.app[HUB]
    poll_id=request.query.get('poll_id') or (hub.cache.get('poll') or {}).get('id','')
    if not isinstance(poll_id,str) or len(poll_id)>32: raise ValueError('Encuesta inválida.')
    response=web.StreamResponse(headers={'Content-Type':'application/x-ndjson; charset=utf-8',
        'Content-Disposition':'attachment; filename="gerstep-votes.ndjson"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    await response.prepare(request)
    after=0
    while True:
        rows=await hub.db.call(lambda db:hub.domain.voters(db,poll_id,after=after))
        if not rows: break
        await asyncio.wait_for(response.write(('\n'.join(compact_json({k:v for k,v in row.items() if k!='sequence'}) for row in rows)+'\n').encode()),5)
        after=rows[-1]['sequence']
    await response.write_eof()
    return response


async def bridge_events(request):
    machine(request)
    values = await body(request)
    events = values.get('events')
    if not isinstance(events, list) or len(events) > 50 or any(not isinstance(e, dict) for e in events): raise ValueError('Lote inválido.')
    return web.json_response(await request.app[HUB].call(request.app[HUB].domain.ingest, events))


async def websocket(request):
    hub = request.app[HUB]
    role = request.match_info['role']
    expires = float('inf')
    if role == 'bridge':
        machine(request)
        if hub.bridge: raise web.HTTPConflict(text='Ya existe un programa conectado.')
        owner = 'bridge'
    else:
        if request.headers.get('Origin') != hub.config.origin: raise web.HTTPForbidden(text='Origen no permitido.')
        if role == 'admin':
            session = actor(request, 'admin')
            owner, expires = session['id'], session.get('expires', expires)
        elif role == 'viewer':
            session = hub.security.read(request.cookies.get('gerstep_viewer', ''), 'viewer')
            owner = session['id'] if session else ''
            expires = session['expires'] if session else expires
        else: raise web.HTTPNotFound()
    address = ip_key(request)
    if len(hub.peers) >= 300 or sum(peer.ip == address for peer in hub.peers) >= (8 if role in {'bridge', 'admin'} else 4):
        raise web.HTTPTooManyRequests(text='Límite de conexiones alcanzado.')
    rate(request, 'socket', limit=30, period=60)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=65536 if role == 'bridge' else 4096, compress=False)
    await ws.prepare(request)
    peer = Peer(ws, role, owner, address, expires)
    hub.peers.add(peer)
    if role == 'bridge':
        hub.bridge = peer
        hub.source_changed.set()
    peer.previous = hub.state(role, owner)
    await ws.send_json({'type': 'state', 'patch': peer.previous},dumps=compact_json)
    hub.dirty.set()
    async def sender():
        while True:
            message = await peer.queue.get()
            if message.get('type') == 'snapshot':
                data = message['state']
                patch = {key:value for key,value in data.items() if peer.previous.get(key) != value}
                if not patch: continue
                message = {'type':'state', 'patch':patch}
                await asyncio.wait_for(ws.send_json(message,dumps=compact_json), 3)
                peer.previous = data
                continue
            await asyncio.wait_for(ws.send_json(message,dumps=compact_json), 3)
    task = asyncio.create_task(sender(), name='websocket-writer')
    def writer_done(done):
        if not done.cancelled() and done.exception(): asyncio.create_task(ws.close(code=1013))
    task.add_done_callback(writer_done)
    try:
        async for message in ws:
            if message.type != WSMsgType.TEXT: continue
            if role != 'bridge':
                await ws.close(code=1008, message=b'Read-only channel')
                break
            if not hub.security.allow(('bridge-message', address), limit=100, period=1):
                await ws.close(code=1008)
                break
            try:
                payload = json.loads(message.data)
                if not isinstance(payload, dict): raise ValueError()
                if payload.get('type') == 'events':
                    events = payload.get('events')
                    if not isinstance(events, list) or len(events)>50 or any(not isinstance(e,dict) for e in events): raise ValueError()
                    await hub.call(hub.domain.ingest, events)
                elif payload.get('type') == 'ack':
                    action = hub.actions.get(payload.get('action_id'))
                    if action:
                        status = payload.get('status')
                        if status in {'answered','error','selected'}:
                            if status != 'selected': hub.actions.pop(action['action_id'])
                            else:
                                hub.latencies.append((time.time() - action['created']) * 1000)
                                hub.latencies = hub.latencies[-256:]
                                action['expires'] = time.time() + 45
                            await hub.call(hub.domain.moderate, 'ack', {'id': action['request_id'], 'status': status})
                elif payload.get('type') == 'ping': pass
                else: raise ValueError()
            except (ValueError, TypeError, KeyError):
                await ws.send_json({'type':'error','message':'Evento inválido.'})
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        hub.peers.discard(peer)
        if hub.bridge is peer:
            hub.bridge = None
            await hub.db.call(lambda _db: hub.domain.live.update(connected=False))
            hub.source_changed.set()
            for action in list(hub.actions.values()):
                await hub.call(hub.domain.moderate, 'ack', {'id': action['request_id'], 'status':'error'})
            hub.actions.clear()
        hub.dirty.set()
    return ws


async def frontend(request):
    if request.path.rstrip('/').endswith('/admin'):
        try: actor(request, 'admin')
        except web.HTTPUnauthorized: raise web.HTTPFound(request.app[HUB].config.prefix+'/login')
    path = request.app[HUB].config.frontend / 'index.html'
    if not path.exists(): return web.Response(text='Build the React frontend first.', status=503)
    return web.FileResponse(path)


async def health(request):
    return web.json_response({'ok':True})


def create_app(config):
    hub = Hub(config)
    app = web.Application(middlewares=[security_middleware], client_max_size=65536)
    app[HUB] = hub
    prefix = config.prefix
    app.add_routes([web.get(prefix+'/api/state', state), web.post(prefix+'/api/session', join),
                    web.post(prefix+'/api/viewer/{action}', viewer_action), web.post(prefix+'/api/admin/login', login),
                    web.get(prefix+'/api/admin/state', admin_state), web.post(prefix+'/api/admin/action', admin_action), web.post(prefix+'/api/admin/logout', logout),
                    web.get(prefix+'/api/admin/markers', markers), web.post(prefix+'/api/bridge/events', bridge_events),
                    web.get(prefix+'/api/admin/votes',votes_export),
                    web.get(prefix+'/api/admin/connection',connection_export),
                    web.get(prefix+'/api/{role}/ws', websocket), web.get(prefix+'/api/health', health),
                    web.get(prefix, frontend), web.get(prefix+'/', frontend), web.get(prefix+'/admin', frontend), web.get(prefix+'/login', frontend), web.get(prefix+'/overlay', frontend)])
    assets = config.frontend / 'assets'
    if assets.exists(): app.router.add_static(prefix+'/assets/', assets, follow_symlinks=False)
    async def lifecycle(_app):
        await hub.start()
        yield
        await hub.stop()
    app.cleanup_ctx.append(lifecycle)
    return app


if __name__ == '__main__':
    import os
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(Config.from_env()), host='127.0.0.1', port=int(os.environ.get('GERSTEP_PORT','9081')), access_log=None, print=None)
