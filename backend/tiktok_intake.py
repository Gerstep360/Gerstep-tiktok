"""Optional SDK adapter; no TTS, GUI, desktop settings or PC actions."""
import inspect


class Intake:
    def __init__(self, username, emit, gate, *, client=None, event_types=None):
        if client is None:
            from TikTokLive import TikTokLiveClient, events
            client = TikTokLiveClient(unique_id=username.lstrip('@'))
            event_types = {name: getattr(events, name + 'Event') for name in ('Connect', 'Disconnect', 'Comment', 'Gift', 'Like', 'Join')}
        self.client, self.emit, self.gate, self.retired = client, emit, gate, False
        for name, handler in (('Connect', self.connect), ('Disconnect', self.disconnect),
                              ('Comment', self.comment), ('Gift', self.gift), ('Like', self.like), ('Join', self.join)):
            client.on(event_types[name], handler)

    async def connect(self, event):
        if self.retired: return
        self.gate.connect()
        await self.emit('connect', {})

    async def disconnect(self, event):
        if self.retired: return
        self.gate.disconnect()
        await self.emit('disconnect', {})

    @staticmethod
    def identity(event):
        user = event.user
        raw = str(getattr(user, 'id', '') or '')[:32]
        return {'user_id': raw if raw.isdecimal() and int(raw) > 0 else '',
                'handle': str(getattr(user, 'unique_id', '') or '')[:80],
                'nickname': str(getattr(user, 'nickname', '') or '')[:80],
                'event_id': str(getattr(getattr(event, 'base_message', None), 'message_id', '') or '')[:80]}

    def accept(self, event): return not self.retired and self.gate.accept(event)

    async def comment(self, event):
        if self.accept(event):
            identity = self.identity(event)
            await self.emit('comment', {'user': identity['handle'], 'message': str(event.comment)[:2000], 'metadata': identity})

    async def gift(self, event):
        if event.gift.streakable and event.repeat_end != 1: return
        if self.accept(event):
            identity = self.identity(event)
            amount = max(1, int(event.repeat_count or 1))
            await self.emit('gift', {'user': identity['handle'], 'amount': amount,
                'coins': max(0, int(event.gift.diamond_count)) * amount, 'metadata': identity})

    async def like(self, event):
        if self.accept(event): await self.emit('like', {'total': int(event.total)})

    async def join(self, event):
        if self.accept(event): await self.emit('join', {})

    async def start(self): return await self.client.start(process_connect_events=False)

    async def stop(self):
        self.retired = True
        self.gate.disconnect()
        try:
            if self.client.connected: await self.client.disconnect(close_client=False)
            else:
                import asyncio
                task = getattr(self.client, '_event_loop_task', None)
                if task and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            web = getattr(self.client, 'web', None)
            if web:
                await web.httpx_client.aclose()
                if web.curl_cffi_client is not None: await web.curl_cffi_client.close()
