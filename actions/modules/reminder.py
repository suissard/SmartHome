"""
Module d'action des rappels et routines programmés (voir core/scheduler.py).

- [REMIND quand | message | répétition] / outil `remind` : « rappelle-moi dans 10 minutes de sortir le linge ».
- [ROUTINE quand | consigne | répétition] / outil `routine` : « tous les matins à 7h, donne-moi la météo » ; à
  l'échéance, la consigne est envoyée à l'assistant et sa réponse est annoncée.
- [REMINDERS] / outil `list_reminders` : rappels et routines en attente du compte.
- [CANCEL_REMINDER n°] / outil `cancel_reminder` : annule par numéro ou par mots du message.

Le compte qui crée le rappel est celui du tour en cours (core/turn_context.py) : chacun ne voit et n'annule que les
siens ; le micro de l'ordinateur crée ceux du foyer. L'échéance est lue en français ou en ISO 8601.
"""

import json
import re
import unicodedata
from typing import Optional, Tuple

from actions.base import PythonAction
from core.config import Settings, get_settings


def _settings() -> Settings:
    from core.settings_store import get_owner
    owner = get_owner()
    return owner.settings if owner is not None else get_settings()


def _scheduler():
    """Planificateur du cœur actif (réveillé à chaque ajout), sinon base seule (serveur MCP : lue par main.py)."""
    from core.settings_store import get_owner
    owner = get_owner()
    scheduler = getattr(owner, "scheduler", None) if owner is not None else None
    if scheduler is not None:
        return scheduler.store, scheduler.wake
    from core.scheduler import ReminderStore
    return ReminderStore(_settings()), (lambda: None)


def _owner_id() -> str:
    from core.turn_context import current_user
    from core.users import LOCAL_USER_ID
    user = current_user()
    return user.id if user is not None else LOCAL_USER_ID


def _owner():
    from core.turn_context import current_user
    from core.users import local_user
    return current_user() or local_user(_settings())


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


_SEPARATORS = (" : ", " - ", " pour ", " de ", " d'", " que ", " qu'", ", ")


def parse_request(args: str, settings: Settings) -> Tuple[object, str, str]:
    """« quand | message | répétition », JSON {"when", "message", "repeat"}, ou phrase libre « dans 10 min de … ».
    Retourne (échéance, message, répétition) ; ValueError si incompris."""
    from core.scheduler import REPEAT_NONE, parse_repeat, parse_when, split_repeat
    text = (args or "").strip()
    if not text:
        raise ValueError("Indique quand et quoi : « dans 10 minutes | sortir le linge ».")
    repeat = REPEAT_NONE
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide : {e.msg}.") from None
        when_text, message = str(data.get("when", "")), str(data.get("message", ""))
        repeat = parse_repeat(str(data.get("repeat", "") or ""))
    elif "|" in text:
        parts = [p.strip() for p in text.split("|")]
        when_text, message = parts[0], parts[1] if len(parts) > 1 else ""
        if len(parts) > 2 and parts[2]:
            repeat = parse_repeat(parts[2])
    else:
        when_text, message = text, ""
        for sep in _SEPARATORS:
            index = text.find(sep)
            while index > 0:
                try:
                    parse_when(split_repeat(text[:index])[0], default_hour=settings.SCHEDULER_DEFAULT_HOUR)
                    when_text, message = text[:index], text[index + len(sep):]
                    break
                except ValueError:
                    index = text.find(sep, index + 1)
            if message:
                break
    when_text, inline_repeat = split_repeat(when_text)
    repeat = repeat or inline_repeat
    message = message.strip(" .")
    if not message:
        raise ValueError("Que faut-il rappeler ? Format : « quand | message ».")
    max_chars = settings.SCHEDULER_MESSAGE_MAX_CHARS
    if len(message) > max_chars:
        raise ValueError(f"Message trop long ({len(message)} caractères, {max_chars} au plus).")
    return parse_when(when_text, default_hour=settings.SCHEDULER_DEFAULT_HOUR), message, repeat


