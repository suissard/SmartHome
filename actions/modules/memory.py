"""
Module d'action de la mémoire à long terme (voir core/memory.py).

- [REMEMBER fait] / outil `remember` : retenir un fait durable sur l'utilisateur ou le foyer.
- [MEMORIES] / outil `list_memories` : souvenirs du compte, avec leur numéro.
- [FORGET_MEMORY n° ou mots] / outil `forget_memory` : effacer un souvenir.

Les souvenirs appartiennent au compte du tour en cours (core/turn_context.py) ; hors d'un tour (serveur MCP) et au
micro de l'ordinateur, ce sont ceux du foyer.
"""

from typing import Tuple

from actions.base import PythonAction
from core.config import get_settings


def _store():
    from core.settings_store import get_owner
    owner = get_owner()
    store = getattr(owner, "memory", None) if owner is not None else None
    if store is not None:
        return store
    from core.memory import MemoryStore
    return MemoryStore()


def _owner_id() -> str:
    from core.turn_context import current_user
    from core.users import LOCAL_USER_ID
    user = current_user()
    return user.id if user is not None else LOCAL_USER_ID


class RememberAction(PythonAction):
    def __init__(self):
        super().__init__(
            tag="REMEMBER",
            description=(
                "Retenir durablement un fait utile sur l'utilisateur ou son foyer (prénoms, goûts, habitudes, "
                "informations pratiques), quand il le demande (« retiens que… », « souviens-toi que… ») ou quand il "
                "partage une préférence durable. Une phrase courte et autonome, à la 3e personne si besoin "
                "(« Sa fille s'appelle Léa. »). Jamais de mot de passe ni de donnée bancaire."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="le fait à retenir, en une phrase",
            example_prompt="Retiens que je préfère le thé au café.",
            example_response="[REMEMBER Préfère le thé au café.] C'est noté.",
        )

    @property
    def enabled(self) -> bool:
        return bool(get_settings().MEMORY_ENABLED)

    @enabled.setter
    def enabled(self, _value: bool):
        pass

    def run(self, args: str) -> Tuple[int, str, str]:
        memory, created = _store().remember(_owner_id(), args)
        verb = "Retenu" if created else "Souvenir mis à jour"
        return 0, f"{verb} (n°{memory.id}) : {memory.text}", ""


class ListMemoriesAction(PythonAction):
    def __init__(self):
        super().__init__(
            tag="MEMORIES",
            description="Lister ce que l'assistant a retenu sur l'utilisateur (souvenirs numérotés), quand il le demande.",
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=False,
            example_prompt="Qu'est-ce que tu sais de moi ?",
            example_response="[MEMORIES] Voici ce que j'ai retenu.",
        )

    @property
    def enabled(self) -> bool:
        return bool(get_settings().MEMORY_ENABLED)

    @enabled.setter
    def enabled(self, _value: bool):
        pass

    @property
    def tool_name(self) -> str:
        return "list_memories"

    def run(self, args: str) -> Tuple[int, str, str]:
        memories = _store().all(_owner_id())
        if not memories:
            return 0, "Aucun souvenir enregistré.", ""
        return 0, "\n".join(f"n°{m.id} : {m.text}" for m in memories), ""


class ForgetMemoryAction(PythonAction):
    def __init__(self):
        super().__init__(
            tag="FORGET_MEMORY",
            description=("Effacer un souvenir quand l'utilisateur le demande (« oublie que… »). Argument : son numéro "
                         "(voir list_memories) ou des mots de son texte."),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="numéro du souvenir ou mots de son texte",
            example_prompt="Oublie ce que je t'ai dit sur le café.",
            example_response="[FORGET_MEMORY café] C'est oublié.",
        )

    @property
    def enabled(self) -> bool:
        return bool(get_settings().MEMORY_ENABLED)

    @enabled.setter
    def enabled(self, _value: bool):
        pass

    def run(self, args: str) -> Tuple[int, str, str]:
        store, owner = _store(), _owner_id()
        matches = store.find(owner, args)
        if not matches:
            return 1, "", f"Aucun souvenir ne correspond à « {args} »."
        if len(matches) > 1:
            listed = "; ".join(f"n°{m.id} : {m.text}" for m in matches)
            return 1, "", f"Plusieurs souvenirs correspondent, précise le numéro : {listed}."
        store.forget(owner, matches[0].id)
        return 0, f"Oublié : {matches[0].text}", ""


ACTIONS = [RememberAction(), ListMemoriesAction(), ForgetMemoryAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/memory.py (souvenirs du foyer)")
    print(ListMemoriesAction().execute_sync())
