"""Operator-authorized AI voice delivery over the existing PC WebSocket."""
from collections import OrderedDict
import secrets
import time

from aiohttp import web
from .ai_actions import EFFECTS


KINDS = frozenset({'reaction','joke','story','conversation','explanation','confession','idle'})


class AIDelivery:
    def __init__(self):
        self.pending = OrderedDict()

    def available(self, hub):
        peer=hub.bridge
        if peer is None or getattr(peer.socket,'closed',False):
            raise web.HTTPConflict(text='Conectá el programa del PC antes de enviar voz.')
        if hub.domain.suspended or hub.cache.get('live',{}).get('emergency'):
            raise web.HTTPConflict(text='Las interacciones están suspendidas o hay una parada total.')
        if peer.queue.full():
            raise web.HTTPServiceUnavailable(text='El programa tiene intervenciones pendientes.')
        return peer

    def enqueue(self,hub,result,owner):
        peer=self.available(hub)
        text=result.get('text')
        kind=result.get('kind','conversation')
        if not isinstance(text,str) or not 1<=len(text)<=2400 or kind not in KINDS:
            raise ValueError('Respuesta de IA inválida para voz.')
        effect=result.get('effect_id','')
        if effect and effect not in EFFECTS: raise ValueError('Efecto no permitido.')
        now=time.time()
        self.prune()
        if len(self.pending)>=8: raise web.HTTPServiceUnavailable(text='Hay demasiadas voces pendientes.')
        action_id=secrets.token_hex(12)
        # The public page cannot submit this event. The ID is bound by our backend.
        message={'type':'ai_response','action_id':action_id,'turn_id':result['id'],
                 'kind':kind,'text':text,'effect_id':effect,'created':now,'expires':now+10,
                 'max_duration':60 if kind=='confession' else 45}
        peer.queue.put_nowait(message)
        self.pending[action_id]={'owner':owner,'status':'queued','until':now+90}
        return {'action_id':action_id,'status':'queued'}

    def acknowledge(self,action_id,status):
        self.prune()
        if action_id not in self.pending or status not in {'selected','answered','error'}: return False
        self.pending[action_id]['status']=status
        return True

    def prune(self):
        now=time.time()
        for key,value in list(self.pending.items()):
            if value['until']<=now: self.pending.pop(key,None)

    def clear(self):
        self.pending.clear()

    def snapshot(self,owner):
        self.prune()
        return [{'action_id':key,'status':value['status']} for key,value in self.pending.items() if value['owner']==owner]
