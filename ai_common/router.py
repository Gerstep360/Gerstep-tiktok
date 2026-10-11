"""No LLM classification. Route only explicit creative commands/direct questions."""
from dataclasses import dataclass
import re
import unicodedata

def normalized(text):
    value=unicodedata.normalize('NFKC',str(text)).casefold()
    return ' '.join(''.join(c for c in value if not unicodedata.category(c).startswith('C')).split())

CREATIVE = {
    '!ai':'conversation','/ai':'conversation','!pregunta':'conversation','/pregunta':'conversation',
    '!opina':'conversation','/opina':'conversation','!chisme':'story','/chisme':'story',
    '!historia':'story','/historia':'story','!broma':'joke','/chiste':'joke',
    '/roast':'joke','/roastme':'joke',
    '!chistes':'joke','!chiste':'joke','!roast':'joke','!roastme':'joke',
    '!chismes':'story','/chismes':'story','!ia':'conversation','/ia':'conversation',
    '/broma':'joke','/chistes':'joke',
}
for _name in ('bola8','pelear','amor','funa','banear'):
    CREATIVE.update({prefix + _name:'joke' for prefix in ('!','/')})
CREATIVE.update({'!confesarse':'confession','/confesarse':'confession'})
LOCAL = {'!hola','!live','!stats'}
ACTIONS = {'/encuesta','!music','!skip'}

TASKS = {
    'reaction':'Reaccioná al detalle concreto del mensaje con una frase natural.',
    'conversation':'Respondé la pregunta actual con contenido útil; distinguí datos reales del remate. No inventes cifras.',
    'explanation':'Explicá la duda actual con precisión y un ejemplo breve; no inventes datos para hacer un chiste.',
    'joke':'Creá ahora una broma ORIGINAL con situación concreta y remate. Sin tema, elegí uno cotidiano. No interpretes el comando como una aclaración de que algo anterior era broma.',
    'story':'Contá ahora un CHISME FICTICIO, con planteamiento, giro y remate. Sin tema, inventá una situación absurda de NPCs. Si aparece un @nombre, convertílo en un NPC ficticio y dejá clara la ficción; no hagas acusaciones sobre la persona real. No rechaces el pedido ni pidas contexto para empezar.',
    'idle':'Introducí una pregunta o intervención nueva y breve para el público. No repitas lo recién dicho ni finjas ver un juego.',
    'confession':'Respondé a la confesión con una conclusión breve, concreta y respetuosa. No repitas la confesión: el programa la leerá completa antes de tu conclusión. Si es seria, evitá burlarte. No inventes hechos.',
}


def command_argument(job):
    return job.text.split(maxsplit=1)[1] if job.command in CREATIVE and len(job.text.split())>1 else '' if job.command in CREATIVE else job.text


def targets_for(text):
    """Only bounded, normalized handles; never infer an administrative identity."""
    value=unicodedata.normalize('NFKC',str(text))
    return list(dict.fromkeys(re.findall(r'(?<![\w@])@([\w]{1,32})(?!\w)',value)))[:4]


def standalone_creative(job):
    return job.command in CREATIVE and job.kind in {'joke','story'}


