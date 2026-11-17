"""
Préchargement des modèles Ollama dès le mot-clé (ou l'ouverture du micro de la PWA).

Un modèle Ollama déchargé (premier lancement, ou plus d'`OLLAMA_KEEP_ALIVE` sans demande) met plusieurs secondes
à revenir en mémoire : on le recharge pendant que l'utilisateur parle plutôt qu'après. `ModelWarmer.start()` ne
bloque jamais : un fil demande à Ollama les modèles déjà chargés (`/api/ps`) et charge les autres (`/api/generate`
sans prompt). Si la demande est prête alors qu'un chargement est en cours, `main.py` dit une phrase d'attente
(`OLLAMA_WARMUP_PHRASES`, tirée au hasard).

Modèles concernés : le LLM (`LLM_PROVIDER=ollama`), la transcription (`STT_PROVIDER=ollama`, ou transcription
de repli Ollama en mode direct) et la voix (`TTS_PROVIDER=ollama`).
"""

import random
import threading
from typing import Optional, Union

from core.config import Settings
from core.providers import ollama_host


def keep_alive_value(settings: Settings) -> Optional[Union[int, str]]:
    """`OLLAMA_KEEP_ALIVE` pour l'API d'Ollama : None (défaut du serveur), secondes (« 600 », « -1 » = toujours)
    ou durée (« 30m », « 2h »)."""
    value = (settings.OLLAMA_KEEP_ALIVE or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _with_tag(model: str) -> str:
    """Ollama liste « lfm3-audio:latest » pour un modèle demandé « lfm3-audio »."""
    return model if ":" in model else f"{model}:latest"


def models_to_warm(settings: Settings, llm_model: Optional[str] = None, stt_via_ollama: bool = False) -> list[str]:
    """Modèles Ollama utilisés par la configuration (sans doublon, dans l'ordre où ils servent)."""
    models = []
    if stt_via_ollama or settings.STT_PROVIDER.lower() == "ollama":
        models.append(settings.OLLAMA_STT_MODEL)
    if settings.LLM_PROVIDER.lower() == "ollama":
        models.append(llm_model or settings.OLLAMA_MODEL)
    if settings.TTS_PROVIDER.lower() == "ollama":
        models.append(settings.OLLAMA_TTS_MODEL)
    return list(dict.fromkeys(m for m in models if m))


def loaded_models(settings: Settings, timeout: float = 2.0) -> set[str]:
    """Modèles actuellement en mémoire dans Ollama (noms avec étiquette). Lève si Ollama est injoignable."""
    import httpx
    response = httpx.get(f"{ollama_host(settings)}/api/ps", timeout=timeout)
    response.raise_for_status()
    return {_with_tag(m.get("name") or m.get("model") or "") for m in response.json().get("models", [])}


def load_model(settings: Settings, model: str):
    """Charge un modèle en mémoire : /api/generate sans prompt (rien n'est généré)."""
    import httpx
    payload: dict = {"model": model}
    keep_alive = keep_alive_value(settings)
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    response = httpx.post(f"{ollama_host(settings)}/api/generate", json=payload, timeout=settings.OLLAMA_WARMUP_TIMEOUT)
    response.raise_for_status()


def waiting_phrase(settings: Settings, rng: Optional[random.Random] = None) -> str:
    """Une phrase d'attente au hasard (`OLLAMA_WARMUP_PHRASES`, séparées par « | »), vide s'il n'y en a pas."""
    phrases = [p.strip() for p in (settings.OLLAMA_WARMUP_PHRASES or "").split("|") if p.strip()]
    return (rng or random).choice(phrases) if phrases else ""


class ModelWarmer:
    """Précharge en arrière-plan les modèles Ollama froids. `settings` et `llm_model` sont relus à chaque
    départ (réglages modifiés à chaud, modèle changé depuis la PWA)."""

    def __init__(self, settings_getter, llm_model_getter=None, stt_via_ollama_getter=None):
        self._settings = settings_getter
        self._llm_model = llm_model_getter or (lambda: None)
        self._stt_via_ollama = stt_via_ollama_getter or (lambda: False)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loading: list[str] = []
        self._done = threading.Event()
        self._done.set()

    def start(self) -> bool:
        """Lance le préchargement sans attendre (même la liste des modèles est calculée dans le fil).
        False s'il est désactivé ou déjà en cours."""
        settings = self._settings()
        if not settings.OLLAMA_WARMUP_ENABLED:
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._done.clear()
            self._thread = threading.Thread(target=self._run, args=(settings,), name="ollama-warmup", daemon=True)
            self._thread.start()
            return True

    def loading(self) -> list[str]:
        """Modèles en cours de chargement (vide une fois prêts, ou s'ils l'étaient déjà)."""
        with self._lock:
            return list(self._loading) if not self._done.is_set() else []

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Attend la fin du préchargement (tests, diagnostic). True s'il est terminé."""
        return self._done.wait(timeout)

    def _run(self, settings: Settings):
        try:
            try:
                models = models_to_warm(settings, self._llm_model(), self._stt_via_ollama())
                if not models:
                    return
                loaded = loaded_models(settings)
            except Exception:
                return  # Ollama injoignable : l'erreur apparaîtra à la demande, avec son message habituel
            cold = [m for m in models if _with_tag(m) not in loaded]
            if not cold:
                return
            with self._lock:
                self._loading = cold
            print(f"\n🔥 [OLLAMA] Chargement de {', '.join(cold)} en mémoire…")
            for model in cold:
                try:
                    load_model(settings, model)
                except Exception as e:
                    print(f"⚠️ [OLLAMA] Préchargement de {model} impossible : {e}")
                with self._lock:
                    self._loading = [m for m in self._loading if m != model]
            print("🔥 [OLLAMA] Modèles prêts.")
        finally:
            with self._lock:
                self._loading = []
            self._done.set()


if __name__ == "__main__":
    import time

    from core.config import get_settings

    s = get_settings()
    print(f"🧪 [DEBUG] Ollama : {ollama_host(s)} · modèles de la configuration : {models_to_warm(s) or 'aucun'}")
    try:
        print(f"  • En mémoire : {sorted(loaded_models(s)) or 'aucun'}")
    except Exception as e:
        print(f"  • Ollama injoignable : {e}")
    warmer = ModelWarmer(lambda: s)
    t0 = time.monotonic()
    if warmer.start():
        warmer.wait()
    print(f"  • Préchargement terminé en {time.monotonic() - t0:.1f} s · phrase d'attente : « {waiting_phrase(s)} »")
