"""Reusable streaming NVIDIA client; optional validated proposals, never execution."""
import asyncio
from collections import Counter, deque
from dataclasses import dataclass
import json
import random
import time

import aiohttp
from .memory import estimate_tokens
from .tools import TOOL_INSTRUCTION, ToolCallBuffer, sound_tools


class Unavailable(Exception):
    def __init__(self, reason):
        self.reason=reason
        super().__init__(reason)


@dataclass(slots=True)
class Completion:
    text:str
    first_token_ms:float
    total_ms:float
    usage:dict | None=None
    actions:tuple=()


class NvidiaClient:
    def __init__(self,config,budget,*,session=None):
        self.config,self.budget=config,budget
        self.session=session
        self.owns_session=session is None
        self.stats=Counter()
        self.first_tokens=deque(maxlen=128)
        self.generations=deque(maxlen=128)
        self.active=0

    async def close(self):
        if self.session and self.owns_session:
            await self.session.close()
            self.session=None

    async def generate(self,messages,max_tokens,*,priority,expires,tools_enabled=False,force_tool=False):
        if force_tool and not tools_enabled: raise ValueError('Forced tool requires declared tools')
        if not self.config.enabled or not self.config.api_key: raise Unavailable('offline')
        if self.session is None:
            self.session=aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=self.config.concurrency,ttl_dns_cache=300),
                timeout=aiohttp.ClientTimeout(total=self.config.timeout,connect=3,sock_read=self.config.first_token_timeout),
                trust_env=False)
        request_messages=list(messages)
        if tools_enabled:
            request_messages.insert(1 if request_messages and request_messages[0].get('role')=='system' else 0,
                                    {'role':'system','content':TOOL_INSTRUCTION})
        payload={'model':self.config.model,'messages':request_messages,'max_tokens':max_tokens,
                 'temperature':self.config.temperature,'top_p':self.config.top_p,'stream':True,'stream_options':{'include_usage':True}}
        if tools_enabled:
            payload['tools']=sound_tools()
            payload['tool_choice']={'type':'function','function':{'name':'queue_sound'}} if force_tool else 'auto'
        if self.config.model=='nvidia/nemotron-3.5-lightning-30b-a3b':
            payload['chat_template_kwargs']={'enable_thinking':self.config.thinking}
        began=time.monotonic()
        deadline=min(expires,began+self.config.timeout)
        for attempt in range(self.config.retries+1):
            if time.monotonic()>=deadline: raise Unavailable('expired')
            estimate=estimate_tokens(request_messages)+max_tokens
            if tools_enabled: estimate+=estimate_tokens(payload['tools'])
            entry=self.budget.reserve(estimate,priority=priority)
            if entry is None: raise Unavailable('quota')
            usage=None
            first=None
            self.active+=1
            try:
                async with asyncio.timeout(max(.01,deadline-time.monotonic())):
                    async with self.session.post(self.config.base_url+'/chat/completions',json=payload,
                        headers={'Authorization':'Bearer '+self.config.api_key},allow_redirects=False) as response:
                        self.stats['requests']+=1
                        if response.status==429:
                            self.stats['http_429']+=1
                            self.budget.backoff(response.headers.get('Retry-After'),seconds=1)
                            # Shared cooldown protects every worker; don't sleep behind a long Retry-After.
                            raise Unavailable('http_429')
                        if response.status in (401,403):
                            self.budget.backoff(seconds=60)
                            raise Unavailable('authentication')
                        if response.status>=500:
                            self.stats['server_errors']+=1
                            raise Unavailable('server')
                        if response.status!=200: raise Unavailable('http_'+str(response.status))
                        chunks=[]
                        proposed=ToolCallBuffer()
                        first=None
                        size=0
                        ended=False
                        while True:
                            timeout = max(.001,(began+self.config.first_token_timeout-time.monotonic())) if first is None else max(.001,deadline-time.monotonic())
                            line=await asyncio.wait_for(response.content.readline(),timeout)
                            if not line: break
                            if len(line)>65536: raise Unavailable('large_frame')
                            line=line.strip()
                            if not line.startswith(b'data:'): continue
                            data=line[5:].strip()
                            if data==b'[DONE]':
                                ended=True
                                break
                            value=json.loads(data)
                            if not isinstance(value,dict): raise Unavailable('invalid_stream')
                            if isinstance(value.get('usage'),dict): usage=value['usage']
                            choices=value.get('choices') or []
                            if not choices: continue
                            if not isinstance(choices,list) or not isinstance(choices[0],dict): raise Unavailable('invalid_stream')
                            delta=choices[0].get('delta') or {}
                            if not isinstance(delta,dict): raise Unavailable('invalid_stream')
                            if tools_enabled and 'tool_calls' in delta:
                                proposed.feed(delta['tool_calls'])
                                if first is None and proposed.seen:
                                    first=(time.monotonic()-began)*1000
                            fragment=delta.get('content')
                            if isinstance(fragment,str) and fragment:
                                if first is None: first=(time.monotonic()-began)*1000
                                size+=len(fragment.encode('utf-8'))
                                if size>16000: raise Unavailable('large_response')
                                chunks.append(fragment)
                            if first is None and time.monotonic()-began>self.config.first_token_timeout:
                                raise Unavailable('first_token_timeout')
                        text=''.join(chunks)
                        if tools_enabled: text=proposed.spoken_text(text)
                        if not text.strip() or not ended: raise Unavailable('incomplete_stream')
                        elapsed=(time.monotonic()-began)*1000
                        if self.config.metrics:
                            self.first_tokens.append(first)
                            self.generations.append(elapsed)
                        self.stats['completed']+=1
                        actions=proposed.actions(spoken_text=text) if tools_enabled else ()
                        if tools_enabled and proposed.seen:
                            self.stats['tool_proposals' if actions else 'tool_rejected']+=1
                        return Completion(text,first,elapsed,usage,actions)
            except asyncio.CancelledError:
                self.stats['cancelled']+=1
                raise
            except (TimeoutError,aiohttp.ClientError,ValueError,TypeError,KeyError) as exc:
                self.stats['errors']+=1
                reason='timeout' if isinstance(exc,TimeoutError) else 'network_or_protocol'
                if attempt>=self.config.retries or first is not None or time.monotonic()>=began+self.config.first_token_timeout:
                    raise Unavailable(reason) from None
            except Unavailable as exc:
                self.stats['errors']+=1
                if exc.reason!='server' or attempt>=self.config.retries: raise
            finally:
                self.active-=1
                try: self.budget.settle(entry,usage)
                except (ValueError,TypeError): self.budget.settle(entry,None)
            delay=min(2,.3*(2**attempt))+random.uniform(0,.2)
            if time.monotonic()+delay>=deadline: raise Unavailable('deadline')
            await asyncio.sleep(delay)
            self.stats['retries']+=1
        raise Unavailable('unavailable')

    def snapshot(self):
        from .metrics import distribution
        return {'active':self.active,'stats':dict(self.stats),
                'first_token':distribution(self.first_tokens),'generation':distribution(self.generations)}
