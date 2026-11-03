"""
Assistant de configuration pas à pas (`./start.sh --setup`, ou « Configurer pas à pas » dans le menu de démarrage).

Il détecte ce qui est disponible (clé OpenRouter, modèles Ollama et leurs capacités), pose une question par étape
et crée le profil `profiles/perso.env` (non versionné). La clé OpenRouter va dans `.env`, jamais dans un profil.
"""

import sys
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core import profiles
from core.config import BASE_DIR, get_settings
from core.menu import GoBack, Option, answered, ask_text, choose, note, style
from core.settings_store import save_to_env, to_env_value

PERSONAL_PROFILE = "perso"
WHISPER_SIZES = [("tiny", "Très rapide, moins précis"), ("base", "Rapide"), ("small", "Bon équilibre"),
                 ("medium", "Plus précis, plus lent")]
OLLAMA_VOICES = ["female-french", "male-french"]


def _base(model: str) -> str:
    return model.split(":")[0].lower()


def _ollama_models(settings) -> Optional[list[dict]]:
    """Modèles installés avec leurs capacités, None si Ollama ne répond pas."""
    from llm.providers import LLM_PROVIDERS
    try:
        return LLM_PROVIDERS.create("ollama", settings).list_models()
    except Exception:
        return None


def _key_is_valid(settings, key: str) -> Optional[bool]:
    """Vérifie la clé auprès d'OpenRouter (None si le service est injoignable)."""
    import httpx
    try:
        response = httpx.get(f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/key",
                             headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except httpx.HTTPError:
        return None
    return response.status_code == 200


def _accepts_audio_online(settings, model: str) -> bool:
    from llm.providers import LLM_PROVIDERS
    return LLM_PROVIDERS.create("openrouter", settings).accepts_audio(model)


class Wizard:
    STEPS = ["step_key", "step_local", "step_brain", "step_listen", "step_voice", "step_comfort"]

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.new_key = ""
        self.use_cloud = False
        self.models: list[dict] = []
        self.brain = ""            # modèle qui réfléchit
        self.brain_local = False
        self.brain_audio = False   # il comprend l'audio : l'étape d'écoute propose le mode direct
        self.brain_decision = False
        self.values: dict[str, dict[str, str]] = {}   # réglages retenus, par étape
        self.summary: dict[str, str] = {}

    def title(self, step: str, text: str) -> str:
        return f"Étape {self.STEPS.index(step) + 1}/{len(self.STEPS)} · {text}"

    def ask(self, step: str, text: str, options: list[Option], index: int = 0) -> Option:
        return choose(self.title(step, text), options, index, can_go_back=step != self.STEPS[0])

    def second_model_tag(self, model: str) -> str:
        """Prévient quand un modèle audio s'ajoute au modèle qui réfléchit dans Ollama."""
        return "2e modèle Ollama en mémoire, machine plus sollicitée" if self.brain_local and model != self.brain else ""

    # ---- Étapes ----
    def step_key(self):
        stored = bool(self.settings.OPENROUTER_API_KEY)
        options = [Option("Oui, garder la clé enregistrée", "keep"), Option("Remplacer la clé", "new")] if stored \
            else [Option("Oui, je saisis ma clé", "new", "Elle reste dans le fichier .env de cet ordinateur")]
        options.append(Option("Non, pas d'OpenRouter", "none", "Aucune demande ne partira en ligne"))
        answer = self.ask("step_key", "Avez-vous une clé OpenRouter ?", options).value
        self.new_key = ""
        self.use_cloud = answer != "none"
        if answer == "new":
            self.new_key = ask_text("Clé OpenRouter (saisie masquée)", secret=True)
            if not self.new_key:
                self.use_cloud = False
            elif _key_is_valid(self.settings, self.new_key) is False:
                note("OpenRouter refuse cette clé : elle sera tout de même enregistrée, à vous de la vérifier.")
        answered("OpenRouter", "oui" if self.use_cloud else "non")

    def step_local(self):
        while True:
            models = _ollama_models(self.settings)
            if models:
                first = Option("Oui, avec Ollama", True, f"{len(models)} modèle(s) installé(s)")
            else:
                first = Option("Réessayer", None, "Ollama ne répond pas ou n'a aucun modèle : lancez-le, puis réessayez")
            answer = self.ask("step_local", "Voulez-vous faire tourner un modèle d'IA sur cet ordinateur ?", [
                first, Option("Non", False, "Whisper et Piper restent disponibles pour l'écoute et la voix"),
            ]).value
            if answer is None:
                continue
            if answer is False and not self.use_cloud:
                note("Il faut un modèle pour réfléchir : une clé OpenRouter ou un modèle local.")
                raise GoBack
            self.models = models or [] if answer else []
            answered("Modèle local", "oui" if answer else "non")
            return

    def step_brain(self):
        options = []
        for model in self.models:
            caps = model["capabilities"]
            decision = "decision" in caps or _base(model["name"]) in self.settings.LLM_DECISION_MODELS
            detail = "Choisit une commande sans rédiger de réponse" if decision else ", ".join(caps)
            options.append(Option(model["name"], ("ollama", model["name"], "audio" in caps, decision),
                                  detail, "décision · local" if decision else "local"))
        if self.use_cloud:
            for profile in ("mix", "cloud"):
                name = profiles.profile_values(profile)["OPENROUTER_MODEL"]
                options.append(Option(name, ("openrouter", name, None, False), tag="en ligne"))
            options.append(Option("Autre modèle OpenRouter…", ("openrouter", "", None, False)))
        provider, name, audio, decision = self.ask("step_brain", "Quel modèle doit réfléchir ?", options).value
        name = name or ask_text("Identifiant du modèle (ex: google/gemini-2.5-flash)")
        if not name:
            raise GoBack
        self.brain, self.brain_local, self.brain_decision = name, provider == "ollama", decision
        self.brain_audio = _accepts_audio_online(self.settings, name) if audio is None else audio
        values = {"LLM_PROVIDER": provider, "OLLAMA_MODEL" if self.brain_local else "OPENROUTER_MODEL": name}
        if decision and _base(name) not in self.settings.LLM_DECISION_MODELS:
            values["LLM_DECISION_MODELS"] = ",".join([*self.settings.LLM_DECISION_MODELS, _base(name)])
        self.values["step_brain"] = values
        self.summary["Réflexion"] = name
        answered("Réflexion", name)

    def step_listen(self):
        options = []
        if self.brain_audio and not self.brain_decision:
            options.append(Option(f"{self.brain} écoute directement", ("direct", ""), "Pas de transcription séparée"))
        options.append(Option("Whisper", ("whisper", ""), "Local, sans Ollama, le moins gourmand"))
        for model in self.models:
            if "audio" in model["capabilities"]:
                options.append(Option(model["name"], ("ollama", model["name"]), "Transcription par Ollama",
                                      self.second_model_tag(model["name"])))
        if self.use_cloud:
            options.append(Option("OpenRouter", ("openrouter", ""), self.settings.OPENROUTER_STT_MODEL, "en ligne"))
        option = self.ask("step_listen", "Comment transcrire votre voix ?", options)
        (engine, model), label = option.value, option.label
        values = {"STT_PROVIDER": engine}
        if engine == "ollama":
            values["OLLAMA_STT_MODEL"] = model
        elif engine == "direct":
            values["STT_FALLBACK_PROVIDER"] = "whisper"
        if engine in ("whisper", "direct"):
            sizes = [Option(size, size, detail) for size, detail in WHISPER_SIZES]
            current = next((i for i, (size, _) in enumerate(WHISPER_SIZES) if size == self.settings.WHISPER_MODEL), 1)
            question = "Taille de Whisper" if engine == "whisper" else "Taille de Whisper (repli si le modèle n'écoute pas)"
            values["WHISPER_MODEL"] = self.ask("step_listen", question, sizes, current).value
        self.values["step_listen"] = values
        self.summary["Écoute"] = label
        answered("Écoute", label)

    def step_voice(self):
        options = [Option("Piper", ("piper", ""), "Local, rapide, sans Ollama")]
        for model in self.models:
            if "speech" in model["capabilities"]:
                options.append(Option(model["name"], ("ollama", model["name"]), "Voix générée par Ollama",
                                      self.second_model_tag(model["name"])))
        if self.use_cloud:
            options.append(Option("OpenRouter", ("openrouter", ""), self.settings.OPENROUTER_TTS_MODEL, "en ligne"))
        option = self.ask("step_voice", "Quelle voix pour l'assistant ?", options)
        engine, model = option.value
        values = {"TTS_PROVIDER": engine}
        if engine == "piper":
            voices = sorted(p.stem for p in (BASE_DIR / "voices").glob("*.onnx"))
            if len(voices) > 1:
                values["TTS_VOICE"] = self.ask("step_voice", "Quelle voix Piper ?", [Option(v, v) for v in voices]).value
        elif engine == "ollama":
            values["OLLAMA_TTS_MODEL"] = model
            values["OLLAMA_TTS_VOICE"] = self.ask("step_voice", "Quelle voix ?", [Option(v, v) for v in OLLAMA_VOICES]).value
        self.values["step_voice"] = values
        self.summary["Voix"] = option.label
        answered("Voix", option.label)

    def step_comfort(self):
        pause = self.ask("step_comfort", "Mettre vos médias en pause pendant que vous parlez à l'assistant ?", [
            Option("Oui", True, "Musique et vidéos reprennent à la fin de l'échange"), Option("Non", False),
        ]).value
        web = self.ask("step_comfort", "Activer l'interface web ?", [
            Option("Oui", True, f"Accessible sur http://{self.settings.GATEWAY_HOST}:{self.settings.GATEWAY_PORT}"),
            Option("Non", False, "L'assistant reste uniquement vocal"),
        ], 0 if self.settings.GATEWAY_ENABLED else 1).value
        self.values["step_comfort"] = {"MEDIA_PAUSE_ENABLED": to_env_value(pause), "GATEWAY_ENABLED": to_env_value(web)}
        self.summary["Médias en pause"] = "oui" if pause else "non"
        self.summary["Interface web"] = "oui" if web else "non"

    # ---- Déroulement ----
    def run(self) -> Optional[str]:
        """Pose les questions. Retourne le nom du profil créé, ou None si l'utilisateur annule."""
        while True:
            step = 0
            while step < len(self.STEPS):
                try:
                    getattr(self, self.STEPS[step])()
                    step += 1
                except GoBack:
                    step = max(step - 1, 0)
            for label, value in self.summary.items():
                print(f"    {style('2', label + ' :')} {value}", file=sys.stderr)
            answer = choose("Tout est prêt", [
                Option("Enregistrer et démarrer", "save"), Option("Recommencer", "again"), Option("Annuler", "cancel"),
            ]).value
            if answer == "save":
                return self.save()
            if answer == "cancel":
                return None

    def settings_values(self) -> dict[str, str]:
        return {k: v for step in self.STEPS for k, v in self.values.get(step, {}).items()}

    def description(self) -> str:
        return f"Perso : {self.summary['Réflexion']} réfléchit, écoute {self.summary['Écoute']}, voix {self.summary['Voix']}"

    def save(self) -> str:
        if self.new_key:
            save_to_env(self.settings.model_copy(update={"OPENROUTER_API_KEY": self.new_key}), ["OPENROUTER_API_KEY"])
        path = profiles.PROFILES_DIR / f"{PERSONAL_PROFILE}.env"
        lines = [f"# {self.description()}", "# Créé par ./start.sh --setup"]
        lines += [f"{key}={value}" for key, value in self.settings_values().items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Les modifications faites depuis l'interface web portaient sur l'ancienne configuration
        profiles.local_overrides_path(PERSONAL_PROFILE).unlink(missing_ok=True)
        return PERSONAL_PROFILE


def run_wizard() -> Optional[str]:
    return Wizard().run()


if __name__ == "__main__":
    print(f"🧪 [DEBUG] Profil créé : {run_wizard()}")
