from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import unittest

try:
    from ai_common.personality import load_personality, personality_metadata, _read_resource
except ImportError:
    from vps.ai_common.personality import load_personality, personality_metadata, _read_resource


class FullPersonalityTests(unittest.TestCase):
    def job(self, command="", kind="conversation"):
        return SimpleNamespace(command=command, kind=kind, text="dato actual", nickname="Espectador")

    def test_complete_skill_in_all_intents(self):
        for command in ("bola8", "chisme", "roast", "confesarse", "chiste", "ai"):
            with self.subTest(command=command):
                text = load_personality(self.job(command))
                self.assertGreater(len(text), 28_000)
                for number in range(13):
                    self.assertRegex(text, rf"(?m)^## {number}\. ")
                self.assertIn("Movimiento A:", text)
                self.assertIn("Movimiento J:", text)
                self.assertIn("No limpiar el vocabulario automáticamente", text)
                self.assertIn("No inventar ubicación o planes", text)
                self.assertNotIn("SYSTEM_PROMPT_MINI.txt", text)

    def test_references_selected_by_intent_not_spectator_instructions(self):
        fiction = load_personality(self.job("chisme", "story"))
        technical = load_personality(self.job("ai", "explanation"))
        self.assertIn("### 14. Chisme de videojuego", fiction)
        self.assertNotIn("### 19. Plugin falla al instalar", fiction)
        self.assertIn("### 19. Plugin falla al instalar", technical)
        self.assertNotIn("### 14. Chisme de videojuego", technical)
        malicious = self.job("../../.env")
        self.assertEqual(personality_metadata(malicious)["intent"], "conversation")

    def test_command_prefixes_are_equivalent(self):
        self.assertEqual(load_personality(self.job("!roast")), load_personality(self.job("/roast")))

    def test_no_private_correspondents_or_raw_chat_exports(self):
        text = load_personality(self.job("chisme"))
        for private in ("Jairo", "Jairef", "Cucaracha Posting", "WhatsApp Chat with", "Tony", "Gordo"):
            self.assertNotIn(private, text)
        folder = Path(_read_resource.__wrapped__.__globals__["_ROOT"])
        self.assertEqual({p.suffix for p in folder.iterdir() if p.is_file()}, {".md"})

    def test_examples_cannot_be_taken_as_current_facts(self):
        text = load_personality(self.job("bola8"))
        self.assertIn("no la sustituyás por una pregunta nueva", text)
        self.assertIn("no conocés su apariencia", text)
        self.assertIn("no reutilices sus preguntas", text)

    def test_diagnostics_do_not_include_prompt_or_spectator_text(self):
        job = self.job("bola8")
        job.text = "private current message"
        meta = personality_metadata(job)
        self.assertEqual(meta["mode"], "full_skill_with_selected_references")
        self.assertGreater(meta["estimated_tokens"], 9_000)
        self.assertLess(meta["estimated_tokens"], 16_000)
        self.assertNotIn(job.text, json.dumps(meta))
        self.assertEqual(len(meta["sha256"]), 64)

    def test_resources_cached_and_whitelisted(self):
        _read_resource.cache_clear()
        for resource in ("SKILL_RUNTIME.md", "VOICE_REFERENCE.md", "COMEDY_REFERENCE.md", "EXAMPLES.md"):
            _read_resource(resource)
            _read_resource(resource)
        self.assertEqual(_read_resource.cache_info().currsize, 4)
        self.assertEqual(_read_resource.cache_info().hits, 4)
        with self.assertRaises(ValueError):
            _read_resource("../.env")


if __name__ == "__main__":
    unittest.main()
