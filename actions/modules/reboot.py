"""
Module d'action pour le redémarrage du système.
Contient les métadonnées et le script bash de redémarrage.
"""

from actions.base import BaseAction

_REBOOT_SCRIPT = r"""
if command -v systemctl >/dev/null 2>&1; then
    systemctl reboot
elif command -v reboot >/dev/null 2>&1; then
    reboot
else
    echo "Erreur : Commande de redémarrage introuvable." >&2
    exit 1
fi
"""


class RebootAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="REBOOT",
            description="Redémarrer l'ordinateur.",
            script_code=_REBOOT_SCRIPT,
            has_args=False,
            example_prompt="Redémarre le système.",
            example_response="[REBOOT] Redémarrage de la machine en cours."
        )


ACTIONS = [RebootAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/reboot.py")
    print(f"Action : [{ACTIONS[0].tag}] chargée avec succès.")
