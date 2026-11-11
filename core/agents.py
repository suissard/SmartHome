"""
Agents externes (Hermes, Claude Code, Antigravity...) : la conversation est reliée à un agent installé sur la machine,
qui répond directement à travers SmartHome (texte dans la PWA, voix alternative).

- Fiches des agents : AGENTS_CONFIG_FILE (agents.json), relu dès qu'il change :
    {"agents": {"hermes": {
        "label": "Hermes",                      # nom affiché et prononcé
        "aliases": ["hermès"],                  # autres noms reconnus à la voix
        "color": "#a855f7",                     # couleur de la pastille de la PWA
        "voice": "fr_FR-tom-medium",            # voix Piper (voices/), sinon AGENTS_DEFAULT_VOICE / autre voix
        "command": ["hermes", "chat", "-q", "{prompt}", "--format", "stream-json"],
        "resume_args": ["--resume", "{session}"],   # ajoutés quand l'agent a donné un identifiant de session
        "output": "hermes",                     # lecture de la sortie : text | hermes | claude | antigravity
        "cwd": "",                              # répertoire de travail (vide : dossier personnel)
        "timeout": 600, "enabled": true, "description": "..."}}}
  `{prompt}` et `{session}` sont remplacés dans les arguments (aucun shell : pas d'injection possible).
- AgentRunner lance l'agent pour un message, lit sa sortie au fil de l'eau (fragments de texte → voix en streaming),
  retient l'identifiant de session renvoyé pour que l'agent garde le fil, et tue le processus sur interruption.
- detect_switch() reconnaît « j'aimerais parler à Hermes » / « passe-moi Claude, ... » sans appeler le LLM ;
  le LLM dispose aussi de l'outil « agent » (actions/modules/agent.py) pour les formulations libres.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import BASE_DIR, Settings, get_settings
from core.sentences import normalize_utterance

# Nombre de mots, au début de l'énoncé, où une formule de bascule est cherchée (« alors j'aimerais parler à »)
_TRIGGER_WINDOW = 6
_STDERR_LINES = 20
_POLL_SECONDS = 0.1
DEFAULT_COLOR = "#a855f7"


class AgentError(RuntimeError):
    pass


class AgentCancelled(Exception):
    pass


@dataclass
class AgentSpec:
    name: str
    label: str
    command: list[str]
    resume_args: list[str] = field(default_factory=list)
    output: str = "text"
    aliases: list[str] = field(default_factory=list)
    color: str = DEFAULT_COLOR
    voice: str = ""
    cwd: str = ""
    timeout: Optional[int] = None
    description: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "AgentSpec":
        command = data.get("command")
        if isinstance(command, str):
            command = command.split()
        if not command or not all(isinstance(a, str) for a in command):
            raise ValueError(f"agent « {name} » : 'command' doit être une liste d'arguments")
        return cls(
            name=name.strip().lower(),
            label=str(data.get("label") or name).strip(),
            command=list(command),
            resume_args=[str(a) for a in data.get("resume_args") or []],
            output=str(data.get("output") or "text").lower(),
            aliases=[str(a) for a in data.get("aliases") or []],
            color=str(data.get("color") or DEFAULT_COLOR),
            voice=str(data.get("voice") or ""),
            cwd=str(data.get("cwd") or ""),
            timeout=int(data["timeout"]) if data.get("timeout") else None,
            description=str(data.get("description") or ""),
            enabled=bool(data.get("enabled", True)),
        )

    @property
    def names(self) -> list[str]:
        return [self.name, self.label, *self.aliases]

    def public(self) -> dict:
        """Fiche transmise à la PWA (ni commande ni répertoire)."""
        return {"name": self.name, "label": self.label, "color": self.color, "description": self.description}

    def build_command(self, prompt: str, session: str = "") -> list[str]:
        args = self.command + (self.resume_args if session else [])
        resolved = [a.replace("{prompt}", prompt).replace("{session}", session) for a in args]
        if "{prompt}" not in " ".join(args):
            resolved.append(prompt)
        exe = shutil.which(resolved[0])
        if exe is None:
            raise AgentError(f"commande « {resolved[0]} » introuvable")
        return [exe, *resolved[1:]]


# ==========================================
# Lecture de la sortie des agents
# ==========================================
@dataclass
class ParsedLine:
    text: str = ""        # fragment de réponse à afficher / prononcer
    final: str = ""       # réponse complète (fin de l'échange)
    session: str = ""     # identifiant de session à reprendre au prochain message
    error: str = ""


OUTPUT_PARSERS: dict[str, Callable[[str], ParsedLine]] = {}


def _parser(*names: str):
    def decorator(func):
        for name in names:
            OUTPUT_PARSERS[name] = func
        return func
    return decorator


def _json(line: str) -> Optional[dict]:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@_parser("text")
def parse_text(line: str) -> ParsedLine:
    return ParsedLine(text=line)


@_parser("hermes")
def parse_hermes(line: str) -> ParsedLine:
    """`hermes chat --format stream-json` : {"type": "text", "text"} puis {"type": "result", "text", "session_id"}."""
    data = _json(line)
    if data is None:
        return ParsedLine()
    kind = data.get("type")
    if kind == "text":
        return ParsedLine(text=str(data.get("text") or ""))
    if kind == "result":
        error = "" if data.get("exit_code", 0) == 0 else str(data.get("error") or f"code {data.get('exit_code')}")
        return ParsedLine(final=str(data.get("text") or ""), session=str(data.get("session_id") or ""), error=error)
    if kind == "error":
        return ParsedLine(error=str(data.get("message") or data.get("error") or "erreur"))
    return ParsedLine()


@_parser("claude")
def parse_claude(line: str) -> ParsedLine:
    """`claude -p --output-format stream-json --verbose --include-partial-messages`."""
    data = _json(line)
    if data is None:
        return ParsedLine()
    kind = data.get("type")
    if kind == "system":
        return ParsedLine(session=str(data.get("session_id") or ""))
    if kind == "stream_event":
        event = data.get("event") or {}
        delta = event.get("delta") or {}
        if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            return ParsedLine(text=str(delta.get("text") or ""))
        return ParsedLine()
    if kind == "result":
        error = str(data.get("result") or data.get("subtype") or "erreur") if data.get("is_error") else ""
        return ParsedLine(final="" if error else str(data.get("result") or ""),
                          session=str(data.get("session_id") or ""), error=error)
    return ParsedLine()


@_parser("antigravity", "agy")
def parse_antigravity(line: str) -> ParsedLine:
    """`agy -p ... --output-format stream-json` : init (conversation_id), step_update (text_delta), result."""
    data = _json(line)
    if data is None:
        return ParsedLine()
    kind = data.get("event")
    if kind == "init":
        return ParsedLine(session=str(data.get("conversation_id") or ""))
    if kind == "step_update":
        step = data.get("step_update") or {}
        if step.get("step_type") == "agent_response":
            return ParsedLine(text=str(step.get("text_delta") or ""))
        return ParsedLine()
    if kind == "result":
        result = data.get("result") or {}
        ok = str(result.get("status") or "SUCCESS").upper() == "SUCCESS"
        return ParsedLine(final=str(result.get("response") or "") if ok else "",
                          session=str(result.get("conversation_id") or ""),
                          error="" if ok else str(result.get("error") or result.get("status")))
    return ParsedLine()


# ==========================================
# Annuaire des agents (agents.json)
# ==========================================
class AgentDirectory:
    def __init__(self, settings: Optional[Settings] = None, path: Optional[Path] = None):
        self.settings = settings or get_settings()
        configured = Path(path or self.settings.AGENTS_CONFIG_FILE).expanduser()
        self.path = configured if configured.is_absolute() else BASE_DIR / configured
        self._mtime: Optional[float] = None
        self._agents: dict[str, AgentSpec] = {}
        self._lock = threading.Lock()

    def _load(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._agents, self._mtime = {}, None
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        agents: dict[str, AgentSpec] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")).get("agents") or {}
            for name, data in raw.items():
                try:
                    spec = AgentSpec.from_dict(name, data)
                except (ValueError, TypeError) as e:
                    print(f"⚠️ [AGENTS] Fiche ignorée : {e}")
                    continue
                if spec.output not in OUTPUT_PARSERS:
                    print(f"⚠️ [AGENTS] {spec.name} : sortie « {spec.output} » inconnue, lue comme du texte.")
                    spec.output = "text"
                if spec.enabled:
                    agents[spec.name] = spec
        except (OSError, json.JSONDecodeError, AttributeError) as e:
            print(f"⚠️ [AGENTS] {self.path.name} illisible : {e}")
        self._agents = agents

    def all(self) -> list[AgentSpec]:
        if not self.settings.AGENTS_ENABLED:
            return []
        with self._lock:
            self._load()
            return list(self._agents.values())

    def get(self, name: str) -> Optional[AgentSpec]:
        """Agent par nom, libellé ou alias (casse et accents ignorés)."""
        key = _key(name)
        return next((a for a in self.all() if key in {_key(n) for n in a.names}), None)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _key(text: str) -> str:
    return _strip_accents(normalize_utterance(text))


def _words(text: str) -> list[str]:
    return _key(text).split()


# ==========================================
# Reconnaissance de « parler à X »
# ==========================================
ASSISTANT = "assistant"   # cible de detect_switch() : retour à l'assistant


@dataclass
class SwitchRequest:
    target: str                       # nom d'agent, ou ASSISTANT
    rest: str = ""                    # demande à transmettre à l'agent : l'énoncé entier s'il dit autre chose
                                      # que la mise en relation (« passe-moi Hermes, quelle heure est-il ? »)


def _match_at(keys: list[str], start: int, candidates: list[list[str]]) -> int:
    """Longueur du plus long candidat présent à partir de `start` (0 si aucun)."""
    best = 0
    for cand in candidates:
        if cand and keys[start:start + len(cand)] == cand:
            best = max(best, len(cand))
    return best


def _strip_fillers(words: list[str], fillers: list[list[str]]) -> list[str]:
    changed = True
    while words and changed:
        changed = False
        for f in fillers:
            if f and words[:len(f)] == f:
                words, changed = words[len(f):], True
            elif f and words[-len(f):] == f:
                words, changed = words[:-len(f)], True
    return words


def detect_switch(text: str, agents: list[AgentSpec], settings: Optional[Settings] = None) -> Optional[SwitchRequest]:
    """« J'aimerais parler à Hermes », « passe-moi Claude, quelle heure est-il ? », « parler à Jarvis »."""
    s = settings or get_settings()
    keys = _words(text)
    triggers = [_words(t) for t in s.AGENTS_SWITCH_TRIGGERS]
    articles = [["a"], ["avec"], ["l'"], ["le"], ["la"]]
    targets = [(a.name, _words(n)) for a in agents for n in a.names]
    targets += [(ASSISTANT, _words(n)) for n in [*s.AGENTS_ASSISTANT_NAMES, s.ASSISTANT_NAME] if _words(n)]
    for i in range(min(_TRIGGER_WINDOW, len(keys))):
        length = _match_at(keys, i, triggers)
        if not length:
            continue
        j = i + length
        j += _match_at(keys, j, articles)
        found = [(name, len(words)) for name, words in targets if words and keys[j:j + len(words)] == words]
        if not found:
            continue
        name, size = max(found, key=lambda item: item[1])
        rest = _strip_fillers(keys[j + size:], [_words(f) for f in s.AGENTS_SWITCH_FILLERS])
        return SwitchRequest(name, text.strip() if rest else "")
    return None


