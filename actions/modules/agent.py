"""
Module d'action de mise en relation avec un agent externe (Hermes, Claude Code, Antigravity... voir core/agents.py).

L'outil `agent` (tag [AGENT nom]) ne fait rien sur le système : il vérifie que l'agent existe, puis AssistantCore
relie la conversation à cet agent (ses réponses arrivent directement, dans une autre voix) jusqu'au retour à
l'assistant (« reviens », « parler à Jarvis »). Les formulations simples (« passe-moi Hermes ») sont reconnues sans
LLM par core.agents.detect_switch() ; cet outil sert aux formulations libres.
Réservé aux rôles AGENTS_ROLES (retiré des autres comptes par core.users.tool_policy()).
"""

from typing import Dict, Optional, Tuple

from actions.base import BaseAction

AGENT_TOOL = "agent"


def _directory():
    from core.agents import AgentDirectory
    from core.settings_store import get_owner
    owner = get_owner()
    return owner.agents if owner is not None and hasattr(owner, "agents") else AgentDirectory()


class AgentAction(BaseAction):
    def __init__(self):
        agents = _directory().all()
        names = ", ".join(f"{a.name} ({a.label}{' : ' + a.description if a.description else ''})" for a in agents)
        super().__init__(
            tag="AGENT",
            description=(
                "Mettre l'utilisateur en relation directe avec un agent IA externe installé sur la machine, quand il "
                "demande à parler à cet agent ou à lui confier la conversation. Les messages suivants iront à "
                f"l'agent jusqu'à ce que l'utilisateur revienne. Agents disponibles : {names or 'aucun'}."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="Nom de l'agent",
            example_prompt="J'aimerais discuter un moment avec Hermes.",
            example_response="[AGENT hermes] Je vous passe Hermes.",
            enabled=bool(agents),
        )

    @property
    def parameters(self) -> dict:
        names = [a.name for a in _directory().all()]
        prop = {"type": "string", "description": self.args_hint}
        if names:
            prop["enum"] = names
        return {"type": "object", "properties": {"args": prop}, "required": ["args"]}

    def decision_choices(self) -> Optional[Dict[str, str]]:
        return {a.name: a.label for a in _directory().all()} or None

    def check(self, args: str = "") -> Tuple[int, str, str]:
        spec = _directory().get(args or "")
        if spec is None:
            known = ", ".join(a.name for a in _directory().all()) or "aucun"
            return 1, "", f"Agent « {args} » inconnu. Agents disponibles : {known}."
        return 0, f"Conversation reliée à {spec.label} : ses réponses arrivent directement.", ""

    def execute_sync(self, args: str = "", timeout: float = 10.0):
        return self.check(args)

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0):
        return self.check(args)

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        return self.check(args)[0] == 0

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        return self.execute(args, dry_run)


AGENT_ACTION = AgentAction()
ACTIONS = [AGENT_ACTION]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/agent.py")
    print(f"Action : [{AGENT_ACTION.tag}] (outil « {AGENT_ACTION.tool_name} »), active : {AGENT_ACTION.enabled}")
    print(AGENT_ACTION.description)
    print(AGENT_ACTION.check("hermes"))
