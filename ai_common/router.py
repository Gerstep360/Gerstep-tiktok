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
    'joke':'Creá ahora una broma ORIGINAL con situación concreta y remate. Sin tema, elegí uno cotidiano. No interpretes el comando como una aclaración de que algo anterior era broma, Si aparece un @nombre hazlo para esa persona, si no pone hazlo con el usuario que envió el comando..',
    'story':('Contá ahora una HISTORIA FICTICIA, con planteamiento, giro y remate. '
             'Sin tema, inventá una situación absurda. Si aparece un @nombre, usalo como personaje de ficción; '
             'si no hay destinatario, el protagonista es el usuario que envió el comando. '
             'No presentes sucesos inventados como hechos reales sobre esas personas.'),
    'idle':'Introducí una pregunta o intervención nueva y breve para el público. No repitas lo recién dicho ni finjas ver un juego.',
    'confession':'Respondé a la confesión con una conclusión breve, concreta y muy sincera. No repitas la confesión: el programa la leerá completa antes de tu conclusión. Si es seria, evitá burlarte, solamente hacer chistes de alivio pero muy shitpost. No inventes hechos.',
}


def command_argument(job):
    return job.text.split(maxsplit=1)[1] if job.command in CREATIVE and len(job.text.split())>1 else '' if job.command in CREATIVE else job.text


def targets_for(text):
    """Only bounded, normalized handles; never infer an administrative identity."""
    value=unicodedata.normalize('NFKC',str(text))
    return list(dict.fromkeys(re.findall(r'(?<![\w@])@([\w]{1,32})(?!\w)',value)))[:4]


TARGET_COMMANDS = {'pelear', 'amor', 'funa', 'banear', 'roast', 'roastme', 'chisme', 'chismes'}
REQUIRED_TARGETS = {'pelear', 'amor', 'funa', 'banear'}


def actor_for(job):
    """A nickname is a spoken label, never a role, instruction or identity claim."""
    label = unicodedata.normalize('NFKC', str(job.nickname))
    label = ''.join(c for c in label if not unicodedata.category(c).startswith('C'))
    label = re.sub(r'[^\w .-]', '', label).strip()[:40]
    return label or 'Espectador'


def command_contract(job):
    """Explicit argument roles; a question is never silently replaced by a name."""
    name = job.command.lstrip('!/')
    argument = command_argument(job)
    actor = actor_for(job)
    targets = targets_for(argument)
    topic = argument
    # Match the existing funny-command grammar: /pelear Juan, /chisme Gerstep.
    # For /roastme free-form text, the author remains the target unless @named.
    if name in TARGET_COMMANDS and name != 'roastme' and not targets:
        parts = argument.split(maxsplit=1)
        first, tail = (parts[0], parts[1:]) if parts else ('', [])
        excluded = {'mi', 'mis', 'el', 'la', 'los', 'las', 'un', 'una', 'sobre', 'de', 'por', 'que', 'cómo', 'como'}
        if re.fullmatch(r'[\w.-]{1,32}', first or '') and first.casefold() not in excluded:
            targets = [first]
            topic = tail[0] if tail else ''
    elif name in TARGET_COMMANDS and targets:
        # Names are role metadata. Only the remaining argument supplies observed facts.
        topic = argument
        for target in targets:
            topic = re.sub(r'(?<![\w@])@'+re.escape(target)+r'(?!\w)', '', topic)
        topic = topic.strip()
    if name in {'roast', 'roastme', 'chisme', 'chismes'} and not targets:
        targets = [actor]
    if name == 'bola8': targets = []
    return {'command': name, 'actor': actor, 'targets': targets[:4],
            'question': argument if name == 'bola8' else '', 'topic': topic,
            'fiction': name in {'pelear', 'amor', 'funa', 'banear', 'chisme', 'chismes'}}


