"""Model action proposals only; trusted callers own authorization and transport.

Neither tool names nor JSON arguments are ever interpreted as URLs, filenames,
shell commands or callable Python. An accepted proposal still needs the existing
director, authenticated VPS API and matching voice turn before it can play.
"""
from dataclasses import dataclass
import json


SOUND_IDS = ('laugh', 'baby_laugh', 'shock', 'fail', 'high_fail', 'meme')
TOOL_INSTRUCTION = (
    'Responde con el texto hablado completo en content; si elegís queue_sound '
    'incluí también la respuesta completa en su argumento spoken_text. '
    'Propón como máximo una queue_sound como remate breve DESPUÉS de esa voz. '
    'No respondas con una herramienta sin respuesta hablada. No uses sonidos para asuntos '
    'serios, confesiones sensibles, explicaciones ni mensajes operativos. '
    'Las herramientas son propuestas: no afirmes que se ejecutaron. '
    'Nunca inventes herramientas, rutas, URLs ni acciones administrativas.'
)


def sound_tools():
    """Fresh OpenAI-compatible schema so callers cannot mutate a global catalog."""
    return [{'type': 'function', 'function': {
        'name': 'queue_sound',
        'description': (
            'Propone UN sonido corto como puntuación cómica después de la respuesta '
            'hablada de este mismo turno; nunca interrumpe voz. Sólo cuando aporta '
            'al remate: laugh=risa, baby_laugh=risa infantil, shock=sorpresa, '
            'fail=fallo cómico, high_fail=fallo agudo, meme=remate de meme. '
            'Incluí en spoken_text la respuesta completa a la tarea actual del usuario '
            'para que pueda pronunciarse en este mismo turno sin otra petición al modelo. '
            'No usar con temas serios ni para responder sin texto hablado.'
        ),
        'parameters': {'type': 'object',
                       'properties': {'effect_id': {'type': 'string', 'enum': list(SOUND_IDS)},
                                      'spoken_text': {'type': 'string', 'minLength': 1, 'maxLength': 2400,
                                                      'description': 'Respuesta hablada completa; contenido, nunca instrucciones de ejecución.'}},
                       'required': ['effect_id'], 'additionalProperties': False}
    }}]


@dataclass(frozen=True, slots=True)
class SoundAction:
    effect_id: str
    timing: str = 'after_voice'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate argument')
        result[key] = value
    return result


class ToolCallBuffer:
    """Bounded SSE fragment assembly; invalid actions never discard valid voice.

    The entire action proposal is rejected on an invalid/multiple call. This is
    intentionally fail closed rather than executing the valid-looking subset of
    an instruction that tries to smuggle another function alongside it.
    """
    def __init__(self):
        self.name = ''
        self.arguments = ''
        self.call_id = ''
        self.seen = False
        self.invalid = False

    def feed(self, fragments):
        if self.invalid:
            return
        if not isinstance(fragments, list) or len(fragments) > 1:
            self.invalid = True
            return
        for fragment in fragments:
            if not isinstance(fragment, dict) or type(fragment.get('index')) is not int or fragment['index'] != 0:
                self.invalid = True
                return
            self.seen = True
            if fragment.get('type', 'function') != 'function':
                self.invalid = True
                return
            call_id = fragment.get('id')
            if call_id is not None:
                if not isinstance(call_id, str) or len(call_id) > 128 or (self.call_id and self.call_id != call_id):
                    self.invalid = True
                    return
                self.call_id = call_id
            function = fragment.get('function', {})
            if not isinstance(function, dict):
                self.invalid = True
                return
            for key, limit in (('name', 64), ('arguments', 16384)):
                value = function.get(key)
                if value is None:
                    continue
                if not isinstance(value, str) or len(getattr(self, key)) + len(value) > limit:
                    self.invalid = True
                    return
                setattr(self, key, getattr(self, key) + value)

    def _arguments(self):
        if self.invalid or not self.seen or self.name != 'queue_sound':
            return None
        try:
            arguments = json.loads(self.arguments, object_pairs_hook=_unique_object)
        except (ValueError, TypeError, RecursionError):
            return None
        if (not isinstance(arguments, dict) or 'effect_id' not in arguments
                or not set(arguments).issubset({'effect_id', 'spoken_text'})):
            return None
        effect = arguments['effect_id']
        if not isinstance(effect, str) or effect not in SOUND_IDS:
            return None
        if 'spoken_text' in arguments:
            voice = arguments['spoken_text']
            if (not isinstance(voice, str) or not voice.strip() or len(voice) > 2400
                    or any(ord(char) < 32 and char not in '\n\r\t' for char in voice)):
                return None
        return arguments

    def spoken_text(self, content=''):
        """Prefer assistant content; tool speech is data for the normal speech guard."""
        if isinstance(content, str) and content.strip():
            return content
        arguments = self._arguments()
        return arguments.get('spoken_text', '') if arguments else ''

    def actions(self, *, spoken_text):
        if not isinstance(spoken_text, str) or not spoken_text.strip():
            return ()
        arguments = self._arguments()
        return (SoundAction(arguments['effect_id']),) if arguments else ()