# ==========================================
# Exécution d'un agent
# ==========================================
@dataclass
class AgentResult:
    text: str
    session: str = ""


class AgentRunner:
    """Lance un agent pour un message et lit sa réponse au fil de l'eau."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def run(self, spec: AgentSpec, message: str, session: str = "", on_text: Optional[Callable[[str], None]] = None,
            cancel: Optional[threading.Event] = None) -> AgentResult:
        """Bloquant. Lève AgentCancelled (interruption), AgentError (échec, délai dépassé), ou l'exception
        levée par `on_text` (le processus est tué dans tous les cas)."""
        s = self.settings
        prompt = f"{s.AGENTS_PROMPT_PREFIX}\n{message}" if s.AGENTS_PROMPT_PREFIX.strip() else message
        cmd = spec.build_command(prompt, session)
        cwd = Path(spec.cwd).expanduser() if spec.cwd else Path.home()
        parse = OUTPUT_PARSERS.get(spec.output, parse_text)
        timeout = spec.timeout or s.AGENTS_TIMEOUT
        print(f"🤝 [AGENTS] {spec.label} ({'reprise ' + session[:12] if session else 'nouvelle session'})")
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                **({"start_new_session": True} if os.name != "nt"
                   else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}),
            )
        except OSError as e:
            raise AgentError(f"lancement impossible : {e}") from e

        stderr_tail: deque[str] = deque(maxlen=_STDERR_LINES)
        def read_stderr():
            with proc.stderr:
                for line in proc.stderr:
                    stderr_tail.append(line.rstrip())
        stderr_thread = threading.Thread(target=read_stderr, name=f"agent-{spec.name}-stderr", daemon=True)
        stderr_thread.start()
        stopped = threading.Event()
        reason: dict = {}

        def watchdog():
            deadline = time.monotonic() + timeout
            while not stopped.wait(_POLL_SECONDS):
                if cancel is not None and cancel.is_set():
                    reason["why"] = "cancel"
                elif time.monotonic() > deadline:
                    reason["why"] = "timeout"
                else:
                    continue
                _kill(proc)
                return
        threading.Thread(target=watchdog, name=f"agent-{spec.name}-watchdog", daemon=True).start()

        streamed: list[str] = []
        final, new_session, error = "", session, ""
        try:
            for line in proc.stdout:
                parsed = parse(line)
                if parsed.session:
                    new_session = parsed.session
                if parsed.error:
                    error = parsed.error
                if parsed.final:
                    final = parsed.final
                if parsed.text:
                    streamed.append(parsed.text)
                    if on_text:
                        on_text(parsed.text)
            proc.wait()
        except BaseException:
            _kill(proc)
            raise
        finally:
            stopped.set()
            proc.stdout.close()
            stderr_thread.join(timeout=1)

        if reason.get("why") == "cancel":
            raise AgentCancelled()
        if reason.get("why") == "timeout":
            raise AgentError(f"pas de réponse après {timeout} s")
        text = "".join(streamed).strip() or final.strip()
        if error or (proc.returncode and not text):
            detail = error or next((l for l in reversed(stderr_tail) if l.strip()), f"code {proc.returncode}")
            raise AgentError(detail[:300])
        if not streamed and final and on_text:
            on_text(final)
        return AgentResult(text=text, session=new_session)


def _kill(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


if __name__ == "__main__":
    print("🧪 [DEBUG] Agents externes")
    directory = AgentDirectory()
    agents = directory.all()
    print(f"Fichier : {directory.path} — {len(agents)} agent(s)")
    for a in agents:
        found = "✅" if shutil.which(a.command[0]) else "❌ introuvable"
        print(f"  • {a.label} ({a.name}) : {' '.join(a.command)} [{a.output}] {found}")
    for sample in ("J'aimerais parler à Hermes", "passe-moi claude, quelle heure est-il ?", "reviens à jarvis",
                   "baisse le son"):
        print(f"  « {sample} » -> {detect_switch(sample, agents)}")
    if len(sys.argv) > 2:
        spec = directory.get(sys.argv[1])
        if spec is None:
            sys.exit(f"Agent inconnu : {sys.argv[1]}")
        try:
            result = AgentRunner().run(spec, " ".join(sys.argv[2:]), on_text=lambda t: print(t, end="", flush=True))
        except AgentError as e:
            sys.exit(f"❌ {spec.label} : {e}")
        print(f"\n— session : {result.session}")
    else:
        print("Essai : python -m core.agents hermes Bonjour, qui es-tu ?")