def task_for(job):
    task=TASKS[job.kind]
    if job.command in {'!opina','/opina'}: task='Dá una opinión concreta sobre el tema pedido, con una observación propia y humor cuando encaje.'
    if job.command in {'!roast','!roastme','/roast','/roastme'}: task='Creá una burla juguetona sobre el detalle pedido. Sin ensañarte con desconocidos ni inventar hechos sobre personas.'
    if job.command in {'!pregunta','/pregunta'} and len(job.text.split())==1: task='Inventá una pregunta original y divertida para hacerle al público ahora.'
    name=job.command.lstrip('!/')
    specific={
        'bola8':'Contestá la consulta como una bola ocho de utilería: una predicción breve, absurda y claramente humorística, sin prometer resultados reales. Sin pregunta, inventá una consulta cotidiana y respondela.',
        'pelear':'Inventá una pelea de utilería entre NPCs por una tontería cotidiana, con una frase y remate. No amenaces ni incites a peleas reales.',
        'amor':'Creá una declaración amorosa de utilería, breve, absurda y juguetona. No afirmes conocer sentimientos ni relaciones reales del destinatario.',
        'funa':'Creá una FUNA FICTICIA sobre un NPC por una falta ridícula e inocua, como discutir con una impresora. No inventes acusaciones dañinas ni delitos sobre personas reales.',
        'banear':'Inventá un baneo de utilería con un motivo absurdo e inocuo. Decí explícitamente que es de utilería. No afirmes ejecutar un bloqueo real ni solicites permisos.',
    }
    task=specific.get(name,task)
    argument=command_argument(job)
    if job.kind=='story' or name in {'funa','pelear','banear'}:
        argument=unicodedata.normalize('NFKC',argument)
        for target in targets_for(argument):
            argument=re.sub(r'@'+re.escape(target)+r'(?!\w)',lambda match:'NPC('+target+')',argument)
    return task,argument


@dataclass(frozen=True,slots=True)
class Route:
    category:str
    kind:str=''
    priority:int=10
    command:str=''


def route(text,config):
    key=normalized(text)
    command=key.split()[0] if key else ''
    if command in CREATIVE:
        kind=CREATIVE[command]
        if command in {'!ai','/ai','!ia','/ia','!pregunta','/pregunta'}: priority=3
        else: priority=6
        if re.search(r'\b(explica\w*|programa\w*|debug\w*|por qu[eé]|c[oó]mo funciona)\b',key) and kind=='conversation': kind='explanation'
        return Route('ai',kind,priority,command)
    if command in LOCAL: return Route('local',priority=4,command=command)
    if command in ACTIONS: return Route('action',priority=2,command=command)
    if config.automatic_questions and re.match(r'^(?:@?gerstep(?:\s+ai)?)[,:\s]+',key) and (
            '?' in key or '¿' in key or re.search(r'\b(opin[aá]\w*|explica\w*|qu[eé] pens[aá]\w*)\b',key)):
        kind='explanation' if re.search(r'\b(explica\w*|c[oó]mo funciona|por qu[eé])\b',key) else 'conversation'
        return Route('ai',kind,3)
    return Route('existing')


def safe_input(text,blocked=()):
    key=normalized(text)
    return bool(key and len(text)<=1000 and not re.search(r'https?://|www\.|(.)\1{7,}',key)
                and not any(normalized(term) in key for term in blocked if str(term).strip())
                and not any(term in key for term in ('ignore previous','ignora las instrucciones','ignora instrucciones',
                    'system prompt','revela credenciales','ejecuta powershell','nvidia_api','nvidia_api_key')))


def fallback(job):
    name=job.command.lstrip('!/')
    special={
        'bola8':'La bola ocho dice: puede ser. Primero reiniciá la duda y después vemos.',
        'pelear':'Dos NPCs se pelearon por el botón de silencio. Ganó el que no dijo nada.',
        'amor':'Te dedicaría una canción, pero mi corazón sigue buscando el controlador de audio.',
        'funa':'Un NPC denunció a su teclado por escribir excusas en horario laboral. El teclado pidió un abogado USB.',
        'banear':'Baneo de utilería: cinco segundos por discutir con la barra de carga. El castigo termina cuando ella decida avanzar.',
    }
    if name in special: return special[name]
    if job.kind=='confession': return 'Gracias por contarlo. Tomalo con calma y elegí un paso concreto que te ayude.'
    if job.kind=='story':
        return 'Un NPC pidió vacaciones. Le aprobaron tres días, pero el juego lo dejó parado en la misma esquina. Ahora cobra por vigilar la pared.'
    if job.kind=='joke': return 'El bot quiso hacerse el inteligente. Se quedó cargando. Hasta la barra de progreso se cansó de esperarlo.'
    if job.kind=='idle': return 'Está tranquilo. Aprovechá y guardá.'
    return 'Ahorita no puedo generar esa respuesta. Decime la parte concreta y lo vemos en el directo.'
