"""
Conversation avec le LLM : historique glissant, prompt système dynamique, affichage du streaming
et boucle d'appel d'outils (function calling natif, ou tags [VOLUME 40] en repli).
Le fournisseur (Ollama, OpenRouter...) est choisi via LLM_PROVIDER dans le registre `llm.providers`.

API publique conservée : ask_llm(), get_history(), clear_history(), add_history_message(), get_default_system_prompt().
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings
from core.tools import ConfirmationHandler, ToolPolicy, ToolRegistry, ToolResult, build_tool_registry
from llm.providers import LLM_PROVIDERS, LLMProvider, ToolsNotSupportedError

_THINK_TAGS = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


class ResponseInterrupted(Exception):
    """Levée depuis `on_token` pour abandonner la génération en cours (barge-in, bouton stop)."""

_NATIVE_TOOLS_GUIDANCE = """

### ⚡ OUTILS :
Tu peux agir sur l'ordinateur et la maison grâce aux outils fournis.
1. N'appelle un outil QUE si l'utilisateur le demande expressément.
2. Après l'exécution, réponds par une courte phrase de confirmation orale (sans markdown).
3. Si un outil échoue ou si l'action est annulée, dis-le simplement à l'utilisateur.
4. Quand l'utilisateur prend congé ou n'a plus besoin de rien (au revoir, c'est tout, bonne nuit...), appelle l'outil sleep, puis salue-le en une courte phrase.
5. N'écris jamais le nom d'un outil dans ta réponse : appelle-le."""


_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre")


def current_datetime_line(now: Optional[datetime] = None) -> str:
    """Date et heure locales en toutes lettres (la langue du prompt par défaut est le français)."""
    now = now or datetime.now().astimezone()
    return (f"Nous sommes le {_WEEKDAYS[now.weekday()]} {now.day} {_MONTHS[now.month - 1]} {now.year}, "
            f"il est {now:%H:%M} (fuseau {now:%Z}).")


def get_default_system_prompt(settings: Optional[Settings] = None, use_tags: Optional[bool] = None,
                              policy: Optional[ToolPolicy] = None) -> str:
    """Prompt système complet : consignes de base, date et heure courantes, puis outils (voir `_tools_prompt`).
    `policy` limite les tags d'actions présentés à ceux que l'utilisateur a le droit d'utiliser."""
    s = settings or get_settings()
    prompt = _tools_prompt(s, use_tags, policy)
    if s.LLM_INJECT_DATETIME:
        prompt = f"{prompt.rstrip()}\n\n{current_datetime_line()}"
    return prompt


def _tools_prompt(s: Settings, use_tags: Optional[bool], policy: Optional[ToolPolicy] = None) -> str:
    """Prompt système enrichi : liste des tags d'actions (mode tags) ou consignes d'outils (mode natif)."""
    if use_tags is None:
        use_tags = s.LLM_TOOL_CALLING == "tags"
    if not s.ACTIONS_DYNAMIC_PROMPT:
        return s.LLM_SYSTEM_PROMPT
    if not use_tags:
        return s.LLM_SYSTEM_PROMPT.strip() + _NATIVE_TOOLS_GUIDANCE
    if not s.ACTIONS_ENABLED:
        return s.LLM_SYSTEM_PROMPT
    try:
        from actions.manager import get_action_manager
        return get_action_manager().build_dynamic_system_prompt(s.LLM_SYSTEM_PROMPT, policy=policy)
    except Exception as e:
        print(f"⚠️ [LLM] Erreur lors de la construction du prompt dynamique : {e}")
        return s.LLM_SYSTEM_PROMPT


def _print_token(token: str):
    print(token, end="", flush=True)


class Conversation:
    """Une conversation : historique des N derniers messages + appels au fournisseur LLM."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        settings: Optional[Settings] = None,
        tools: Optional[ToolRegistry] = None,
        confirm: Optional[ConfirmationHandler] = None,
        tool_policy: Optional[ToolPolicy] = None,
    ):
        self.settings = settings or get_settings()
        self._provider = provider
        self._tools = tools
        # Droits de l'utilisateur de la session (None : tous les outils) ; vue filtrée mise en cache
        self.tool_policy = tool_policy
        self._restricted: Optional[tuple] = None
        # Lignes propres à l'utilisateur de la session (prénom, préférences), ajoutées au prompt système
        self.user_prompt = ""
        # Souvenirs du compte utiles à ce tour (core/memory.py), recalculés à chaque demande
        self.memory_prompt = ""
        self.max_messages = self.settings.LLM_HISTORY_MESSAGES
        self.history: list[dict] = []
        # Messages sortis de la fenêtre : ils y reviennent si une suppression ou une relance y refait de la place
        self.older: list[dict] = []
        # "auto" bascule définitivement sur "tags" si le modèle refuse les outils
        self.tool_mode = self.settings.LLM_TOOL_CALLING
        self.last_tool_results: list[ToolResult] = []
        # Confirmation propre à cette conversation (sinon le gestionnaire global de core.tools)
        self.confirm = confirm
        self._on_tool: Optional[Callable[[ToolResult], None]] = None

    @property
    def tools(self) -> ToolRegistry:
        # Construit au premier besoin, pour inclure les outils des serveurs MCP connectés entre-temps
        if self._tools is None:
            self._tools = build_tool_registry(self.settings)
        if self.tool_policy is None:
            return self._tools
        cache = self._restricted
        if cache is None or cache[0] is not self._tools or cache[1] is not self.tool_policy:
            cache = self._restricted = (self._tools, self.tool_policy, self._tools.restricted(self.tool_policy))
        return cache[2]

    def refresh_tools(self):
        """Reconstruit le registre d'outils (ex: après connexion du hub MCP)."""
        self._tools = None

    @property
    def provider(self) -> LLMProvider:
        # Instanciation paresseuse : importer le module ne se connecte à aucun service
        if self._provider is None:
            self._provider = LLM_PROVIDERS.create(self.settings.LLM_PROVIDER, self.settings)
        return self._provider

    def add_message(self, role: str, content: str, turn: Optional[str] = None):
        """Ajoute un message à l'historique et tronque selon LLM_HISTORY_MESSAGES.
        `turn` identifie l'échange côté client (suppression ou relance d'un message)."""
        if self.max_messages <= 0:
            return
        self.history.append({"role": role, "content": content, **({"turn": turn} if turn else {})})
        self._fit_window()

    def _fit_window(self):
        """Répartit les messages entre la fenêtre envoyée au LLM (`history`) et les plus anciens (`older`)."""
        messages = self.older + self.history
        split = max(len(messages) - self.max_messages, 0)
        if split:
            # La fenêtre doit commencer par un tour utilisateur (sinon l'échange est coupé en deux)
            while split < len(messages) and messages[split]["role"] != "user":
                split += 1
        self.older = messages[:split]
        self.history[:] = messages[split:]

    def clear(self):
        self.history.clear()
        self.older.clear()

    def forget(self, turns: Iterable[str], role: Optional[str] = None):
        """Retire les messages de ces échanges (seulement ceux de `role` s'il est précisé)."""
        turns = set(turns)

        def kept(messages: list[dict]) -> list[dict]:
            return [m for m in messages if m.get("turn") not in turns or (role and m["role"] != role)]

        self.older = kept(self.older)
        self.history[:] = kept(self.history)
        self._fit_window()

    def edit_answer(self, turn: str, text: str):
        """Remplace la réponse de l'assistant pour cet échange."""
        for message in self.older + self.history:
            if message.get("turn") == turn and message["role"] == "assistant":
                message["content"] = text

    def ask(
        self,
        prompt: Optional[str] = None,
        audio_bytes: Optional[bytes] = None,
        images: Optional[list] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        stream: Optional[bool] = None,
        think: Optional[bool] = None,
        use_history: bool = True,
        use_tools: bool = True,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[ToolResult], None]] = None,
        turn: Optional[str] = None,
    ) -> str:
        """Envoie un prompt texte ou un enregistrement audio et retourne la réponse (ou un message ⚠️ en cas d'erreur).
        `on_token` reçoit les fragments en streaming (affichage console par défaut), `on_tool` chaque outil exécuté.
        `images` (core.images.Image) accompagnent ce tour seulement : l'historique n'en garde que la mention."""
        stream = self.settings.LLM_STREAM if stream is None else stream
        think = self.settings.LLM_THINK if think is None else think
        self.last_tool_results = []
        if use_tools and self.provider.is_decision_model(model):
            return self._decide(prompt, audio_bytes, use_history, on_tool, turn)

        def build_messages(use_tags: bool) -> list[dict]:
            system = system_prompt or get_default_system_prompt(self.settings, use_tags, self.tool_policy)
            if self.user_prompt:
                system = f"{system.rstrip()}\n\n{self.user_prompt}"
            if self.memory_prompt:
                system = f"{system.rstrip()}\n\n{self.memory_prompt}"
            messages = [{"role": "system", "content": system}]
            if use_history:
                messages.extend({"role": m["role"], "content": m["content"]} for m in self.history)
            messages.append({"role": "user", "content": prompt or ""})
            return messages

        # Le registre contient les actions activées et les outils MCP : vide => pas d'outils à proposer
        native = use_tools and self.tool_mode != "tags" and bool(self.tools.all())
        console = stream and on_token is None
        self._on_tool = on_tool
        options = dict(audio_wav=audio_bytes, model=model, stream=stream, think=think,
                       on_token=(on_token or _print_token) if stream else None)
        if images:
            options["images"] = list(images)
        try:
            try:
                full_text = self._run(build_messages(use_tags=not native), native, options)
            except ToolsNotSupportedError:
                if self.tool_mode != "auto":
                    raise
                print("\nℹ️ [LLM] Le modèle ne gère pas les outils : repli sur les tags d'actions.")
                self.tool_mode = "tags"
                full_text = self._run(build_messages(use_tags=True), False, options)
            if console:
                print()
        except ResponseInterrupted:
            # Réponse abandonnée : rien n'est conservé dans l'historique
            print("\n⏹️ [LLM] Réponse interrompue.")
            return ""
        except Exception as e:
            err_str = f"⚠️ Erreur {self.settings.LLM_PROVIDER} : {e}"
            print(f"\n{err_str}")
            return err_str

        # Nettoyage des balises de réflexion résiduelles (<think>...</think>)
        full_text = _THINK_TAGS.sub("", full_text).strip()

        if use_history and full_text:
            content = prompt or ("🎙️ [Message vocal]" if audio_bytes else "")
            if images:
                mention = ", ".join(img.name for img in images)
                content = f"{content}\n🖼️ [Image(s) jointe(s) : {mention}]".strip()
            self.add_message("user", content, turn)
            self.add_message("assistant", full_text, turn)
        return full_text

    def _decide(self, prompt, audio_bytes, use_history: bool, on_tool, turn: Optional[str] = None) -> str:
        """Modèle de décision : choix et exécution de la commande, puis réponse type (voir llm/decision.py)."""
        from llm.decision import run_decision
        if audio_bytes and not prompt:
            return "⚠️ Un modèle de décision a besoin du texte de la demande : utilisez un STT (STT_PROVIDER=whisper)."
        try:
            text = run_decision(self, prompt or "", on_tool)
        except Exception as e:
            err_str = f"⚠️ Erreur {self.settings.LLM_PROVIDER} (décision) : {e}"
            print(f"\n{err_str}")
            return err_str
        print(f"🤖 {text}")
        if use_history:
            self.add_message("user", prompt, turn)
            self.add_message("assistant", text, turn)
        return text

    def _run(self, messages: list[dict], native: bool, options: dict) -> str:
        """Interroge le LLM ; en mode natif, exécute les outils demandés et renvoie leurs résultats jusqu'à la réponse finale."""
        schemas = self.tools.schemas() if native else None
        response = None
        for _ in range(self.settings.LLM_MAX_TOOL_ROUNDS):
            response = self.provider.chat(messages, tools=schemas, **options)
            if not response.tool_calls:
                return response.text
            messages.append(self.provider.assistant_message(response))
            for call in response.tool_calls:
                result = self.tools.call(call, confirm=self.confirm)
                self.last_tool_results.append(result)
                if self._on_tool:
                    self._on_tool(result)
                messages.append(self.provider.tool_message(result))

        # Trop d'allers-retours : on résume ce qui a été fait plutôt que de boucler
        done = [r.call.name for r in self.last_tool_results if r.executed]
        return (response.text if response else "") or (
            f"J'ai exécuté : {', '.join(done)}." if done else "Je n'ai pas réussi à terminer cette demande."
        )


