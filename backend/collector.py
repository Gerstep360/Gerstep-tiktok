"""Optional VPS intake reuses the desktop adapter, with all speech disabled."""
import asyncio
import time
import uuid
from pathlib import Path


class IntakeOnlyAudio:
    async def reset_session(self): pass
    async def queue_message(self, *args, **kwargs): return False
    def snapshot(self): return {'pending':0}


async def collect(hub, username):
    from gerstep_live.settings import AppSettings
    from gerstep_live.persistence.profiles import ProfileStore, Award
    settings = AppSettings(tts_comments=False, tts_gifts=False, auto_mode=False,
                           director_enabled=False, spontaneous_enabled=False, levels_enabled=False)
    stream_id = uuid.uuid4().hex
    stats = dict.fromkeys(('comments','gifts','coins','likes','viewers'),0)
    profiles = ProfileStore(Path(hub.config.database).parent / 'tiktok_viewers.sqlite3')
    began = None
    async def event(kind, payload):
        nonlocal began
        if hub.bridge: return
        if kind in {'connect','disconnect'}:
            if kind=='connect' and began is None: began=time.time()
            await hub.call(hub.domain.ingest, [{'kind':'state','state':{'connected':kind=='connect','username':username,
                'stream_id':stream_id,'started_at':began,'stats':stats.copy()}}])
        elif kind in {'comment','gift'}:
            stats['comments' if kind=='comment' else 'gifts'] += 1
            if kind=='gift': stats['coins'] += payload.get('coins',0)
            identity=payload.get('metadata',{})
            profiles.award(Award(str(identity.get('user_id','')),str(identity.get('handle','')),
                str(identity.get('nickname') or payload.get('user','Espectador')),kind,str(identity.get('event_id','')),
                coins=payload.get('coins',0)))
            await hub.call(hub.domain.ingest, [{'kind':kind, **payload}])
    async def publish_profiles():
        while True:
            if not hub.bridge:
                rows=await asyncio.wrap_future(profiles.top())
                await hub.call(hub.domain.ingest,[{'kind':'profiles','profiles':rows}])
            await asyncio.sleep(30)
    publisher=asyncio.create_task(publish_profiles())
    try:
        await listen_loop(hub,username,settings,event)
    finally:
        publisher.cancel()
        await asyncio.gather(publisher,return_exceptions=True)
        await asyncio.to_thread(profiles.close)


async def listen_loop(hub, username, settings, event):
    from gerstep_live.integrations.tiktok import TikTokManager
    failures=0
    while True:
        while hub.bridge:
            hub.source_changed.clear()
            await hub.source_changed.wait()
        manager = TikTokManager(IntakeOnlyAudio(), username=username, settings=settings, event_callback=event)
        tasks = []
        try:
            async def listen():
                live = await asyncio.wait_for(manager.start(),20)
                await live
            hub.source_changed.clear()
            tasks = [asyncio.create_task(listen()), asyncio.create_task(hub.source_changed.wait())]
            done,_ = await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done: task.result()
            failures = 0
        except asyncio.CancelledError: raise
        except Exception as exc:
            import logging
            logging.getLogger('Collector').warning('TikTok intake failed: %s',type(exc).__name__)
            failures += 1
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await asyncio.wait_for(manager.stop(),5)
        await asyncio.sleep(min(30,2**min(failures+1,5)))