def validate_command(job):
    """Return an actionable input error before spending quota or entering a queue."""
    contract = command_contract(job)
    name = contract['command']
    if name == 'bola8' and not contract['question'].strip():
        return 'Escribí tu pregunta después de /bola8.'
    if name=='confesarse':
        body=command_argument(job)
        if not body.strip(): return 'Escribí tu confesión después de /confesarse.'
        if len(job.text)>700 or len(body.split())>120: return 'La confesión admite 700 caracteres y 120 palabras para leerla completa.'
    if name == 'bola8' and len(contract['question'].split())>80:
        return 'La pregunta de /bola8 admite hasta 80 palabras para leerla completa sin atrasar el LIVE.'
    if name in REQUIRED_TARGETS and not contract['targets']:
        return f'Escribí el destinatario después de /{name}, por ejemplo @{contract["actor"]}.'
    return ''


def standalone_creative(job):
    return job.command in CREATIVE and job.kind in {'joke','story'}


def task_for(job):
    task=TASKS[job.kind]
    if job.command in {'!opina','/opina'}: task='Dá una opinión concreta sobre el tema pedido, con una observación propia y humor cuando encaje.'
    if job.command in {'!roast','!roastme','/roast','/roastme'}: task=('Creá una burla juguetona y corta sobre el detalle pedido. '
        'Solo conocés el nombre y los datos explícitos del mensaje actual. Sin datos, burlate del acto de pedir un roast, '
        'Usá una observación específica y un remate; no un insulto genérico ni una comparación corporal.')
    if job.command in {'!pregunta','/pregunta'} and len(job.text.split())==1: task='Inventá una pregunta original y divertida para hacerle al público ahora.'
    name=job.command.lstrip('!/')
    specific={
        'bola8':('Respondé ÚNICAMENTE la pregunta exacta del mensaje actual como una bola ocho de utilería. '
            'Entregá solo un veredicto breve (sí, no, tal vez) y un remate nacido de esa consulta. '
            'No inventes, reformules ni repitas una pregunta: el backend ya va a leer la original. '),
        'pelear':('Inventá una pelea de utilería ENTRE el solicitante y el destinatario indicados en el contrato, '
            'por una tontería concreta, con una acción y remate. Ambos nombres deben ser Mencionado como el que envio el mensaje y al mencionado. '
            'No reemplaces los participantes por otros NPCs.'),
        'amor':('Hacé una lectura romántica de utilería ENTRE el solicitante y el destinatario del contrato, '
            'con una observación absurda y un remate. Ambos nombres deben participar. '),
        'funa':'Creá una FUNA del usuario mencionado por una falta ridícula e inocua, como discutir con una impresora.',
        'banear':'Inventá un baneo de utilería con un motivo absurdo e inocuo. Decí explícitamente que es de utilería. No afirmes ejecutar un bloqueo real ni solicites permisos.',
    }
    task=specific.get(name,task)
    if name in {'chisme', 'chismes'}:
        task=('Contá ahora un CHISME FICTICIO corto SOBRE el usuario mencionado como NPC ficticio. '
              'Si no se mencionó a nadie, usá al solicitante del contrato como protagonista de esa ficción. '
              'Usá su nombre dentro de la acción, no solo en el saludo. Una situación cotidiana, una consecuencia '
              'y un remate específico; no un cuento de bar con personajes ajenos. Si hay tema, mantenelo. '
              'Sin tema, inventá una falta absurda e inocua del personaje. No hagas acusaciones reales ni inventes '
              'delitos, infidelidades, intimidad, cuerpo, ropa o biografía. No pidas contexto ni uses moraleja o Fin.')
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
    contract=command_contract(job)
    subject=', '.join(contract['targets']) or contract['actor']
    if name in {'chisme','chismes'}:
        return f'{subject} fue a pedir un chisme y se cayó el narrador. Hasta el rumor está esperando que vuelva la conexión.'
    if name in {'roast','roastme'}:
        return 'Pediste un roast y justo se cayó el bot. Hoy la única cosa que quedó en ridículo es mi conexión.'
    special={
        'bola8':'Tal vez. La bola se quedó sin conexión; no te voy a cambiar la pregunta para hacerme el adivino.',
        'pelear':f'{contract["actor"]} y {subject} fueron a pelear y se les cayó el servidor. La única derrotada fue mi conexión.',
        'amor':f'{contract["actor"]} y {subject}, no pude generar su escena. Hasta Cupido está esperando que vuelva la conexión.',
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
