"""Optional real Chromium regression probe. Set BROWSER_BINARY to Chrome/Edge.

Uses a fresh headless profile, loopback backend and in-memory database. No VPS,
TikTok, installed service, personal browser profile or physical device is used.
"""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from backend.config import Config
from backend.server import HUB, create_app


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class DevTools:
    def __init__(self, ws):
        self.ws, self.pending, self.errors, self.counter = ws, {}, [], 0
        self.reader = asyncio.create_task(self.receive())

    async def receive(self):
        async for event in self.ws:
            message = json.loads(event.data)
            if 'id' in message:
                future = self.pending.pop(message['id'], None)
                if future and not future.done(): future.set_result(message)
            elif message.get('method') == 'Runtime.exceptionThrown':
                detail = message['params']['exceptionDetails']
                self.errors.append(detail.get('exception', {}).get('description', detail['text']))

    async def call(self, method, **params):
        self.counter += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.counter] = future
        await self.ws.send_json({'id': self.counter, 'method': method, 'params': params})
        result = await asyncio.wait_for(future, 10)
        if 'error' in result: raise AssertionError(result['error'])
        return result.get('result', {})

    async def evaluate(self, expression):
        result = await self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        if 'exceptionDetails' in result: raise AssertionError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    async def wait(self, expression):
        for _ in range(120):
            if self.errors: raise AssertionError('\n'.join(self.errors))
            if await self.evaluate(expression): return
            await asyncio.sleep(.05)
        raise AssertionError('Browser condition timed out: ' + expression)


async def probe():
    binary = os.environ['BROWSER_BINARY']
    port, debug = free_port(), free_port()
    config = Config(f'http://127.0.0.1:{port}', 's'*48, 'b'*48, 'a'*48, database=':memory:', development=True)
    server = TestServer(create_app(config), port=port)
    await server.start_server()
    try:
        with tempfile.TemporaryDirectory(prefix='gerstep-browser-test-') as profile:
            process = subprocess.Popen([binary, '--headless', '--disable-gpu', '--disable-extensions',
                '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
                '--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={debug}',
                '--user-data-dir=' + profile, 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                async with ClientSession() as client:
                    tabs = None
                    for _ in range(100):
                        try:
                            async with client.get(f'http://127.0.0.1:{debug}/json/list') as response: tabs = await response.json()
                            if any(tab['type'] == 'page' for tab in tabs): break
                        except OSError: pass
                        await asyncio.sleep(.1)
                    if not tabs: raise AssertionError('Headless browser did not start')
                    tab = next(tab for tab in tabs if tab['type'] == 'page')
                    async with client.ws_connect(tab['webSocketDebuggerUrl']) as ws:
                        browser = DevTools(ws)
                        try:
                            await browser.call('Runtime.enable')
                            await browser.call('Page.enable')
                            await browser.call('Page.navigate', url=config.origin + '/Gerstep/')
                            await browser.wait("document.querySelector('.tiny-status')?.textContent.includes('Sincronizado')")
                            await browser.wait("document.querySelector('.poll-panel')?.textContent.includes('La próxima encuesta')")
                            hub = server.app[HUB]
                            await hub.admin('poll_create', {'title': 'Encuesta de prueba', 'options': ['Error', 'Reinicio'], 'duration': 60})
                            await browser.wait("document.querySelector('.poll-panel')?.textContent.includes('Encuesta de prueba')")
                            await browser.wait("document.querySelector('.poll-option:not(:disabled)') !== null")
                            await browser.evaluate("document.querySelector('.poll-option').click()")
                            await browser.wait("document.querySelector('.poll-panel')?.textContent.includes('Tu opción registrada: 1')")
                            # Reload includes a persisted vote; effects must recover it.
                            await browser.call('Page.reload')
                            await browser.wait("document.querySelector('.poll-panel')?.textContent.includes('Tu opción registrada: 1')")
                            # A new poll must discard the previous poll's choice.
                            await hub.admin('poll_create', {'title': 'Segunda encuesta', 'options': ['Uno', 'Dos'], 'duration': 60})
                            await browser.wait("document.querySelector('.poll-panel')?.textContent.includes('Segunda encuesta')")
                            await browser.wait("document.querySelectorAll('.poll-option.voted').length === 0")
                            for width, height in ((1280, 800), (390, 844)):
                                await browser.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=width<600)
                                if width < 600:
                                    await browser.evaluate("[...document.querySelectorAll('.mobile-nav button')].find(b=>b.textContent.includes('Encuestas')).click()")
                                    await browser.wait("document.querySelector('.main-content .poll-panel') !== null")
                                assert await browser.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
                            await hub.admin('poll_close', {})
                            await browser.wait("document.querySelector('.main-content .poll-panel')?.textContent.includes('Encuesta cerrada')")
                            assert not browser.errors, browser.errors
                            await browser.call('Browser.close')
                        finally:
                            browser.reader.cancel()
                            with contextlib.suppress(asyncio.CancelledError): await browser.reader
                process.wait(timeout=10)
            finally:
                if process.poll() is None: process.terminate(); process.wait(timeout=10)
        return {'initial_empty_state': True, 'websocket_poll_update': True, 'vote_and_reload': True,
                'new_poll_clears_previous_choice': True, 'poll_close': True, 'javascript_errors': 0,
                'viewports_without_horizontal_overflow': ['1280x800', '390x844'], 'environment': 'local headless Chromium'}
    finally:
        await server.close()


if __name__ == '__main__': print(json.dumps(asyncio.run(probe()), indent=2))
