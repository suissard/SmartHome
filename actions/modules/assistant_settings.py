"""
Module d'action de modification de ses propres paramètres par l'assistant.

- [GET_SETTINGS] / outil `get_settings` : liste les paramètres modifiables (ceux de l'interface web), leur valeur
  actuelle, leurs choix et leur prise d'effet. Lecture seule, sans confirmation.
- [SET_SETTING] / outil `set_setting` : modifie un ou plusieurs paramètres. La confirmation de l'utilisateur est
  TOUJOURS demandée (même si ACTIONS_CONFIRM_DANGEROUS=false), avec l'ancienne et la nouvelle valeur ; une valeur
  invalide est refusée avant toute question. Le changement passe par AssistantCore.update_settings() : mêmes
  validation, écriture (.env ou surcharge du profil) et application à chaud que l'interface web.

Réservé aux administrateurs (AUTH_ADMIN_TOOLS). Les champs de ACTIONS_SETTINGS_BLOCKED (clé API, confirmation des
actions sensibles) ne sont ni lus ni modifiables par l'assistant.
"""

import json
from typing import Optional, Tuple

from actions.base import BaseAction
from core.config import Settings, get_settings


def _settings() -> Settings:
    from core.settings_store import get_owner
    owner = get_owner()
    return owner.settings if owner is not None else get_settings()


def allowed_fields(settings: Settings) -> dict:
    """Paramètres accessibles à l'assistant : ceux de l'interface, moins ACTIONS_SETTINGS_BLOCKED."""
    from core.settings_store import EDITABLE
    blocked = {name.strip().upper() for name in settings.ACTIONS_SETTINGS_BLOCKED if name.strip()}
    return {name: info for name, info in EDITABLE.items() if name not in blocked}


def _display(value, max_chars: int) -> str:
    from core.settings_store import to_env_value
    text = to_env_value(value) if not isinstance(value, str) else value
    text = text if text != "" else "(vide)"
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def parse_changes(args: str, settings: Settings) -> dict:
    """`NOM=valeur` (un paramètre) ou objet JSON `{"NOM": valeur, ...}`. Lève ValueError si inconnu ou interdit."""
    text = (args or "").strip()
    if not text:
        raise ValueError("Indique le paramètre à modifier : NOM=valeur.")
    if text.startswith("{"):
        try:
            changes = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide : {e.msg}.") from None
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Objet JSON attendu : {\"NOM\": valeur}.")
    else:
        name, sep, value = text.partition("=")
        if not sep:
            raise ValueError("Format attendu : NOM=valeur.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        changes = {name: value}
    changes = {str(name).strip().upper(): value for name, value in changes.items()}
    allowed = allowed_fields(settings)
    refused = sorted(name for name in changes if name not in allowed)
    if refused:
        raise ValueError(f"Paramètre inconnu ou non modifiable par l'assistant : {', '.join(refused)}. "
                         "Utilise get_settings pour voir la liste.")
    return changes


def preview_changes(args: str, settings: Settings) -> Tuple[dict, list[tuple[str, object, object]]]:
    """Valide les changements sans rien écrire : (changements, [(nom, ancienne valeur, nouvelle valeur)])."""
    from core.settings_store import validate_changes
    changes = parse_changes(args, settings)
    new, changed = validate_changes(settings, changes)  # ValueError si une valeur est invalide
    before, after = settings.model_dump(), new.model_dump()
    return changes, [(name, before[name], after[name]) for name in changed]


def _describe(name: str) -> str:
    from core.settings_store import EDITABLE
    label, live = EDITABLE[name]
    return f"« {label} »" + ("" if live else " (au redémarrage)")


class GetSettingsAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="GET_SETTINGS",
            description=(
                "Lire tes propres paramètres modifiables (modèle, voix, prompt système, seuils...) avec leur valeur "
                "actuelle, avant d'en changer un avec set_setting ou quand l'utilisateur demande ta configuration. "
                "Argument facultatif : un mot pour filtrer (nom ou libellé)."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="<filtre facultatif, ex: modèle, voix, OLLAMA>",
            example_prompt="Quel modèle utilises-tu ?",
            example_response="[GET_SETTINGS modèle] Je regarde ma configuration.",
        )

    @property
    def parameters(self) -> dict:
        schema = super().parameters
        schema["required"] = []
        return schema

    def listing(self, args: str = "", settings: Optional[Settings] = None) -> str:
        from core.settings_store import _field_spec
        s = settings or _settings()
        needle = (args or "").strip().lower()
        values = s.model_dump()
        lines = []
        for name, (label, live) in allowed_fields(s).items():
            if needle and needle not in name.lower() and needle not in label.lower():
                continue
            spec = _field_spec(name)
            line = f"{name} = {_display(values[name], s.ACTIONS_SETTINGS_MAX_VALUE_CHARS)} — {label}"
            line += " [immédiat]" if live else " [au redémarrage]"
            if spec.get("options"):
                line += f" choix : {', '.join(str(o) for o in spec['options'])}"
            elif "min" in spec or "max" in spec:
                line += f" bornes : {spec.get('min', '')}..{spec.get('max', '')}"
            lines.append(line)
        if not lines:
            return f"Aucun paramètre ne correspond à « {args.strip()} »."
        return "\n".join(lines)

    def execute_sync(self, args: str = "", timeout: float = 10.0):
        return 0, self.listing(args), ""

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0):
        return self.execute_sync(args, timeout)

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        print(self.listing(args))
        return True

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        return self.execute(args, dry_run)


class SetSettingAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SET_SETTING",
            description=(
                "Modifier un de tes propres paramètres (modèle, voix, vitesse de parole, prompt système, seuils...), "
                "seulement quand l'utilisateur le demande explicitement. Argument : NOM=valeur (nom exact donné par "
                "get_settings), ou un objet JSON {\"NOM\": valeur} pour plusieurs paramètres liés. "
                "L'utilisateur doit confirmer le changement."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="NOM=valeur, ex: TTS_SPEECH_SPEED=1.2",
            example_prompt="Parle un peu plus vite.",
            example_response="[SET_SETTING TTS_SPEECH_SPEED=1.2] D'accord, je parlerai plus vite.",
            danger="confirm",
            force_confirm=True,
            done_message="Paramètre modifié.",
        )

    def confirm_text(self, args: str = "") -> str:
        _, changed = preview_changes(args, _settings())
        if not changed:
            raise ValueError("Ce paramètre a déjà cette valeur, rien à changer.")
        s = _settings()
        limit = min(s.ACTIONS_SETTINGS_MAX_VALUE_CHARS, 60)
        parts = [f"changer {_describe(name)} de « {_display(old, limit)} » à « {_display(new, limit)} »"
                 for name, old, new in changed]
        return " et ".join(parts)

    def apply(self, args: str = "") -> Tuple[int, str, str]:
        """Applique le changement (la confirmation a déjà eu lieu : ToolRegistry / ActionManager)."""
        from core import settings_store
        owner = settings_store.get_owner()
        if owner is None:
            return 1, "", "Modification des paramètres indisponible ici (aucun assistant actif)."
        try:
            changes, changed = preview_changes(args, owner.settings)
            if not changed:
                return 0, "Rien à changer : valeur déjà en place.", ""
            result = owner.update_settings(changes)
        except ValueError as e:
            return 1, "", str(e)
        if result["changed"]:
            owner.events.emit("settings_changed", None, changed=result["changed"])
        done = ", ".join(result["changed"]) or "aucun"
        out = f"Modifié : {done}."
        if result["restart"]:
            out += f" Pris en compte au prochain redémarrage de SmartHome : {', '.join(result['restart'])}."
        return 0, out, ""

    def execute_sync(self, args: str = "", timeout: float = 10.0):
        return self.apply(args)

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0):
        return self.apply(args)

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print(f"🔍 [ACTIONS] [DRY RUN] Tag [{self.tag}] avec args: {args}")
            return True
        code, out, err = self.apply(args)
        print(f"⚙️ [ACTIONS] [{self.tag}] {out or err}")
        return code == 0

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        return self.execute(args, dry_run)


GET_SETTINGS_ACTION = GetSettingsAction()
SET_SETTING_ACTION = SetSettingAction()
ACTIONS = [GET_SETTINGS_ACTION, SET_SETTING_ACTION]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/assistant_settings.py (sans rien modifier)")
    print(GET_SETTINGS_ACTION.listing("modèle"))
    for sample in ("TTS_SPEECH_SPEED=1.2", "OPENROUTER_API_KEY=x", "LLM_HISTORY_MESSAGES=abc"):
        try:
            print(f"  {sample} -> Tu confirmes : {SET_SETTING_ACTION.confirm_text(sample)} ?")
        except ValueError as e:
            print(f"  {sample} -> refusé : {e}")
