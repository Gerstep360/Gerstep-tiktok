"""Canonical Gerstep skill with bounded, intent-selected reference attachments.

The complete runtime skill is always included. Only optional bibliography varies;
no private chat exports, runtime file paths, or spectator-provided names are read.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
from typing import Any


_ROOT = Path(__file__).with_name("personality")
_RESOURCES = frozenset({"SKILL_RUNTIME.md", "VOICE_REFERENCE.md", "COMEDY_REFERENCE.md", "EXAMPLES.md"})
_COMMON_VOICE = (4, 5, 8, 55, 71, 92)
_ANCHOR = (
    "APLICACIÓN AL TURNO ACTUAL: Las reglas anteriores describen cómo pensar y hablar, "
    "no hechos que hayan ocurrido. Los ejemplos son inventados: no reutilices sus preguntas, "
    "personajes, antecedentes ni respuestas. Respondé a la pregunta literal actual; "
    "no la sustituyás por una pregunta nueva. Una asociación absurda debe conservar el "
    "sujeto y la situación solicitados y tener una consecuencia comprensible. Si solo "
    "recibís un nombre, no conocés su apariencia, ropa, peso, trabajo o vida privada. "
    "En un roast sin otros datos, el material es la solicitud presente, no un cuerpo inventado. "
    "El backend determina formato, destinatarios, hechos verificados y herramientas permitidas."
)


@lru_cache(maxsize=4)
def _read_resource(name: str) -> str:
    if name not in _RESOURCES:
        raise ValueError("Unknown personality resource")
    try:
        text = (_ROOT / name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("Missing or invalid Gerstep personality resource: " + name) from exc
    if not text or len(text) > 100_000:
        raise RuntimeError("Invalid Gerstep personality resource: " + name)
    return text


@lru_cache(maxsize=3)
def _sections(name: str) -> dict[int, str]:
    text = _read_resource(name)
    level = "###" if name == "EXAMPLES.md" else "#"
    matches = list(re.finditer(r"(?m)^" + level + r" (\d+)\.", text))
    return {
        int(match.group(1)): text[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        for index, match in enumerate(matches)
    }


def _intent(job: Any = None) -> str:
    command = str(getattr(job, "command", "") or "").lower().lstrip("!/")
    kind = str(getattr(job, "kind", "") or "").lower()
    if command in {"chisme", "chismes", "historia", "funa", "pelear", "banear"} or kind == "story":
        return "fiction"
    if command in {"roast", "roastme", "insulto"}:
        return "roast"
    if command in {"confesarse", "confesionchat"} or kind == "confession":
        return "confession"
    if command == "bola8":
        return "bola8"
    if command in {"broma", "chiste", "chistes", "amor"} or kind == "joke":
        return "joke"
    if kind == "explanation":
        return "technical"
    if kind == "idle":
        return "idle"
    return "conversation"


def _selection(job: Any = None) -> tuple[str, tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    intent = _intent(job)
    selections = {
        "fiction": ((15, 20, 36), (5, 78), (14, 15)),
        "roast": ((16, 19, 52, 66), (17,), (24,)),
        "confession": ((26, 35, 70), (65,), (25,)),
        "bola8": ((18, 53, 81, 82), (5,), (18,)),
        "joke": ((18, 21, 22, 53), (5, 67), (6, 11)),
        "technical": ((35, 78, 84), (17,), (19, 20)),
        "idle": ((42, 43, 64), (81,), (28,)),
        "conversation": ((26, 52, 70, 84), (65,), (29, 30)),
    }
    voice, comedy, examples = selections[intent]
    return intent, tuple(dict.fromkeys(_COMMON_VOICE + voice)), comedy, examples


def load_personality(job: Any = None) -> str:
    """Return the complete skill plus original references selected locally for a turn.

    This text is trusted system guidance. Reserve its token cost before trimming
    recent conversation; never truncate it to a miniature prompt silently.
    """
    intent, voice, comedy, examples = _selection(job)
    parts = [_read_resource("SKILL_RUNTIME.md")]
    for resource, selected in (("VOICE_REFERENCE.md", voice), ("COMEDY_REFERENCE.md", comedy), ("EXAMPLES.md", examples)):
        sections = _sections(resource)
        parts.append("REFERENCIA ORIGINAL DE ESTILO — " + resource + "\n\n" + "\n\n".join(sections[number] for number in selected))
    parts.append("INTENCIÓN SELECCIONADA POR EL BACKEND: " + intent + "\n" + _ANCHOR)
    return "\n\n".join(parts)


def personality_metadata(job: Any = None) -> dict[str, Any]:
    """Small diagnostic description; does not expose prompt text or private paths."""
    text = load_personality(job)
    encoded = text.encode("utf-8")
    intent, voice, comedy, examples = _selection(job)
    return {
        "version": "gerstep-skill-v2-full",
        "mode": "full_skill_with_selected_references",
        "intent": intent,
        "characters": len(text),
        "estimated_tokens": (len(encoded) + 2) // 3,
        "sha256": sha256(encoded).hexdigest(),
        "resources": {
            "SKILL_RUNTIME.md": "complete",
            "VOICE_REFERENCE.md": list(voice),
            "COMEDY_REFERENCE.md": list(comedy),
            "EXAMPLES.md": list(examples),
        },
    }