# Conversation par défaut (processus mono-utilisateur : main.py, serveur MCP)
_default_conversation: Optional[Conversation] = None


def get_conversation() -> Conversation:
    global _default_conversation
    if _default_conversation is None:
        _default_conversation = Conversation()
    return _default_conversation


def get_history() -> list[dict]:
    """Retourne une copie de l'historique actuel de la conversation."""
    return list(get_conversation().history)


def clear_history():
    """Réinitialise l'historique de conversation."""
    get_conversation().clear()


def add_history_message(role: str, content: str):
    """Ajoute un message à l'historique et tronque selon LLM_HISTORY_MESSAGES."""
    get_conversation().add_message(role, content)


def ask_llm(
    prompt: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    stream: Optional[bool] = None,
    think: Optional[bool] = None,
    use_history: bool = True,
    use_tools: bool = True,
) -> str:
    """Interroge le fournisseur LLM configuré via la conversation par défaut."""
    return get_conversation().ask(
        prompt=prompt,
        audio_bytes=audio_bytes,
        model=model,
        system_prompt=system_prompt,
        stream=stream,
        think=think,
        use_history=use_history,
        use_tools=use_tools,
    )


if __name__ == "__main__":
    s = get_settings()
    print(f"🧪 [DEBUG] Mode test LLM ({LLM_PROVIDERS.get(s.LLM_PROVIDER).describe(s)})")
    print(f"🧠 Mémoire historique active : {s.LLM_HISTORY_MESSAGES} messages (Tapez /clear pour vider, /history pour afficher)")
    while True:
        try:
            user_input = input("\nToi > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                break
            if user_input.lower() in ["/clear", "/reset"]:
                clear_history()
                print("🧹 Historique réinitialisé.")
                continue
            if user_input.lower() == "/history":
                hist = get_history()
                print(f"📜 Historique actuel ({len(hist)}/{s.LLM_HISTORY_MESSAGES}) :")
                for i, msg in enumerate(hist, 1):
                    print(f"  {i}. [{msg['role'].upper()}] {msg['content']}")
                continue

            print("Assistant > ", end="", flush=True)
            ask_llm(user_input)
        except KeyboardInterrupt:
            break
