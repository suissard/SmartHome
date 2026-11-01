"""
Fournisseurs LLM : interface commune `LLMProvider` + implémentations Ollama (local) et OpenRouter (cloud).
Un fournisseur ne gère ni l'historique ni le prompt système : il reçoit une liste de messages (et
éventuellement des définitions d'outils) et renvoie un `LLMResponse` (texte + appels d'outils demandés).
"""

import base64
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings
from core.providers import ProviderRegistry, ollama_capabilities, ollama_host, require_openrouter_key
from core.tools import ToolCall, ToolResult, parse_arguments

TokenCallback = Callable[[str], None]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ToolsNotSupportedError(RuntimeError):
    """Le modèle refuse les définitions d'outils (function calling indisponible)."""


def _is_tools_unsupported(error: Exception) -> bool:
    msg = str(error).lower()
    return "support tool" in msg or "tools are not supported" in msg


class LLMProvider:
    """Interface d'un fournisseur LLM."""

    provider_name: str = ""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = ""
        # Entrée audio détectée par modèle (nom -> bool), interrogée une seule fois
        self._audio_input: dict[str, bool] = {}

    @classmethod
    def describe(cls, settings: Settings) -> str:
        """Résumé lisible de la configuration, sans instancier le fournisseur."""
        raise NotImplementedError

    def is_decision_model(self, model: Optional[str] = None) -> bool:
        """True si le modèle (actif par défaut) est un modèle de décision : il choisit, il ne rédige pas (voir llm/decision.py)."""
        return False

    def decide(self, state: str, questions: dict) -> dict:
        """Pose des questions fermées (choice / noul / score) sur `state` ; retourne les réponses par nom de question."""
        raise NotImplementedError(f"{self.provider_name} ne gère pas les modèles de décision.")

    def list_models(self) -> list[dict]:
        """Modèles disponibles : [{"name", "capabilities", "size"}] (vide si le fournisseur ne sait pas les lister)."""
        return []

    def accepts_audio(self, model: Optional[str] = None) -> bool:
        """True si le modèle (actif par défaut) comprend un enregistrement audio (mode STT direct).
        `LLM_AUDIO_INPUT` force la réponse ("on" / "off") ; "auto" interroge les capacités du modèle."""
        mode = self.settings.LLM_AUDIO_INPUT
        if mode != "auto":
            return mode == "on"
        name = model or self.model
        if name not in self._audio_input:
            try:
                self._audio_input[name] = self._detect_audio_input(name)
            except Exception as e:
                # Non mémorisé : nouvelle tentative à la prochaine demande
                print(f"\n⚠️ [LLM] Capacités de {name} inconnues ({e}) : l'audio sera transcrit.")
                return False
        return self._audio_input[name]

    def _detect_audio_input(self, model: str) -> bool:
        """Interroge le fournisseur : le modèle accepte-t-il l'audio en entrée ? Peut lever."""
        return False

    def chat(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        audio_wav: Optional[bytes] = None,
        model: Optional[str] = None,
        stream: bool = False,
        think: bool = False,
        on_token: Optional[TokenCallback] = None,
    ) -> LLMResponse:
        """Envoie les messages (le dernier étant le tour utilisateur ou un résultat d'outil).
        En streaming, chaque fragment de texte est transmis à `on_token`. Lève une exception en cas d'échec,
        `ToolsNotSupportedError` si le modèle ne gère pas les outils."""
        raise NotImplementedError

    # Formats des messages d'outils (format OpenAI par défaut)
    def assistant_message(self, response: LLMResponse) -> dict:
        """Message assistant à réinjecter dans la conversation après une demande d'appel d'outils."""
        return {
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                for c in response.tool_calls
            ],
        }

    def tool_message(self, result: ToolResult) -> dict:
        """Message transmettant le résultat d'un outil au LLM."""
        return {"role": "tool", "tool_call_id": result.call.id, "content": result.output}


LLM_PROVIDERS: ProviderRegistry[LLMProvider] = ProviderRegistry("LLM")


def _in_decision_list(model: str, settings: Settings) -> bool:
    """Le nom de base suffit : « nimble » couvre « nimble:latest » et « nimble:9b »."""
    name = (model or "").strip().lower()
    return name in settings.LLM_DECISION_MODELS or name.split(":")[0] in settings.LLM_DECISION_MODELS


