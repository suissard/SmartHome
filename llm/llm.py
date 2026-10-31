"""
Conversation avec le LLM : historique glissant, prompt système dynamique et affichage du streaming.
Le fournisseur (Ollama, OpenRouter...) est choisi via LLM_PROVIDER dans le registre `llm.providers`.

API publique conservée : ask_llm(), get_history(), clear_history(), add_history_message(), get_default_system_prompt().
"""

import re
import sys
from pathlib import Path
from typing import Optional

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings
from llm.providers import LLM_PROVIDERS, LLMProvider

_THINK_TAGS = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


def get_default_system_prompt(settings: Optional[Settings] = None) -> str:
    """Retourne le prompt système enrichi dynamiquement avec les commandes d'actions."""
    s = settings or get_settings()
    if s.ACTIONS_DYNAMIC_PROMPT:
        try:
            from actions.manager import get_action_manager
            return get_action_manager().build_dynamic_system_prompt(s.LLM_SYSTEM_PROMPT)
        except Exception as e:
            print(f"⚠️ [LLM] Erreur lors de la construction du prompt dynamique : {e}")
    return s.LLM_SYSTEM_PROMPT


def _print_token(token: str):
    print(token, end="", flush=True)


class Conversation:
    """Une conversation : historique des N derniers messages + appels au fournisseur LLM."""

    def __init__(self, provider: Optional[LLMProvider] = None, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._provider = provider
        self.max_messages = self.settings.LLM_HISTORY_MESSAGES
        self.history: list[dict] = []

    @property
    def provider(self) -> LLMProvider:
        # Instanciation paresseuse : importer le module ne se connecte à aucun service
        if self._provider is None:
            self._provider = LLM_PROVIDERS.create(self.settings.LLM_PROVIDER, self.settings)
        return self._provider

    def add_message(self, role: str, content: str):
        """Ajoute un message à l'historique et tronque selon LLM_HISTORY_MESSAGES."""
        if self.max_messages <= 0:
            return
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_messages:
            del self.history[:-self.max_messages]
            # La fenêtre doit commencer par un tour utilisateur (sinon l'échange est coupé en deux)
            while self.history and self.history[0]["role"] != "user":
                self.history.pop(0)

    def clear(self):
        self.history.clear()

    def ask(
        self,
        prompt: Optional[str] = None,
        audio_bytes: Optional[bytes] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        stream: Optional[bool] = None,
        think: Optional[bool] = None,
        use_history: bool = True,
    ) -> str:
        """Envoie un prompt texte ou un enregistrement audio et retourne la réponse (ou un message ⚠️ en cas d'erreur)."""
        stream = self.settings.LLM_STREAM if stream is None else stream
        think = self.settings.LLM_THINK if think is None else think

        messages = [{"role": "system", "content": system_prompt or get_default_system_prompt(self.settings)}]
        if use_history:
            messages.extend(self.history)
        messages.append({"role": "user", "content": prompt or ""})

        try:
            full_text = self.provider.chat(
                messages,
                audio_wav=audio_bytes,
                model=model,
                stream=stream,
                think=think,
                on_token=_print_token if stream else None,
            )
            if stream:
                print()
        except Exception as e:
            err_str = f"⚠️ Erreur {self.settings.LLM_PROVIDER} : {e}"
            print(f"\n{err_str}")
            return err_str

        # Nettoyage des balises de réflexion résiduelles (<think>...</think>)
        full_text = _THINK_TAGS.sub("", full_text).strip()

        if use_history and full_text:
            self.add_message("user", prompt or ("🎙️ [Message vocal]" if audio_bytes else ""))
            self.add_message("assistant", full_text)
        return full_text


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
