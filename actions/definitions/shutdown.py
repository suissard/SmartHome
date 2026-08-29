"""
Module d'action pour l'extinction complète de l'ordinateur.
Contient les métadonnées et le script bash d'extinction sécurisé.
"""

from actions.base import BaseAction

_SHUTDOWN_SCRIPT = r"""
if command -v systemctl >/dev/null 2>&1; then
    systemctl poweroff
elif command -v shutdown >/dev/null 2>&1; then
    shutdown -h now
else
    echo "Erreur : Commande d'extinction introuvable." >&2
    exit 1
fi
"""


class ShutdownAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SHUTDOWN",
            description="Éteindre complètement l'ordinateur.",
            script_code=_SHUTDOWN_SCRIPT,
            has_args=False,
            example_prompt="Éteins l'ordinateur s'il te plaît.",
            example_response="[SHUTDOWN] J'éteins l'ordinateur. Bonne nuit !"
        )


ACTIONS = [ShutdownAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/shutdown.py")
    print(f"Action : [{ACTIONS[0].tag}] chargée avec succès.")
