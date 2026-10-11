"""Private text testing, sharing the production router, prompt and HTTP client."""
import asyncio
import time
import uuid
from collections import deque
from .client import NvidiaClient, Unavailable
from .memory import Memory, PromptBuilder, prepare_answer, creative_output_rejected
from .queue import Job
from .quota import Budget
from .router import route, safe_input, fallback, command_argument


class PreviewChat:
    def __init__(self, config, *, budget=None, client=None):
        self.config = config
        self.budget = budget or Budget(config)
        self.client = client or NvidiaClient(config, self.budget)
        self.memory = Memory(config)
        self.prompts = PromptBuilder(config, self.memory)
        self.pending = deque(maxlen=8)
        self.active = False
        self.tasks = set()

    async def ask(self, text, owner='operator'):
        if not isinstance(text, str) or not safe_input(text) or len(text)>700:
            raise ValueError('Escribí hasta 700 caracteres, sin enlaces ni instrucciones administrativas.')
        if self.active: raise ValueError('Ya hay una prueba en curso.')
        task = asyncio.current_task()
        self.tasks.add(task)
        self.active = True
        try:
            classified = route(text, self.config)
            local = None
            if text.split()[0].lower() in {'!help','/help'}:
                local = 'IA: !ai, !pregunta, !opina, !chisme, !historia, !broma, !bola8, !chiste, !pelear, !amor, !roast, !funa, !banear, !confesarse. También con /. Locales: !hola, !live, !stats. Las pruebas no ejecutan acciones.'
            elif classified.category=='local':
                local = {'!hola':'Qué onda. Probá una pregunta.', '!live':'Estás en el chat privado de pruebas.',
                         '!stats':f"Se usaron {self.budget.snapshot().get('requests_window',0)} solicitudes en esta ventana."}[classified.command]
            elif text.startswith(('!','/')) and classified.category!='ai':
                local = 'Ese comando activa una función del LIVE. Este chat solo prueba respuestas de texto; no ejecuta acciones.'
            now = time.monotonic()
            job = Job(owner,text,'Gerstep',classified.kind or 'conversation',3,now,now+self.config.timeout,classified.command,id='preview:'+uuid.uuid4().hex)
            if job.kind=='confession' and not command_argument(job).strip():
                raise ValueError('Escribí tu confesión después de !confesarse.')
            if job.kind=='confession' and len(command_argument(job).split())>120:
                raise ValueError('La confesión admite hasta 700 caracteres y 120 palabras para leerla completa.')
            source = 'local'
            answer = local
            if answer is None:
                messages,tokens,words,_ = self.prompts.build(job)
                try:
                    result = await self.client.generate(messages,tokens,priority=3,expires=job.expires)
                    answer = prepare_answer(job,result.text,words=words,secret=self.config.api_key)
                    if not answer: raise Unavailable('unsafe_output')
                    source = 'fallback' if creative_output_rejected(job,result.text) else 'nvidia'
                except Unavailable:
                    answer = prepare_answer(job,fallback(job),words=words,secret=self.config.api_key)
                    source = 'fallback'
            self.pending.append((job,answer,time.monotonic()))
            return {'id':job.id,'text':answer,'source':source,'quota':self.budget.snapshot()}
        finally:
            self.active = False
            self.tasks.discard(task)

    def acknowledge(self, owner, turn_id):
        for job,text,created in list(self.pending):
            if job.id==turn_id and job.user==owner and time.monotonic()-created<60:
                self.pending.remove((job,text,created))
                self.memory.spoken(job,text)
                return True
        return False

    def snapshot(self):
        return {'configured':bool(self.config.api_key),'enabled':self.config.enabled,
                'model':self.config.model,'active':self.active,'quota':self.budget.snapshot()}

    async def close(self):
        tasks = [t for t in self.tasks if t is not asyncio.current_task()]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await self.client.close()
        self.pending.clear()
        self.memory.clear()
