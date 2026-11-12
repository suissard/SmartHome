#!/usr/bin/env python3
"""
Tests des agents externes (core/agents.py) : lecture des sorties (Hermes, Claude, Antigravity), reconnaissance
de « parler à X », exécution d'un faux agent (script Python : streaming, reprise de session, interruption, erreur),
routage par AssistantCore (bascule sans LLM, retour, voix alternative, droits) et passerelle (set_agent).
"""

import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import numpy as np
from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from audio.tts import TextToSpeech, TTSProvider
from core.agents import (
    ASSISTANT, AgentCancelled, AgentDirectory, AgentError, AgentRunner, AgentSpec, detect_switch,
    parse_antigravity, parse_claude, parse_hermes,
)
from core.assistant import AssistantCore
from core.config import Settings
from core.sentences import strip_markdown
from core.tools import ToolRegistry
from core.users import User, tool_policy
from gateway.app import create_app
from tests.test_gateway import FakeSTT, RuleLLM

# Faux agent : écho découpé en fragments (format Hermes), session « s-<n> » incrémentée à chaque reprise.
# « lent » : attend longtemps (interruption) ; « plante » : erreur sur stderr.
FAKE_AGENT = textwrap.dedent('''
    import json, sys, time
    args = sys.argv[1:]
    session = args[args.index("--resume") + 1] if "--resume" in args else ""
    prompt = args[0].split("\\n", 1)[-1]
    if prompt == "plante":
        print("boum", file=sys.stderr); sys.exit(3)
    if prompt == "lent":
        time.sleep(30)
    n = int(session.split("-")[1]) + 1 if session else 1
    for part in ("Reçu : ", prompt, ". Session ", str(n), "."):
        print(json.dumps({"type": "text", "text": part}), flush=True)
    print(json.dumps({"type": "result", "exit_code": 0, "text": "", "session_id": f"s-{n}"}), flush=True)
''')


class VoicesTTS(TTSProvider):
    @classmethod
    def describe(cls, settings):
        return "Fake"

    def synthesize(self, text, voice=None):
        self.last_voice = voice
        return np.zeros(100, dtype=np.int16), 8000

    def voices(self):
        return [{"id": "assistant-voice", "label": "A", "default": True},
                {"id": "autre-voix", "label": "B", "default": False}]


class CountingLLM(RuleLLM):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return super().chat(messages, **kwargs)


class AgentTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        script = tmp / "fake_agent.py"
        script.write_text(FAKE_AGENT, encoding="utf-8")
        config = tmp / "agents.json"
        config.write_text(json.dumps({"agents": {
            "fake": {"label": "Fakebot", "aliases": ["faux agent"], "color": "#123456",
                     "command": [sys.executable, str(script), "{prompt}"], "resume_args": ["--resume", "{session}"],
                     "output": "hermes", "cwd": str(tmp), "timeout": 10},
            "voix": {"label": "Voixbot", "voice": "inexistante", "command": [sys.executable, str(script), "{prompt}"],
                     "output": "hermes"},
            "off": {"label": "Off", "command": ["true"], "enabled": False},
            "absent": {"label": "Absentbot", "command": ["commande-agent-absente", "{prompt}"]},
        }}), encoding="utf-8")
        self.settings = Settings(LLM_STREAM=True, LLM_TOOL_CALLING="native", MCP_CLIENT_ENABLED=False,
                                 AGENTS_CONFIG_FILE=str(config), AGENTS_PROMPT_PREFIX="[voix]",
                                 TTS_STREAM_MIN_CHARS=1)
        self.directory = AgentDirectory(self.settings)

    def tearDown(self):
        self.tmp.cleanup()

    def make_core(self):
        self.llm = CountingLLM()
        self.tts_engine = VoicesTTS(self.settings)
        core = AssistantCore(self.settings, stt=FakeSTT(), tts=TextToSpeech(self.settings, provider=self.tts_engine),
                             tools=ToolRegistry(self.settings), llm=self.llm)
        return core


