#!/usr/bin/env python3
"""
Tests des images (core/images.py, actions/modules/files.py) : contrôle des images reçues (format réel, taille),
recherche limitée aux dossiers FILES_SEARCH_DIRS (mots, accents, motifs, fichiers cachés, profondeur, sortie du
dossier refusée), envoi au modèle (vision ou alerte), image montrée par l'assistant, agent externe et passerelle.
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.modules.files import SEARCH_FILES_ACTION, SHOW_IMAGE_ACTION
from core.assistant import AssistantCore
from core.config import Settings
from core.images import ImageError, decode_upload, decode_uploads, load_image, resolve_allowed, search_files, sniff_mime
from core.tools import ToolCall, ToolRegistry, _action_tool
from gateway.app import create_app
from llm.providers import LLMProvider, LLMResponse
from audio.tts import TextToSpeech
from tests.test_agents import VoicesTTS
from tests.test_gateway import FakeSTT

# Plus petit PNG valide (1 x 1 pixel)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class VisionLLM(LLMProvider):
    """« montre <chemin> » -> outil show_image ; sinon décrit ce qu'il a reçu (nombre d'images)."""

    def __init__(self, settings, vision=True):
        super().__init__(settings)
        self.model = "vue-test"
        self.vision = vision
        self.received = []

    @classmethod
    def describe(cls, settings):
        return "Vision"

    def accepts_images(self, model=None):
        return self.vision

    def chat(self, messages, *, tools=None, images=None, on_token=None, **kwargs):
        last = messages[-1]
        if last["role"] == "tool":
            return LLMResponse(text="Voici l'image.")
        self.received.append(list(images or []))
        prompt = last["content"] or ""
        if tools and prompt.startswith("montre "):
            return LLMResponse(tool_calls=[ToolCall("show_image", {"args": prompt[len("montre "):]}, id="c1")])
        return LLMResponse(text=f"{len(images or [])} image(s) : {prompt}")


class ImagesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.root = tmp / "Images"
        (self.root / "Vacances été" / "Plage").mkdir(parents=True)
        (self.root / ".cache").mkdir()
        (self.root / "a" / "b" / "c").mkdir(parents=True)
        (self.root / "Vacances été" / "Plage" / "coucher_de_soleil.png").write_bytes(PNG)
        (self.root / "Vacances été" / "notes plage.txt").write_text("sable")
        (self.root / ".cache" / "plage.png").write_bytes(PNG)
        (self.root / ".plage-cachée.png").write_bytes(PNG)
        (self.root / "a" / "b" / "c" / "profond plage.png").write_bytes(PNG)
        (self.root / "faux.png").write_text("pas une image")
        self.outside = tmp / "secret.png"
        self.outside.write_bytes(PNG)
        os.symlink(self.outside, self.root / "lien.png")
        self.uploads = tmp / "uploads"
        self.settings = Settings(LLM_STREAM=False, LLM_TOOL_CALLING="native", MCP_CLIENT_ENABLED=False,
                                 FILES_SEARCH_DIRS=[str(self.root), str(tmp / "absent")], FILES_SEARCH_MAX_DEPTH=2,
                                 IMAGES_UPLOAD_DIR=str(self.uploads), IMAGES_MAX_BYTES=10_000)

    def tearDown(self):
        self.tmp.cleanup()

    def make_core(self, vision=True):
        tools = ToolRegistry(self.settings)
        tools.add(_action_tool(SHOW_IMAGE_ACTION, self.settings))
        self.llm = VisionLLM(self.settings, vision)
        tts = TextToSpeech(self.settings, provider=VoicesTTS(self.settings))
        core = AssistantCore(self.settings, stt=FakeSTT(), tts=tts, tools=tools, llm=self.llm)
        self.events = []
        core.events.subscribe(lambda e: self.events.append((e.type, e.data)))
        return core


class TestUploads(ImagesTestCase):
    def test_format_from_bytes(self):
        self.assertEqual(sniff_mime(PNG), "image/png")
        self.assertEqual(sniff_mime(JPEG), "image/jpeg")
        self.assertEqual(sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertIsNone(sniff_mime(b"<svg></svg>"))

    def test_decode(self):
        image = decode_upload({"data": f"data:image/jpeg;base64,{b64(PNG)}", "name": "../../x.jpg"}, self.settings)
        # Le type annoncé est ignoré, le nom ne garde aucun dossier
        self.assertEqual((image.mime, image.name, image.data), ("image/png", "x.jpg", PNG))

    def test_refused(self):
        for item, message in (
            ({"data": b64(b"<svg/>")}, "Format"),
            ({"data": "pas du base64 !"}, "base64"),
            ({"data": b64(PNG + b"\x00" * 20_000)}, "trop lourde"),
            ("texte", "mal formée"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ImageError, message):
                decode_upload(item, self.settings)
        with self.assertRaisesRegex(ImageError, "au maximum"):
            decode_uploads([{"data": b64(PNG)}] * 5, self.settings)
        with self.assertRaisesRegex(ImageError, "désactivées"):
            decode_uploads([{"data": b64(PNG)}], self.settings.model_copy(update={"IMAGES_ENABLED": False}))
        self.assertEqual(decode_uploads(None, self.settings), [])


class TestSearch(ImagesTestCase):
    def names(self, query, **kwargs):
        return sorted(Path(p).name for p in search_files(query, self.settings, **kwargs))

    def test_words_and_accents(self):
        # Mots dans le chemin, accents et casse ignorés ; fichiers et dossiers cachés exclus
        self.assertEqual(self.names("ete PLAGE"), ["coucher_de_soleil.png", "notes plage.txt"])
        self.assertEqual(self.names("coucher soleil"), ["coucher_de_soleil.png"])
        self.assertEqual(self.names("plage", images_only=True), ["coucher_de_soleil.png"])

    def test_glob_and_depth(self):
        self.assertEqual(self.names("*.txt"), ["notes plage.txt"])
        # « a/b/c » dépasse FILES_SEARCH_MAX_DEPTH=2
        self.assertNotIn("profond plage.png", self.names("*.png"))
        deeper = self.settings.model_copy(update={"FILES_SEARCH_MAX_DEPTH": 3})
        self.assertIn("profond plage.png", [Path(p).name for p in search_files("profond", deeper)])

    def test_limit(self):
        limited = self.settings.model_copy(update={"FILES_SEARCH_MAX_RESULTS": 1})
        self.assertEqual(len(search_files("*", limited)), 1)

    def test_outside_refused(self):
        self.assertEqual(resolve_allowed("Vacances été/Plage/coucher_de_soleil.png", self.settings).name,
                         "coucher_de_soleil.png")
        for path in (str(self.outside), "../secret.png", "lien.png"):
            with self.subTest(path=path), self.assertRaisesRegex(ImageError, "en dehors"):
                resolve_allowed(path, self.settings)
        with self.assertRaisesRegex(ImageError, "introuvable"):
            resolve_allowed("absent.png", self.settings)

    def test_load_image(self):
        image, shown = load_image(str(self.root / "Vacances été" / "Plage" / "coucher_de_soleil.png"), self.settings)
        self.assertEqual((image.mime, image.name), ("image/png", "coucher_de_soleil.png"))
        self.assertTrue(shown.endswith("coucher_de_soleil.png"))
        with self.assertRaisesRegex(ImageError, "pas une image"):
            load_image("Vacances été/notes plage.txt", self.settings)
        with self.assertRaisesRegex(ImageError, "lisible"):
            load_image("faux.png", self.settings)

    def test_actions(self):
        self.make_core()  # le cœur fournit ses paramètres aux actions
        code, out, _ = SEARCH_FILES_ACTION.check("soleil")
        self.assertEqual(code, 0)
        self.assertIn("coucher_de_soleil.png", out)
        self.assertIn("Aucun fichier", SEARCH_FILES_ACTION.check("introuvable")[1])
        self.assertEqual(SHOW_IMAGE_ACTION.check(str(self.outside))[0], 1)


class TestCoreImages(ImagesTestCase):
    def test_vision_model_receives_images(self):
        core = self.make_core(vision=True)
        image = decode_upload({"data": b64(PNG), "name": "photo.png"}, self.settings)
        reply = core.respond("s", text="Que vois-tu ?", images=[image])
        self.assertEqual(reply.text, "1 image(s) : Que vois-tu ?")
        self.assertEqual(self.llm.received[-1][0].data, PNG)
        # L'historique ne garde que la mention de l'image
        user = core.get_session("s").conversation.history[0]
        self.assertIn("photo.png", user["content"])
        self.assertEqual(core.model_info()["vision"], True)

    def test_no_vision_warns(self):
        core = self.make_core(vision=False)
        image = decode_upload({"data": b64(PNG)}, self.settings)
        reply = core.respond("s", text="Et ça ?", images=[image])
        self.assertEqual(reply.text, "0 image(s) : Et ça ?")
        warnings = [d for t, d in self.events if t == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("vue-test", warnings[0]["message"])
        # Image seule : le modèle n'est pas appelé, l'alerte sert de réponse
        calls = len(self.llm.received)
        reply = core.respond("s", images=[image])
        self.assertIn("ne sait pas lire les images", reply.text)
        self.assertEqual(len(self.llm.received), calls)

    def test_show_image(self):
        core = self.make_core()
        reply = core.respond("s", text="montre Vacances été/Plage/coucher_de_soleil.png")
        self.assertEqual(reply.text, "Voici l'image.")
        images = [d for t, d in self.events if t == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(base64.b64decode(images[0]["data"]), PNG)
        self.assertEqual(images[0]["mime"], "image/png")
        self.assertEqual(len(reply.images), 1)
        # Hors des dossiers permis : outil refusé, rien n'est envoyé
        self.events.clear()
        core.respond("s", text=f"montre {self.outside}")
        self.assertFalse([d for t, d in self.events if t == "image"])
        tool = [d for t, d in self.events if t == "tool"][0]
        self.assertIn("en dehors", tool["output"])
        self.assertFalse([d for t, d in self.events if t == "error"])

    def test_agent_receives_path(self):
        from tests.test_agents import FAKE_AGENT
        script = Path(self.tmp.name) / "fake_agent.py"
        script.write_text(FAKE_AGENT, encoding="utf-8")
        config = Path(self.tmp.name) / "agents.json"
        config.write_text(json.dumps({"agents": {"fake": {
            "label": "Fakebot", "command": [sys.executable, str(script), "{prompt}"], "output": "hermes"}}}))
        self.settings = self.settings.model_copy(update={"AGENTS_CONFIG_FILE": str(config), "AGENTS_PROMPT_PREFIX": "[v]"})
        core = self.make_core(vision=False)
        core.open_session("s")
        core.set_agent("s", "fake")
        image = decode_upload({"data": b64(PNG)}, self.settings)
        reply = core.respond("s", text="regarde", images=[image])
        saved = list(self.uploads.iterdir())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), PNG)
        self.assertIn(str(saved[0]), reply.text)
        self.assertFalse([d for t, d in self.events if t == "warning"])


class TestGatewayImages(ImagesTestCase):
    def test_ws_images(self):
        core = self.make_core(vision=True)
        client = TestClient(create_app(core, self.settings))
        with client.websocket_connect("/ws") as ws:
            ready = ws.receive_json()
            self.assertEqual(ready["images"]["max_per_message"], self.settings.IMAGES_MAX_PER_MESSAGE)
            self.assertTrue(ready["llm"]["vision"])
            ws.send_json({"type": "text", "text": "décris", "images": [{"data": b64(PNG), "name": "a.png"}]})
            events = []
            while not events or events[-1]["type"] != "done":
                events.append(ws.receive_json())
            response = next(e for e in events if e["type"] == "response")
            self.assertEqual(response["text"], "1 image(s) : décris")
            # Image refusée : erreur, aucune demande au modèle
            calls = len(self.llm.received)
            ws.send_json({"type": "text", "text": "x", "images": [{"data": b64(b"<svg/>")}]})
            events = []
            while not events or events[-1]["type"] != "done":
                events.append(ws.receive_json())
            self.assertTrue(any(e["type"] == "error" and "Format" in e["message"] for e in events))
            self.assertEqual(len(self.llm.received), calls)

    def test_api_ask_images(self):
        core = self.make_core(vision=True)
        client = TestClient(create_app(core, self.settings))
        res = client.post("/api/ask", json={"images": [{"data": b64(PNG)}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["text"].strip(), "1 image(s) :")
        res = client.post("/api/ask", json={"images": [{"data": "%%%"}]})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
