"""
Registre générique de fournisseurs (LLM, STT, TTS...).

Ajouter un fournisseur = écrire une classe héritant de l'interface du domaine et la décorer :

    @LLM_PROVIDERS.register("mon_llm", "alias")
    class MonLLM(LLMProvider):
        def __init__(self, settings: Settings): ...

Le nom configuré dans .env (ex: LLM_PROVIDER=mon_llm) sélectionne alors la classe via `create()`.
"""

import sys
from pathlib import Path
from typing import Callable, Generic, TypeVar

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

T = TypeVar("T")


class ProviderRegistry(Generic[T]):
    """Associe des noms de fournisseurs (et leurs alias) à des classes instanciables avec `Settings`."""

    def __init__(self, kind: str):
        self.kind = kind
        self._classes: dict[str, type[T]] = {}
        self._aliases: dict[str, str] = {}

    def register(self, name: str, *aliases: str) -> Callable[[type[T]], type[T]]:
        def decorator(cls: type[T]) -> type[T]:
            key = name.lower()
            self._classes[key] = cls
            cls.provider_name = key
            for alias in aliases:
                self._aliases[alias.lower()] = key
            return cls
        return decorator

    def names(self) -> list[str]:
        return sorted(self._classes)

    def get(self, name: str) -> type[T]:
        key = name.lower().strip()
        key = self._aliases.get(key, key)
        if key not in self._classes:
            raise ValueError(
                f"Fournisseur {self.kind} inconnu : '{name}'. Disponibles : {', '.join(self.names())}"
            )
        return self._classes[key]

    def create(self, name: str, settings: Settings | None = None) -> T:
        return self.get(name)(settings or get_settings())


def ollama_host(settings: Settings) -> str:
    return (settings.OLLAMA_HOST or "http://localhost:11434").rstrip("/")


def ollama_capabilities(settings: Settings, model: str) -> list[str]:
    """Capacités annoncées par Ollama pour un modèle (completion, tools, vision, audio, speech, thinking...).
    Lève si le serveur est injoignable ou le modèle absent."""
    import httpx
    response = httpx.post(f"{ollama_host(settings)}/api/show", json={"model": model}, timeout=10)
    response.raise_for_status()
    return response.json().get("capabilities") or []


def check_ollama_capability(settings: Settings, model: str, capability: str, usage: str):
    """Fournisseurs audio Ollama : refuse un modèle absent ou sans la capacité requise. Un serveur injoignable
    n'est pas bloquant (il peut démarrer après SmartHome) : l'erreur surviendra à la première demande."""
    import httpx
    try:
        capabilities = ollama_capabilities(settings, model)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Modèle Ollama « {model} » introuvable (ollama pull {model}) : {e.response.text}") from e
    except httpx.HTTPError as e:
        print(f"⚠️ Ollama injoignable ({ollama_host(settings)}) : capacités de {model} non vérifiées ({e}).")
        return
    if capability not in capabilities:
        raise RuntimeError(
            f"Le modèle Ollama « {model} » ne gère pas {usage} (capacités : {', '.join(capabilities) or 'aucune'}). "
            f"Exemple de modèle compatible : lfm3-audio."
        )


def require_openrouter_key(settings: Settings):
    """Lève une erreur explicite si la clé OpenRouter est absente (partagé par les fournisseurs OpenRouter)."""
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("Clé API OpenRouter manquante ! Renseignez OPENROUTER_API_KEY dans votre fichier .env.")


if __name__ == "__main__":
    print("🧪 [DEBUG] Fournisseurs enregistrés :")
    from llm.providers import LLM_PROVIDERS
    from audio.stt import STT_PROVIDERS
    from audio.tts import TTS_PROVIDERS
    for registry in (LLM_PROVIDERS, STT_PROVIDERS, TTS_PROVIDERS):
        s = get_settings()
        lines = [f"{n} → {registry.get(n).describe(s)}" for n in registry.names()]
        print(f"  • {registry.kind} :\n      " + "\n      ".join(lines))