class TestParsers(unittest.TestCase):
    def test_hermes(self):
        self.assertEqual(parse_hermes('{"type": "text", "text": "Bon"}').text, "Bon")
        result = parse_hermes('{"type": "result", "exit_code": 0, "text": "Bonjour", "session_id": "abc"}')
        self.assertEqual((result.final, result.session, result.error), ("Bonjour", "abc", ""))
        self.assertEqual(parse_hermes("Session trouvée, démarrage").text, "")

    def test_claude(self):
        self.assertEqual(parse_claude('{"type": "system", "subtype": "init", "session_id": "u1"}').session, "u1")
        delta = {"type": "stream_event", "event": {"type": "content_block_delta",
                                                    "delta": {"type": "text_delta", "text": "Salut"}}}
        self.assertEqual(parse_claude(json.dumps(delta)).text, "Salut")
        error = parse_claude('{"type": "result", "is_error": true, "result": "quota", "session_id": "u1"}')
        self.assertEqual((error.error, error.final), ("quota", ""))

    def test_antigravity(self):
        self.assertEqual(parse_antigravity('{"event": "init", "conversation_id": "c1"}').session, "c1")
        step = {"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "Oui"}}
        self.assertEqual(parse_antigravity(json.dumps(step)).text, "Oui")
        result = {"event": "result", "result": {"conversation_id": "c1", "status": "SUCCESS", "response": "Oui"}}
        self.assertEqual(parse_antigravity(json.dumps(result)).final, "Oui")

    def test_strip_markdown(self):
        spoken = strip_markdown("## Titre\n- **un** point\n- voir [la doc](https://x.y)\n```\ncode\n```")
        self.assertNotIn("*", spoken)
        self.assertNotIn("#", spoken)
        self.assertNotIn("https", spoken)
        self.assertIn("la doc", spoken)


class TestDirectoryAndSwitch(AgentTestCase):
    def test_directory(self):
        self.assertEqual(sorted(a.name for a in self.directory.all()), ["absent", "fake", "voix"])
        self.assertEqual(self.directory.get("Faux Agent").name, "fake")
        self.assertEqual(self.directory.get("FAKEBOT").name, "fake")
        self.assertIsNone(self.directory.get("off"))
        self.assertNotIn("command", self.directory.get("fake").public())

    def test_disabled(self):
        directory = AgentDirectory(self.settings.model_copy(update={"AGENTS_ENABLED": False}))
        self.assertEqual(directory.all(), [])

    def test_detect_switch(self):
        agents = self.directory.all()
        self.assertEqual(detect_switch("J'aimerais parler à Fakebot", agents, self.settings).target, "fake")
        self.assertEqual(detect_switch("passe-moi le faux agent s'il te plaît", agents, self.settings).rest, "")
        request = detect_switch("Passe-moi Fakebot, quelle heure est-il ?", agents, self.settings)
        self.assertEqual(request.rest, "Passe-moi Fakebot, quelle heure est-il ?")
        self.assertEqual(detect_switch("je veux parler à jarvis", agents, self.settings).target, ASSISTANT)
        self.assertIsNone(detect_switch("comment parler à mon chat", agents, self.settings))
        self.assertIsNone(detect_switch("Fakebot est sympa", agents, self.settings))

    def test_build_command(self):
        spec = AgentSpec("x", "X", [sys.executable, "-c", "{prompt}"], resume_args=["--resume", "{session}"])
        self.assertEqual(spec.build_command("bonjour")[1:], ["-c", "bonjour"])
        self.assertEqual(spec.build_command("bonjour", "s1")[-2:], ["--resume", "s1"])
        with self.assertRaises(AgentError):
            AgentSpec("y", "Y", ["commande-qui-n-existe-pas"]).build_command("a")

    def test_extra_path_finds_command_missing_from_path(self):
        # Service systemd : ~/.local/bin absent du PATH, la commande est trouvée grâce à AGENTS_EXTRA_PATH
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        # Windows ne lance qu'un fichier à extension connue (PATHEXT)
        exe = bin_dir / ("agent-local.cmd" if sys.platform == "win32" else "agent-local")
        exe.write_text("@echo ok\n" if sys.platform == "win32" else "#!/bin/sh\necho ok\n")
        exe.chmod(0o755)
        spec = AgentSpec("l", "L", ["agent-local", "{prompt}"])
        self.assertIsNone(spec.executable(self.settings))
        settings = Settings(AGENTS_EXTRA_PATH=[str(bin_dir)])
        same = lambda found: os.path.normcase(found or "")  # noqa: E731
        self.assertEqual(same(spec.executable(settings)), same(str(exe)))
        self.assertEqual(same(spec.build_command("a", settings=settings)[0]), same(str(exe)))

    def test_build_command_never_turns_text_into_options(self):
        spec = AgentSpec("x", "X", [sys.executable, "{prompt}"], resume_args=["--resume", "{session}"])
        self.assertEqual(spec.build_command("--dangerously-skip-permissions")[1:], [" --dangerously-skip-permissions"])
        self.assertNotIn("--resume", spec.build_command("bonjour", "--evil"))


class TestRunner(AgentTestCase):
    def test_stream_and_resume(self):
        runner = AgentRunner(self.settings)
        spec = self.directory.get("fake")
        fragments = []
        first = runner.run(spec, "bonjour", on_text=fragments.append)
        self.assertEqual(first.text, "Reçu : bonjour. Session 1.")
        self.assertEqual(first.session, "s-1")
        self.assertGreater(len(fragments), 1)
        self.assertEqual(runner.run(spec, "encore", session=first.session).session, "s-2")

    def test_error(self):
        with self.assertRaises(AgentError) as ctx:
            AgentRunner(self.settings).run(self.directory.get("fake"), "plante")
        self.assertIn("boum", str(ctx.exception))

    def test_cancel(self):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(AgentCancelled):
            AgentRunner(self.settings).run(self.directory.get("fake"), "lent", cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)

    @unittest.skipIf(sys.platform == "win32", "signaux POSIX")
    def test_cancel_kills_agent_ignoring_sigterm(self):
        script = Path(self.tmp.name) / "stubborn.py"
        script.write_text("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                          "print('pret', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        spec = AgentSpec("s", "Stubborn", [sys.executable, str(script), "{prompt}"])
        settings = Settings(**{**self.settings.model_dump(), "AGENTS_KILL_GRACE": 0.5})
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(AgentCancelled):
            AgentRunner(settings).run(spec, "x", cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)


class TestCoreRouting(AgentTestCase):
    def test_switch_talk_and_return(self):
        core = self.make_core()
        core.open_session("s")
        events = []
        core.events.subscribe(events.append, session_id="s")
        spoken = []

        reply = core.respond("s", text="J'aimerais parler à Fakebot", on_sentence=spoken.append)
        self.assertEqual(self.llm.calls, 0)
        self.assertEqual(reply.text, "Fakebot à l'écoute.")
        self.assertEqual(core.agent_info("s")["name"], "fake")
        changed = [e for e in events if e.type == "agent_changed"]
        self.assertEqual(changed[-1].data["agent"]["color"], "#123456")
        # Voix de l'agent : pas de voix dans sa fiche -> une autre voix que celle de l'assistant
        self.assertEqual(core.session_voice("s"), "autre-voix")

        reply = core.respond("s", text="quelle heure est-il", on_sentence=spoken.append)
        self.assertEqual(reply.text, "Reçu : quelle heure est-il. Session 1.")
        self.assertEqual(self.llm.calls, 0)
        response = [e for e in events if e.type == "response"][-1]
        self.assertEqual(response.data["agent"], "fake")
        self.assertTrue(any(e.type == "token" for e in events))
        reply = core.respond("s", text="et demain")
        self.assertTrue(reply.text.endswith("Session 2."))

        reply = core.respond("s", text="Reviens !", on_sentence=spoken.append)
        self.assertEqual(reply.text, "Me revoilà.")
        self.assertIsNone(core.agent_info("s"))
        self.assertIsNone(core.session_voice("s"))
        core.respond("s", text="bonjour")
        self.assertEqual(self.llm.calls, 1)
        self.assertIn("Fakebot à l'écoute.", spoken)

    def test_switch_with_request(self):
        core = self.make_core()
        core.open_session("s")
        spoken = []
        reply = core.respond("s", text="Passe-moi Fakebot, dis bonjour", on_sentence=spoken.append)
        self.assertIn("Reçu : ", reply.text)
        self.assertEqual(spoken[0], "Fakebot à l'écoute.")

    def test_end_phrase_leaves_agent(self):
        core = self.make_core()
        core.open_session("s")
        core.set_agent("s", "fake")
        reply = core.respond("s", text="Au revoir")
        self.assertTrue(reply.end_conversation)
        self.assertIsNone(core.agent_info("s"))

    def test_agent_error_is_spoken(self):
        core = self.make_core()
        core.open_session("s")
        core.set_agent("s", "fake")
        reply = core.respond("s", text="plante")
        self.assertIn("Fakebot ne répond pas", reply.text)
        # L'agent a échoué : l'assistant reprend la main, le message suivant va au LLM
        self.assertIsNone(core.agent_info("s"))
        core.respond("s", text="bonjour")
        self.assertEqual(self.llm.calls, 1)

    def test_missing_agent_command_stays_with_assistant(self):
        core = self.make_core()
        core.open_session("s")
        reply = core.respond("s", text="J'aimerais parler à Absentbot")
        self.assertIn("introuvable", reply.text)
        self.assertIsNone(core.agent_info("s"))
        with self.assertRaises(ValueError):
            core.set_agent("s", "absent")
        core.respond("s", text="bonjour")
        self.assertEqual(self.llm.calls, 1)

    def test_roles(self):
        core = self.make_core()
        member = User("u1", "Léo", "member")
        core.open_session("m", user=member)
        reply = core.respond("m", text="parler à Fakebot")
        self.assertIn("réservé", reply.text)
        self.assertIsNone(core.agent_info("m"))
        self.assertEqual(core.available_agents("m"), [])
        with self.assertRaises(ValueError):
            core.set_agent("m", "fake")
        self.assertIn("agent", tool_policy(member, self.settings).denied)
        self.assertNotIn("agent", tool_policy(User("a", "Admin", "admin"), self.settings).denied)

    def test_reset_returns_to_assistant(self):
        core = self.make_core()
        core.open_session("s")
        core.set_agent("s", "fake")
        core.reset("s")
        self.assertIsNone(core.agent_info("s"))

    def test_gateway_set_agent(self):
        core = self.make_core()
        client = TestClient(create_app(core, self.settings))
        with client.websocket_connect("/ws") as ws:
            ready = ws.receive_json()
            self.assertEqual(ready["type"], "ready")
            self.assertIsNone(ready["agent"])
            self.assertEqual(sorted(a["name"] for a in ready["agents"]), ["fake", "voix"])
            ws.send_json({"type": "set_agent", "agent": "fake"})
            event = ws.receive_json()
            self.assertEqual((event["type"], event["agent"]["name"]), ("agent_changed", "fake"))
            ws.send_json({"type": "set_agent", "agent": None})
            event = ws.receive_json()
            self.assertEqual((event["type"], event["agent"]), ("agent_changed", None))
            ws.send_json({"type": "set_agent", "agent": "inconnu"})
            self.assertEqual(ws.receive_json()["type"], "toast")


if __name__ == "__main__":
    unittest.main()
