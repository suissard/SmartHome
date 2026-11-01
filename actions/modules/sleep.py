"""
Module d'action de fin de conversation : remet l'assistant en veille (attente du mot-clé).
Aucun effet sur le système : c'est AssistantCore qui signale la fin (Reply.end_conversation) à l'orchestrateur.
"""

from actions.base import BaseAction


class SleepAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SLEEP",
            done_message="À bientôt !",
            description=(
                "Terminer la conversation et remettre l'assistant en veille, quand l'utilisateur prend congé "
                "ou n'a plus besoin de rien (au revoir, merci c'est tout, bonne nuit...). N'éteint pas l'ordinateur."
            ),
            script_code="exit 0",
            has_args=False,
            example_prompt="Merci, ce sera tout pour aujourd'hui.",
            example_response="[SLEEP] Avec plaisir, à bientôt !"
        )


SLEEP_ACTION = SleepAction()
ACTIONS = [SLEEP_ACTION]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/sleep.py")
    print(f"Action : [{SLEEP_ACTION.tag}] (outil « {SLEEP_ACTION.tool_name} ») chargée avec succès.")
