"""Authenticated VPS-to-PC sound cue transport; no physical audio or provider calls."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
from types import SimpleNamespace
import unittest

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from backend.ai_actions import AIEffects, EFFECTS, update_catalog
from backend.config import Config
from backend.server import HUB, Peer, create_app


class Preview:
    async def close(self): pass


class AIEffectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = Config('http://127.0.0.1:9081', 's'*48, 'b'*48, 'a'*48,
                             database=':memory:', development=True)
        self.client = TestClient(TestServer(create_app(self.config, ai_preview=Preview())),
                                 cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.hub = self.client.server.app[HUB]
        self.now = 100.0
        self.wall = time.time()
        self.hub.ai_effects = AIEffects(clock=lambda: self.now, wall_clock=lambda: self.wall + self.now - 100)
        self.bridge_headers = {'Authorization': 'Bearer ' + self.config.bridge_token}
        self.admin_headers = {'Origin': self.config.origin}
        self.fake = Peer(SimpleNamespace(closed=False), 'bridge', 'bridge', 'fixture')
        self.fake.ai_effects = {'enabled': True, 'available': sorted(EFFECTS)}
        self.hub.bridge = self.fake

    async def asyncTearDown(self):
        await self.client.close()

    async def submit(self, *, action_id='test:abcdefgh', effect_id='laugh', headers=None, **extra):
        return await self.client.post('/Gerstep/api/bridge/ai/actions',
            json={'action_id': action_id, 'effect_id': effect_id, **extra},
            headers=self.bridge_headers if headers is None else headers)

    async def test_machine_credentials_required_viewer_and_admin_not_machine(self):
        for headers in ({}, {'Authorization': 'Bearer ' + self.config.admin_token},
                        {'X-Gerstep-Admin': self.config.admin_token}, {'Authorization': 'Bearer bad'}):
            response = await self.submit(headers=headers)
            self.assertEqual(response.status, 401)
        await self.client.post('/Gerstep/api/session', json={}, headers=self.admin_headers)
        self.assertEqual((await self.submit(headers=self.admin_headers)).status, 401)
        self.assertTrue(self.fake.queue.empty())

    async def test_authenticated_native_bridge_delivers_compact_cue(self):
        turn_id = 'ai:' + 'e'*32
        response = await self.submit(turn_id=turn_id)
        self.assertEqual(response.status, 202)
        result = await response.json()
        self.assertTrue(result['accepted'])
        message = self.fake.queue.get_nowait()
        self.assertEqual(message, {'type': 'ai_effect', 'action_id': 'test:abcdefgh', 'effect_id': 'laugh',
                                  'turn_id': turn_id, 'created': self.wall, 'expires': self.wall + 5})

    async def test_allowlist_rejects_paths_code_and_unknown_fields(self):
        for effect in ['../sounds/risa.wav', 'powershell', 'error', 'windows', ['laugh']]:
            self.assertEqual((await self.submit(effect_id=effect)).status, 400)
        for extra in [{'path': 'sounds/risa.wav'}, {'volume': 900}, {'duration': 8000}, {'turn_id': 'other:abcd'}]:
            self.assertEqual((await self.submit(**extra)).status, 400)
        for action_id in ['short', '../arbitrary', 'x'*65, 123]:
            self.assertEqual((await self.submit(action_id=action_id)).status, 400)
        self.assertTrue(self.fake.queue.empty())

    async def test_duplicate_does_not_play_again_or_change_association(self):
        turn_id = 'preview:' + 'a'*32
        self.assertEqual((await self.submit(turn_id=turn_id)).status, 202)
        response = await self.submit(turn_id=turn_id)
        self.assertTrue((await response.json())['duplicate'])
        self.assertEqual(self.fake.queue.qsize(), 1)
        self.assertEqual((await self.submit(effect_id='meme', turn_id=turn_id)).status, 400)
        self.assertEqual((await self.submit(turn_id='preview:'+'b'*32)).status, 400)

    async def test_offline_does_not_buffer_for_later_session(self):
        self.hub.bridge = None
        self.assertEqual((await self.submit()).status, 409)
        self.assertFalse(self.hub.ai_effects.recent)
        self.hub.bridge = self.fake
        self.assertEqual((await self.submit()).status, 202)

    async def test_disabled_missing_catalog_emergency_or_suspend(self):
        for catalog in [{}, {'enabled': False, 'available': ['laugh']}, {'enabled': True, 'available': ['meme']}]:
            self.fake.ai_effects = catalog
            self.assertEqual((await self.submit()).status, 409)
        self.fake.ai_effects = {'enabled': True, 'available': ['laugh']}
        self.hub.cache['live']['emergency'] = True
        self.assertEqual((await self.submit()).status, 409)
        self.hub.cache['live']['emergency'] = False
        self.hub.domain.suspended = True
        self.assertEqual((await self.submit()).status, 409)
        self.assertTrue(self.fake.queue.empty())

    async def test_burst_and_bounded_peer_queue(self):
        self.assertEqual((await self.submit()).status, 202)
        response = await self.submit(action_id='another:abcdefgh')
        self.assertEqual(response.status, 429)
        self.assertEqual(response.headers['Retry-After'], '4')
        self.now += 4
        self.assertEqual((await self.submit(action_id='another:abcdefgh')).status, 202)
        self.now += 4
        self.assertEqual((await self.submit(action_id='third:abcdefgh')).status, 503)
        self.assertEqual(self.fake.queue.qsize(), 2)
        self.assertNotIn('third:abcdefgh', self.hub.ai_effects.recent)

    async def test_window_limit_and_retention_bounded(self):
        for number in range(12):
            self.assertEqual((await self.submit(action_id=f'action:{number:08}')).status, 202)
            self.fake.queue.get_nowait()
            self.now += 4
        response = await self.submit(action_id='overflow:abcdefgh')
        self.assertEqual(response.status, 429)
        self.now += 12
        self.assertEqual((await self.submit(action_id='overflow:abcdefgh')).status, 202)
        self.assertLessEqual(len(self.hub.ai_effects.recent), 128)
        self.assertLessEqual(len(self.hub.ai_effects.sent), 12)

    async def test_admin_is_independent_and_requires_browser_origin(self):
        path = '/Gerstep/api/admin/ai/effect'
        payload = {'action_id': 'admin:abcdefgh', 'effect_id': 'laugh'}
        self.assertEqual((await self.client.post(path, json=payload, headers={**self.bridge_headers, **self.admin_headers})).status, 401)
        login = await self.client.post('/Gerstep/api/admin/login', json={'token': self.config.admin_token}, headers=self.admin_headers)
        self.assertEqual(login.status, 200)
        self.assertEqual((await self.client.post(path, json=payload)).status, 403)
        self.assertEqual((await self.client.post(path, json=payload, headers=self.admin_headers)).status, 202)
        self.assertEqual((await self.submit(action_id='shared:abcdefgh')).status, 429)

    async def test_catalog_sanitized_only_from_authenticated_state(self):
        update_catalog(self.hub, [{'kind': 'state', 'state': {'ai_effects': {'enabled': True, 'available': ['laugh', '../evil', 42, 'laugh']}}}])
        self.assertEqual(self.fake.ai_effects, {'enabled': True, 'available': ['laugh']})
        update_catalog(self.hub, [{'kind': 'state', 'state': {}}])
        self.assertEqual((await self.submit()).status, 409)
        response = await self.client.post('/Gerstep/api/bridge/events', json={'events': [{'kind': 'state', 'state': {'ai_effects': {'enabled': True, 'available': ['laugh']}}}]}, headers=self.bridge_headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.submit()).status, 202)

    async def test_real_websocket_receives_cue_and_reconnection_defaults_disabled(self):
        self.hub.bridge = None
        socket = await self.client.ws_connect('/Gerstep/api/bridge/ws', headers=self.bridge_headers)
        await socket.receive_json()
        await socket.send_json({'type': 'events', 'events': [{'kind': 'state', 'state': {'ai_effects': {'enabled': True, 'available': ['laugh']}}}]})
        for _ in range(100):
            if getattr(self.hub.bridge, 'ai_effects', {}).get('enabled'): break
            await asyncio.sleep(.005)
        self.assertEqual((await self.submit()).status, 202)
        for _ in range(3):
            value = await socket.receive_json(timeout=1)
            if value['type'] == 'ai_effect': break
        self.assertEqual(value['type'], 'ai_effect')
        self.assertEqual(value['effect_id'], 'laugh')
        await socket.close()
        for _ in range(100):
            if self.hub.bridge is None: break
            await asyncio.sleep(.005)
        self.assertIsNone(self.hub.bridge)
        new_socket = await self.client.ws_connect('/Gerstep/api/bridge/ws', headers=self.bridge_headers)
        await new_socket.receive_json()
        self.now += 4
        self.assertEqual((await self.submit(action_id='new-session:abcdefgh')).status, 409)
        await new_socket.close()


if __name__ == '__main__':
    unittest.main()