@LLM_PROVIDERS.register("ollama")
class OllamaLLM(LLMProvider):
    """LLM local via Ollama. Les modèles qui annoncent la capacité « audio » (ex: gemma4, lfm3-audio) reçoivent
    l'enregistrement dans le champ `images` du message, comme une image."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        import ollama
        self.client = ollama.Client(host=settings.OLLAMA_HOST) if settings.OLLAMA_HOST else ollama.Client()
        self.model = settings.OLLAMA_MODEL

    @classmethod
    def describe(cls, settings: Settings) -> str:
        kind = ", modèle de décision" if _in_decision_list(settings.OLLAMA_MODEL, settings) else ""
        return f"Ollama ({settings.OLLAMA_MODEL} @ {settings.OLLAMA_HOST}{kind})"

    @property
    def host(self) -> str:
        return ollama_host(self.settings)

    def is_decision_model(self, model=None) -> bool:
        return _in_decision_list(model or self.model, self.settings)

    def decide(self, state, questions) -> dict:
        import httpx
        response = httpx.post(
            f"{self.host}/v1/systemone",
            json={"model": self.model, "state": state, "questions": questions},
            timeout=self.settings.LLM_DECISION_TIMEOUT,
        )
        if response.status_code != 200:
            try:
                detail = response.json().get("error", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"décision refusée par Ollama ({response.status_code}) : {detail}")
        return response.json()["answers"]

    def capabilities(self, model: str) -> list[str]:
        """Capacités annoncées par Ollama (completion, tools, vision, audio, thinking...). Lève si injoignable."""
        return ollama_capabilities(self.settings, model)

    def list_models(self) -> list[dict]:
        import httpx
        tags = httpx.get(f"{self.host}/api/tags", timeout=10).json().get("models", [])
        models = []
        for tag in tags:
            name = tag.get("name") or tag.get("model")
            try:
                capabilities = self.capabilities(name)
            except Exception:
                capabilities = []
            models.append({"name": name, "capabilities": capabilities, "size": tag.get("size", 0)})
        return sorted(models, key=lambda m: m["name"])

    def _detect_audio_input(self, model: str) -> bool:
        return "audio" in self.capabilities(model)

    def chat(self, messages, *, tools=None, audio_wav=None, model=None, stream=False, think=False, on_token=None) -> LLMResponse:
        if audio_wav:
            # Le dernier tour utilisateur porte l'enregistrement (Ollama refuse si le modèle n'a pas la capacité audio)
            messages = list(messages)
            idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
            messages[idx] = {**messages[idx], "images": [audio_wav]}
        kwargs = {"model": model or self.model, "messages": messages, "stream": stream}
        if tools:
            kwargs["tools"] = tools
        try:
            try:
                response = self.client.chat(**kwargs, think=think)
            except TypeError:
                # Fallback pour versions d'Ollama ne supportant pas l'argument explicite think
                response = self.client.chat(**kwargs)
            chunks = response if stream else [response]

            result = LLMResponse()
            for chunk in chunks:
                msg = chunk.message if hasattr(chunk, "message") else chunk.get("message", {})
                content = (msg.content if hasattr(msg, "content") else msg.get("content", "")) or ""
                if content:
                    result.text += content
                    if on_token and stream:
                        on_token(content)
                for i, tc in enumerate(getattr(msg, "tool_calls", None) or []):
                    result.tool_calls.append(ToolCall(
                        name=tc.function.name,
                        arguments=parse_arguments(tc.function.arguments),
                        id=f"call_{len(result.tool_calls)}",
                    ))
            return result
        except Exception as e:
            if tools and _is_tools_unsupported(e):
                raise ToolsNotSupportedError(str(e)) from e
            raise

    def assistant_message(self, response: LLMResponse) -> dict:
        return {
            "role": "assistant",
            "content": response.text,
            "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in response.tool_calls],
        }

    def tool_message(self, result: ToolResult) -> dict:
        return {"role": "tool", "content": result.output, "tool_name": result.call.name}


@LLM_PROVIDERS.register("openrouter")
class OpenRouterLLM(LLMProvider):
    """LLM cloud via l'API compatible OpenAI d'OpenRouter (supporte l'audio pour les modèles multimodaux)."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        from openai import OpenAI
        self.client = OpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=settings.OPENROUTER_API_KEY or "missing-key")
        self.model = settings.OPENROUTER_MODEL
        self._input_modalities: Optional[dict[str, list[str]]] = None

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"OpenRouter ({settings.OPENROUTER_MODEL})"

    def _detect_audio_input(self, model: str) -> bool:
        if self._input_modalities is None:
            import httpx
            response = httpx.get(f"{self.settings.OPENROUTER_BASE_URL.rstrip('/')}/models", timeout=10)
            response.raise_for_status()
            self._input_modalities = {
                m["id"]: (m.get("architecture") or {}).get("input_modalities") or [] for m in response.json().get("data", [])
            }
        # Modèle absent du catalogue (alias, modèle privé...) : on laisse l'API trancher
        modalities = self._input_modalities.get(model)
        return modalities is None or "audio" in modalities

    def chat(self, messages, *, tools=None, audio_wav=None, model=None, stream=False, think=False, on_token=None) -> LLMResponse:
        require_openrouter_key(self.settings)

        if audio_wav:
            # Le dernier tour utilisateur devient multimodal : texte éventuel + audio base64
            messages = list(messages)
            idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
            content = [{"type": "input_audio", "input_audio": {"data": base64.b64encode(audio_wav).decode("utf-8"), "format": "wav"}}]
            if messages[idx].get("content"):
                content.insert(0, {"type": "text", "text": messages[idx]["content"]})
            messages[idx] = {"role": "user", "content": content}

        kwargs = {"model": model or self.model, "messages": messages, "stream": stream}
        if tools:
            kwargs["tools"] = tools
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            if tools and _is_tools_unsupported(e):
                raise ToolsNotSupportedError(str(e)) from e
            raise

        if not stream:
            msg = response.choices[0].message
            return LLMResponse(
                text=msg.content or "",
                tool_calls=[
                    ToolCall(name=tc.function.name, arguments=parse_arguments(tc.function.arguments), id=tc.id)
                    for tc in (msg.tool_calls or [])
                ],
            )

        # Streaming : le texte est transmis au fil de l'eau, les appels d'outils arrivent par fragments indexés
        text, partial_calls = "", {}
        for chunk in response:
            if not chunk.choices or not chunk.choices[0].delta:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text += delta.content
                if on_token:
                    on_token(delta.content)
            for tc in delta.tool_calls or []:
                acc = partial_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    acc["id"] = tc.id
                if tc.function and tc.function.name:
                    acc["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    acc["arguments"] += tc.function.arguments

        calls = [
            ToolCall(name=c["name"], arguments=parse_arguments(c["arguments"]), id=c["id"] or f"call_{i}")
            for i, c in sorted(partial_calls.items())
        ]
        return LLMResponse(text=text, tool_calls=calls)


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