class RemindAction(PythonAction):
    kind = "reminder"

    def __init__(self, tag="REMIND", description=None, args_hint=None, example_prompt=None, example_response=None):
        super().__init__(
            tag=tag,
            description=description or (
                "Programmer un rappel à une date ou après un délai, éventuellement répété : à l'échéance l'assistant "
                "le dit à voix haute et l'affiche sur le téléphone. Argument : « quand | message | répétition », "
                "quand = « dans 10 minutes », « à 18h30 », « demain 7h », « lundi 9h », « le 24 décembre 20h » ou "
                "ISO 8601 ; répétition facultative : tous les jours, en semaine, toutes les semaines."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint=args_hint or "quand | message | répétition facultative",
            example_prompt=example_prompt or "Rappelle-moi dans 20 minutes de sortir le gâteau.",
            example_response=example_response or "[REMIND dans 20 minutes | sortir le gâteau du four] C'est noté.",
            enabled=get_settings().SCHEDULER_ENABLED,
        )

    def run(self, args: str) -> Tuple[int, str, str]:
        from core.scheduler import REPEAT_LABELS, describe_due
        settings = _settings()
        due, message, repeat = parse_request(args, settings)
        store, wake = _scheduler()
        reminder = store.add(self.kind, message, due, repeat, user=_owner())
        wake()
        what = "Rappel" if self.kind == "reminder" else "Routine"
        when = describe_due(due) + ("" if not repeat else f", puis {REPEAT_LABELS[repeat]}")
        return 0, f"{what} n°{reminder.id} programmé(e) {when} : {message}", ""


class RoutineAction(RemindAction):
    kind = "routine"

    def __init__(self):
        super().__init__(
            tag="ROUTINE",
            description=(
                "Programmer une consigne que l'assistant exécutera lui-même à l'échéance (souvent répétée) et dont il "
                "annoncera le résultat : « tous les matins à 7h, donne-moi la météo ». Argument : « quand | consigne "
                "| répétition » (mêmes formats que remind). Pour un simple rappel de texte, utiliser remind."
            ),
            args_hint="quand | consigne pour l'assistant | répétition facultative",
            example_prompt="Tous les soirs à 22h, dis-moi les rappels de demain.",
            example_response="[ROUTINE 22h | liste mes rappels de demain | tous les jours] C'est programmé.",
        )


class ListRemindersAction(PythonAction):
    def __init__(self):
        super().__init__(
            tag="REMINDERS",
            description="Lister les rappels et routines en attente de l'utilisateur, avec leur numéro et leur échéance.",
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=False,
            example_prompt="Quels sont mes rappels ?",
            example_response="[REMINDERS] Je regarde.",
            enabled=get_settings().SCHEDULER_ENABLED,
        )

    @property
    def tool_name(self) -> str:
        return "list_reminders"

    def run(self, args: str) -> Tuple[int, str, str]:
        from core.scheduler import REPEAT_LABELS, describe_due
        store, _ = _scheduler()
        pending = store.active(_owner_id())
        if not pending:
            return 0, "Aucun rappel en attente.", ""
        lines = [f"n°{r.id} {'routine' if r.kind == 'routine' else 'rappel'} {describe_due(r.due)}"
                 f"{'' if not r.repeat else ' (' + REPEAT_LABELS.get(r.repeat, r.repeat) + ')'} : {r.message}"
                 for r in pending]
        return 0, "\n".join(lines), ""


class CancelReminderAction(PythonAction):
    def __init__(self):
        super().__init__(
            tag="CANCEL_REMINDER",
            description=("Annuler un rappel ou une routine en attente de l'utilisateur. Argument : son numéro (voir "
                         "list_reminders) ou des mots de son message."),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="numéro du rappel ou mots de son message",
            example_prompt="Annule le rappel du linge.",
            example_response="[CANCEL_REMINDER linge] C'est annulé.",
            enabled=get_settings().SCHEDULER_ENABLED,
        )

    def find(self, args: str, pending: list) -> Optional[list]:
        needle = re.sub(r"^(n°|no|num[eé]ro|#)\s*", "", (args or "").strip(), flags=re.IGNORECASE)
        if needle.isdigit():
            return [r for r in pending if r.id == int(needle)]
        words = [w for w in _fold(needle).split() if len(w) > 2]
        return [r for r in pending if words and all(w in _fold(r.message) for w in words)]

    def run(self, args: str) -> Tuple[int, str, str]:
        store, wake = _scheduler()
        owner = _owner_id()
        matches = self.find(args, store.active(owner))
        if not matches:
            return 1, "", f"Aucun rappel en attente ne correspond à « {args} »."
        if len(matches) > 1:
            listed = "; ".join(f"n°{r.id} : {r.message}" for r in matches)
            return 1, "", f"Plusieurs rappels correspondent, précise le numéro : {listed}."
        reminder = matches[0]
        store.cancel(reminder.id, owner)
        wake()
        return 0, f"Rappel n°{reminder.id} annulé : {reminder.message}", ""


ACTIONS = [RemindAction(), RoutineAction(), ListRemindersAction(), CancelReminderAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/reminder.py (aucun rappel n'est enregistré)")
    s = get_settings()
    for sample in ("dans 10 minutes | sortir le linge", "demain 7h | appeler maman | tous les jours",
                   "dans 20 minutes de sortir le gâteau", "tous les lundis à 9h : réunion d'équipe",
                   '{"when": "à 18h", "message": "arroser les plantes", "repeat": "en semaine"}', "bientôt"):
        try:
            due, message, repeat = parse_request(sample, s)
            print(f"  {sample!r} -> {due:%a %d/%m %H:%M} | {message} | {repeat or 'une fois'}")
        except ValueError as e:
            print(f"  {sample!r} -> ⚠️ {e}")
