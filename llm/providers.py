"""
Fournisseurs LLM : interface commune `LLMProvider` + implémentations Ollama (local) et OpenRouter (cloud).
Un fournisseur ne gère ni l'historique ni le prompt système : il reçoit une liste de messages et renvoie le texte.
"""

import base64
import sys
from pathlib import Path
from typing import Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings
from core.providers import ProviderRegistry, require_openrouter_key

TokenCallback = Callable[[str], None]


class LLMProvider:
    """Interface d'un fournisseur LLM."""

    provider_name: str = ""
    # True si le fournisseur accepte un enregistrement audio en entrée (mode STT direct)
    supports_audio: bool = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = ""

    @classmethod
    def describe(cls, settings: Settings) -> str:
        """Résumé lisible de la configuration, sans instancier le fournisseur."""
        raise NotImplementedError

    def chat(
        self,
        messages: list[dict],
        *,
        audio_wav: Optional[bytes] = None,
        model: Optional[str] = None,
        stream: bool = False,
        think: bool = False,
        on_token: Optional[TokenCallback] = None,
    ) -> str:
        """Envoie les messages (le dernier étant le tour utilisateur) et retourne la réponse complète.
        En streaming, chaque fragment est transmis à `on_token`. Lève une exception en cas d'échec."""
        raise NotImplementedError


LLM_PROVIDERS: ProviderRegistry[LLMProvider] = ProviderRegistry("LLM")


@LLM_PROVIDERS.register("ollama")
class OllamaLLM(LLMProvider):
    """LLM local via Ollama. L'API chat d'Ollama n'accepte pas d'audio."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        import ollama
        self.client = ollama.Client(host=settings.OLLAMA_HOST) if settings.OLLAMA_HOST else ollama.Client()
        self.model = settings.OLLAMA_MODEL

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"Ollama ({settings.OLLAMA_MODEL} @ {settings.OLLAMA_HOST})"

    def chat(self, messages, *, audio_wav=None, model=None, stream=False, think=False, on_token=None) -> str:
        if audio_wav:
            raise RuntimeError(
                "Ollama ne prend pas en charge l'audio direct. Utilisez STT_PROVIDER=whisper ou LLM_PROVIDER=openrouter."
            )
        target_model = model or self.model
        try:
            response = self.client.chat(model=target_model, messages=messages, stream=stream, think=think)
        except TypeError:
            # Fallback pour versions d'Ollama ne supportant pas l'argument explicite think
            response = self.client.chat(model=target_model, messages=messages, stream=stream)

        if not stream:
            return _ollama_content(response)

        full_text = ""
        for chunk in response:
            content = _ollama_content(chunk)
            if content:
                full_text += content
                if on_token:
                    on_token(content)
        return full_text


def _ollama_content(response) -> str:
    msg = response.message if hasattr(response, "message") else response.get("message", {})
    return (msg.content if hasattr(msg, "content") else msg.get("content", "")) or ""


@LLM_PROVIDERS.register("openrouter")
class OpenRouterLLM(LLMProvider):
    """LLM cloud via l'API compatible OpenAI d'OpenRouter (supporte l'audio pour les modèles multimodaux)."""

    supports_audio = True

    def __init__(self, settings: Settings):
        super().__init__(settings)
        from openai import OpenAI
        self.client = OpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=settings.OPENROUTER_API_KEY or "missing-key")
        self.model = settings.OPENROUTER_MODEL

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"OpenRouter ({settings.OPENROUTER_MODEL})"

    def chat(self, messages, *, audio_wav=None, model=None, stream=False, think=False, on_token=None) -> str:
        require_openrouter_key(self.settings)

        if audio_wav:
            # Le dernier message (tour utilisateur) devient multimodal : texte éventuel + audio base64
            messages = list(messages)
            user_msg = messages[-1]
            content = [{"type": "input_audio", "input_audio": {"data": base64.b64encode(audio_wav).decode("utf-8"), "format": "wav"}}]
            if user_msg.get("content"):
                content.insert(0, {"type": "text", "text": user_msg["content"]})
            messages[-1] = {"role": "user", "content": content}

        response = self.client.chat.completions.create(model=model or self.model, messages=messages, stream=stream)
        if not stream:
            return response.choices[0].message.content or ""

        full_text = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_text += content
                if on_token:
                    on_token(content)
        return full_text


if __name__ == "__main__":
    from core.config import get_settings
    s = get_settings()
    print(f"🧪 [DEBUG] Fournisseurs LLM disponibles : {', '.join(LLM_PROVIDERS.names())}")
    provider = LLM_PROVIDERS.create(s.LLM_PROVIDER, s)
    print(f"Actif : {provider.describe(s)}")
    print("Réponse > ", end="", flush=True)
    provider.chat([{"role": "user", "content": "Dis bonjour en une phrase."}], stream=True,
                  on_token=lambda t: print(t, end="", flush=True))
    print()
