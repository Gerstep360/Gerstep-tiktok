import asyncio
import json
import time
import unittest

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

try:
    from ai_common.client import NvidiaClient, Unavailable
    from ai_common.config import AIConfig
    from ai_common.quota import Budget
    from ai_common.tools import SOUND_IDS, ToolCallBuffer, sound_tools
except ModuleNotFoundError:
    from vps.ai_common.client import NvidiaClient, Unavailable
    from vps.ai_common.config import AIConfig
    from vps.ai_common.quota import Budget
    from vps.ai_common.tools import SOUND_IDS, ToolCallBuffer, sound_tools


def call(arguments='{"effect_id":"laugh"}', name='queue_sound', index=0):
    return {'index': index, 'id': 'call_test', 'type': 'function',
            'function': {'name': name, 'arguments': arguments}}


class ToolValidationTests(unittest.TestCase):
    def test_schema_exposes_only_fixed_action_and_no_url_paths_or_timing(self):
        tool = sound_tools()[0]['function']
        self.assertEqual(tool['name'], 'queue_sound')
        self.assertEqual(tool['parameters']['properties']['effect_id']['enum'], list(SOUND_IDS))
        self.assertFalse(tool['parameters']['additionalProperties'])
        self.assertEqual(set(tool['parameters']['properties']), {'effect_id', 'spoken_text'})

    def test_streamed_name_arguments_and_fixed_timing(self):
        buffer = ToolCallBuffer()
        buffer.feed([call('{"effect_', 'queue_')])
        buffer.feed([{'index': 0, 'function': {'name': 'sound', 'arguments': 'id":"laugh"}'}}])
        action, = buffer.actions(spoken_text='The complete joke.')
        self.assertEqual(action.effect_id, 'laugh')
        self.assertEqual(action.timing, 'after_voice')

    def test_invalid_tool_arguments_are_fail_closed(self):
        values = ['not JSON', 'null', '[]', '{"effect_id":"../sounds/risa.wav"}',
                  '{"effect_id":"https://evil.test"}', '{"effect_id":"laugh","url":"https://evil.test"}',
                  '{"effect_id":"laugh","timing":"interrupt"}', '{"effect_id":1}',
                  '{"effect_id":"laugh","spoken_text":1}', '{"effect_id":"laugh","spoken_text":""}',
                  '{"effect_id":"laugh","effect_id":"shock"}']
        for arguments in values:
            with self.subTest(arguments=arguments):
                buffer = ToolCallBuffer()
                buffer.feed([call(arguments)])
                self.assertEqual(buffer.actions(spoken_text='Voice.'), ())

    def test_unknown_multiple_and_oversized_calls_never_execute_partial_action(self):
        cases = [[call(name='shell')], [call(), call(index=1)], [call(index=True)],
                 [call('x' * 16385)], [call(index=1)], [None], {'index': 0}]
        for fragments in cases:
            buffer = ToolCallBuffer()
            buffer.feed(fragments)
            self.assertEqual(buffer.actions(spoken_text='Voice.'), ())

    def test_single_call_id_is_bound_and_no_voice_means_no_action(self):
        buffer = ToolCallBuffer()
        buffer.feed([call()])
        self.assertEqual(buffer.actions(spoken_text=' '), ())
        buffer.feed([{'index': 0, 'id': 'different'}])
        self.assertEqual(buffer.actions(spoken_text='Voice.'), ())

    def test_tool_speech_is_bounded_data_and_content_has_precedence(self):
        buffer = ToolCallBuffer()
        buffer.feed([call(json.dumps({'effect_id': 'laugh', 'spoken_text': 'La respuesta real.'}))])
        self.assertEqual(buffer.spoken_text(), 'La respuesta real.')
        self.assertEqual(buffer.spoken_text('Contenido canónico.'), 'Contenido canónico.')
        full = ToolCallBuffer()
        full.feed([call(json.dumps({'effect_id': 'laugh', 'spoken_text': 'x' * 2400}))])
        self.assertEqual(len(full.spoken_text()), 2400)
        invalid = ToolCallBuffer()
        invalid.feed([call(json.dumps({'effect_id': 'laugh', 'spoken_text': 'x' * 2401}))])
        self.assertEqual(invalid.spoken_text(), '')
        self.assertEqual(invalid.actions(spoken_text='Voice.'), ())


class LocalSession:
    def __init__(self, session, url):
        self.session, self.url = session, url

    def post(self, url, **kwargs):
        assert url == 'https://integrate.api.nvidia.com/v1/chat/completions'
        return self.session.post(self.url, **kwargs)


class StreamingToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.mode = 'valid'

        async def handler(request):
            self.calls.append(await request.json())
            response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
            await response.prepare(request)
            if self.mode == 'slow':
                await asyncio.sleep(.15)
            fragments = [call('{"effect_id":', 'queue_sound'),
                         {'index': 0, 'function': {'arguments': '"laugh"}'}}]
            if self.mode == 'malicious':
                fragments = [call('{"effect_id":"laugh","url":"https://evil.test"}')]
            if self.mode == 'multiple':
                fragments = [call(), call(index=1)]
            if self.mode in ('tool_voice', 'both_voice'):
                fragments = [call(json.dumps({'effect_id': 'laugh', 'spoken_text': 'Voz desde herramienta.'}))]
            chunks = [{'choices': [{'delta': {'tool_calls': [part]}}]} for part in fragments]
            if self.mode not in ('tool_only', 'tool_voice'):
                chunks.insert(0, {'choices': [{'delta': {'content': 'Respuesta cómica completa.'}}]})
            chunks.append({'choices': [], 'usage': {'prompt_tokens': 123, 'completion_tokens': 21, 'total_tokens': 144}})
            try:
                for chunk in chunks:
                    await response.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                await response.write(b'data: [DONE]\n\n')
            except (ConnectionError, RuntimeError):
                pass
            return response

        app = web.Application()
        app.router.add_post('/completion', handler)
        self.server = TestServer(app)
        await self.server.start_server()
        self.session = ClientSession()
        self.config = AIConfig(api_key='dummy', retries=0)
        self.budget = Budget(self.config)
        self.client = NvidiaClient(self.config, self.budget,
                                   session=LocalSession(self.session, str(self.server.make_url('/completion'))))

    async def asyncTearDown(self):
        await self.client.close()
        await self.session.close()
        await self.server.close()

    async def generate(self, enabled=True):
        return await self.client.generate([{'role': 'system', 'content': 'Persona.'},
                                           {'role': 'user', 'content': 'A joke.'}],
                                          120, priority=3, expires=time.monotonic() + 2,
                                          tools_enabled=enabled)

    async def test_optional_schema_single_request_and_measured_usage(self):
        completion = await self.generate()
        self.assertEqual(completion.text, 'Respuesta cómica completa.')
        self.assertEqual(completion.actions[0].effect_id, 'laugh')
        self.assertEqual(completion.actions[0].timing, 'after_voice')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['tool_choice'], 'auto')
        self.assertEqual(self.calls[0]['tools'][0]['function']['name'], 'queue_sound')
        self.assertEqual(self.budget.snapshot()['tokens_window'], 144)

    async def test_default_disabled_cannot_return_actions(self):
        completion = await self.generate(False)
        self.assertEqual(completion.actions, ())
        self.assertNotIn('tools', self.calls[0])
        self.assertNotIn('tool_choice', self.calls[0])

    async def test_operator_probe_can_force_only_the_declared_tool(self):
        self.mode='tool_voice'
        result=await self.client.generate([{'role':'user','content':'Broma'}],120,priority=3,
            expires=time.monotonic()+2,tools_enabled=True,force_tool=True)
        self.assertEqual(self.calls[0]['tool_choice'],{'type':'function','function':{'name':'queue_sound'}})
        self.assertEqual(result.actions[0].effect_id,'laugh')
        self.assertEqual(len(self.calls),1)

    async def test_bad_action_does_not_destroy_valid_voice(self):
        for mode in ('malicious', 'multiple'):
            self.mode = mode
            completion = await self.generate()
            self.assertEqual(completion.actions, ())
            self.assertEqual(completion.text, 'Respuesta cómica completa.')

    async def test_tool_only_response_fails_without_execution_or_second_request(self):
        self.mode = 'tool_only'
        with self.assertRaises(Unavailable) as error:
            await self.generate()
        self.assertEqual(error.exception.reason, 'incomplete_stream')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.client.active, 0)
        self.assertEqual(self.budget.snapshot()['tokens_window'], 144)

    async def test_tool_only_with_spoken_text_yields_single_voice_and_action(self):
        self.mode = 'tool_voice'
        completion = await self.generate()
        self.assertEqual(completion.text, 'Voz desde herramienta.')
        self.assertEqual(completion.actions[0].effect_id, 'laugh')
        self.assertEqual(len(self.calls), 1)

    async def test_content_wins_when_tool_also_contains_spoken_text(self):
        self.mode = 'both_voice'
        completion = await self.generate()
        self.assertEqual(completion.text, 'Respuesta cómica completa.')
        self.assertEqual(len(completion.actions), 1)
        self.assertEqual(len(self.calls), 1)

    async def test_no_first_token_is_bounded_even_with_tools_enabled(self):
        self.mode = 'slow'
        self.config.first_token_timeout = .025
        with self.assertRaises(Unavailable) as error:
            await self.generate()
        self.assertEqual(error.exception.reason, 'timeout')
        self.assertEqual(self.client.active, 0)
        self.assertEqual(len(self.calls), 1)
