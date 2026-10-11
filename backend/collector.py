"""Standalone intake pauses whenever the desktop bridge owns the stream."""
import asyncio
import logging
import time
import uuid
from .freshness import Freshness
from .tiktok_intake import Intake


async def collect(hub, username):
    gate = Freshness()
    stream_id, began, last_state = uuid.uuid4().hex, None, 0
    stats = dict.fromkeys(('comments', 'gifts', 'coins', 'likes', 'viewers'), 0)

    async def event(kind, payload):
        nonlocal began, last_state
        if hub.bridge: return
        if kind == 'connect' and began is None: began = time.time()
        if kind in {'comment', 'gift'}:
            stats['comments' if kind == 'comment' else 'gifts'] += 1
            if kind == 'gift': stats['coins'] += payload.get('coins', 0)
            await hub.call(hub.domain.ingest, [{'kind': kind, **payload, '_collector_profile': True}])
        elif kind == 'like': stats['likes'] = payload['total']
        # Joins are not concurrent viewers. Never invent that metric.
        if kind in {'connect', 'disconnect'} or time.monotonic() - last_state >= 2:
            last_state = time.monotonic()
            await hub.call(hub.domain.ingest, [{'kind': 'state', 'state': {
                'connected': gate.connected, 'username': username, 'stream_id': stream_id,
                'started_at': began, 'stats': stats.copy()}}])

    failures = 0
    while True:
        while hub.bridge:
            hub.source_changed.clear()
            await hub.source_changed.wait()
        manager = None
        tasks = []
        try:
            manager = Intake(username, event, gate)
            async def listen():
                task = await asyncio.wait_for(manager.start(), 20)
                await task
            hub.source_changed.clear()
            tasks = [asyncio.create_task(listen()), asyncio.create_task(hub.source_changed.wait())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done: task.result()
            failures = 0
        except asyncio.CancelledError: raise
        except Exception as exc:
            logging.getLogger('Collector').warning('TikTok intake failed: %s', type(exc).__name__)
            failures += 1
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if manager: await asyncio.wait_for(manager.stop(), 5)
            except Exception: logging.getLogger('Collector').warning('SDK cleanup failed')
            await event('disconnect', {})
        hub.source_changed.clear()
        try: await asyncio.wait_for(hub.source_changed.wait(), min(30, 2 ** min(failures + 1, 5)))
        except TimeoutError: pass
