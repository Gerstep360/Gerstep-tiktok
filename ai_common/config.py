"""One operational configuration from .env/environment; secrets stay in RAM."""
from dataclasses import dataclass, field, fields
import math
import os
from pathlib import Path
import re
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def read_env(path=ROOT / '.env'):
    """Small literal parser, no interpolation, code execution or environment mutation."""
    values = {}
    try:
        if Path(path).stat().st_size > 65536: return values
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
            if not match: continue
            key, value = match.groups()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            else: value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
            values[key] = value
    except (OSError, UnicodeError): pass
    return values


@dataclass(slots=True)
class AIConfig:
    enabled: bool = True
    api_key: str = field(default='', repr=False)
    base_url: str = 'https://integrate.api.nvidia.com/v1'
    model: str = 'nvidia/nemotron-3.5-lightning-30b-a3b'
    requests_per_minute: int = 30
    tokens_per_minute: int = 12000
    reserved_requests: int = 3
    reserved_tokens: int = 1000
    concurrency: int = 1
    event_queue_size: int = 24
    queue_size: int = 8
    timeout: float = 8.0
    first_token_timeout: float = 4.0
    retries: int = 1
    user_cooldown: float = 12.0
    command_cooldown: float = 3.0
    context_tokens: int = 1600
    memory_turns: int = 32
    memory_seconds: float = 300.0
    direct_ttl: float = 25.0
    creative_ttl: float = 35.0
    idle_ttl: float = 12.0
    idle_enabled: bool = True
    idle_seconds: float = 90.0
    idle_ai_every: int = 3
    metrics: bool = True
    thinking: bool = False
    automatic_questions: bool = True
    tts_queue_size: int = 6
    tts_prepared_audio: int = 1
    tts_timeout: float = 6.0
    tts_workers: int = 1  # One ordered synthesis stage; parallel with AI/playback.
    max_speech_seconds: float = 45.0
    output_tokens: dict = field(default_factory=lambda: {'reaction':60,'joke':120,'conversation':180,'explanation':320,'story':400})

    def __post_init__(self):
        bounds = {'requests_per_minute':(1,120), 'tokens_per_minute':(1000,100000), 'reserved_requests':(0,20),
                  'concurrency':(1,3), 'event_queue_size':(4,128), 'queue_size':(1,24), 'timeout':(1,30),
                  'first_token_timeout':(.1,15), 'retries':(0,2), 'user_cooldown':(0,300),
                  'command_cooldown':(0,60), 'context_tokens':(700,4000), 'memory_turns':(2,128),
                  'memory_seconds':(30,1800), 'direct_ttl':(2,60), 'creative_ttl':(2,90), 'idle_ttl':(1,30),
                  'idle_seconds':(30,600), 'idle_ai_every':(2,20), 'tts_queue_size':(4,20),
                  'tts_prepared_audio':(1,2), 'tts_timeout':(1,12), 'tts_workers':(1,1), 'max_speech_seconds':(8,60)}
        for name, (low, high) in bounds.items():
            value = getattr(self,name)
            if not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError(f'Configuración IA inválida: {name}')
            setattr(self,name,max(low,min(high,value)))
        self.reserved_requests = min(self.reserved_requests,max(0,self.requests_per_minute-1))
        self.reserved_tokens = max(0,min(int(self.reserved_tokens),self.tokens_per_minute//2))
        self.first_token_timeout = min(self.first_token_timeout,self.timeout)
        parsed = urlparse(self.base_url)
        if (parsed.scheme != 'https' or parsed.hostname != 'integrate.api.nvidia.com' or parsed.port not in (None,443)
                or parsed.path.rstrip('/') != '/v1' or parsed.username or parsed.query or parsed.fragment):
            raise ValueError('El endpoint de IA debe ser https://integrate.api.nvidia.com/v1.')
        self.base_url = self.base_url.rstrip('/')
        if not re.fullmatch(r'[a-zA-Z0-9_.\-/]{1,160}',self.model): raise ValueError('Identificador de modelo inválido.')
        self.output_tokens = {kind:max(16,min(800,int(self.output_tokens.get(kind,default))))
                              for kind,default in {'reaction':60,'joke':120,'conversation':180,'explanation':320,'story':400}.items()}

    @classmethod
    def from_env(cls, path=ROOT / '.env'):
        env = read_env(path) | dict(os.environ)
        values = {}
        prototype = cls()
        for info in fields(cls):
            if info.name in ('api_key','output_tokens'): continue
            raw = env.get('GERSTEP_AI_' + info.name.upper())
            if raw is None: continue
            default = getattr(prototype,info.name)
            try:
                if isinstance(default,bool):
                    if raw.casefold() not in ('true','false','1','0','yes','no','on','off'): raise ValueError()
                    values[info.name] = raw.casefold() in ('true','1','yes','on')
                elif isinstance(default,int): values[info.name] = int(raw)
                elif isinstance(default,float): values[info.name] = float(raw)
                else: values[info.name] = raw
            except ValueError: raise ValueError(f'Configuración IA inválida: GERSTEP_AI_{info.name.upper()}') from None
        values['output_tokens'] = prototype.output_tokens.copy()
        for kind in values['output_tokens']:
            raw=env.get('GERSTEP_AI_TOKENS_'+kind.upper())
            if raw is not None:
                try: values['output_tokens'][kind]=int(raw)
                except ValueError: raise ValueError(f'Presupuesto IA inválido: {kind}') from None
        values['api_key'] = env.get('NVIDIA_API_KEY') or env.get('nvidia_api') or env.get('NVIDIA_API') or ''
        return cls(**values)
