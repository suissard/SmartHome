from dataclasses import dataclass, field
import re
from typing import Optional, List, Dict


@dataclass
class CommandDefinition:
    """Définition structurée d'une commande système exécutable par le LLM."""
    tag: str
    description: str
    script_name: str
    has_args: bool = False
    args_hint: str = ""
    example_prompt: str = ""
    example_response: str = ""
    enabled: bool = True
    
    # Regex compilée pour détecter ce tag spécifique dans une réponse
    _pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        # Ex: \[SHUTDOWN\] ou \[VOLUME(?:\s+([^\]]+))?\]
        if self.has_args:
            pattern_str = rf"\[{re.escape(self.tag)}(?:\s+([^\]]+))?\]"
        else:
            pattern_str = rf"\[{re.escape(self.tag)}\]"
        self._pattern = re.compile(pattern_str, flags=re.IGNORECASE)

    @property
    def pattern(self) -> re.Pattern:
        if self._pattern is None:
            self.__post_init__()
        return self._pattern


# Registre des commandes natives du système SmartHome
COMMAND_REGISTRY: Dict[str, CommandDefinition] = {
    "SHUTDOWN": CommandDefinition(
        tag="SHUTDOWN",
        description="Éteindre complètement l'ordinateur.",
        script_name="shutdown.sh",
        has_args=False,
        example_prompt="Éteins l'ordinateur s'il te plaît.",
        example_response="[SHUTDOWN] J'éteins l'ordinateur. Bonne nuit !"
    ),
    "REBOOT": CommandDefinition(
        tag="REBOOT",
        description="Redémarrer l'ordinateur.",
        script_name="reboot.sh",
        has_args=False,
        example_prompt="Redémarre le système.",
        example_response="[REBOOT] Redémarrage de la machine en cours."
    ),
    "LOCK": CommandDefinition(
        tag="LOCK",
        description="Verrouiller la session de l'utilisateur.",
        script_name="lock.sh",
        has_args=False,
        example_prompt="Verrouille ma session.",
        example_response="[LOCK] Session verrouillée."
    ),
    "SCREEN_OFF": CommandDefinition(
        tag="SCREEN_OFF",
        description="Mettre en veille / éteindre les écrans.",
        script_name="screen_off.sh",
        has_args=False,
        example_prompt="Éteins les écrans.",
        example_response="[SCREEN_OFF] Écrans éteints."
    ),
    "VOLUME": CommandDefinition(
        tag="VOLUME",
        description="Régler le volume sonore (ex: 0 à 100, up, down).",
        script_name="volume.sh",
        has_args=True,
        args_hint="<0-100|up|down>",
        example_prompt="Mets le volume à 40%.",
        example_response="[VOLUME 40] Volume réglé à 40%."
    ),
    "MUTE": CommandDefinition(
        tag="MUTE",
        description="Couper le son de l'ordinateur (muet).",
        script_name="volume.sh",
        has_args=False,
        example_prompt="Coupe le son.",
        example_response="[MUTE] Son coupé."
    ),
    "UNMUTE": CommandDefinition(
        tag="UNMUTE",
        description="Réactiver le son de l'ordinateur.",
        script_name="volume.sh",
        has_args=False,
        example_prompt="Remets le son.",
        example_response="[UNMUTE] Son réactivé."
    ),

    "MEDIA_PLAY_PAUSE": CommandDefinition(
        tag="MEDIA_PLAY_PAUSE",
        description="Mettre en pause ou relancer la lecture multimédia (musique/vidéo).",
        script_name="media.sh",
        has_args=False,
        example_prompt="Mets la musique en pause.",
        example_response="[MEDIA_PLAY_PAUSE] Pause musicale."
    ),
    "MEDIA_NEXT": CommandDefinition(
        tag="MEDIA_NEXT",
        description="Passer à la piste / musique suivante.",
        script_name="media.sh",
        has_args=False,
        example_prompt="Passe à la chanson suivante.",
        example_response="[MEDIA_NEXT] Piste suivante."
    ),
    "MEDIA_PREV": CommandDefinition(
        tag="MEDIA_PREV",
        description="Revenir à la piste / musique précédente.",
        script_name="media.sh",
        has_args=False,
        example_prompt="Remets la musique précédente.",
        example_response="[MEDIA_PREV] Piste précédente."
    ),
    "OPEN": CommandDefinition(
        tag="OPEN",
        description="Lancer une application installée (ex: firefox, spotify, code).",
        script_name="open_app.sh",
        has_args=True,
        args_hint="<application>",
        example_prompt="Ouvre Firefox.",
        example_response="[OPEN firefox] J'ouvre Firefox."
    ),
    "NOTIFY": CommandDefinition(
        tag="NOTIFY",
        description="Afficher une notification sur le bureau.",
        script_name="notify.sh",
        has_args=True,
        args_hint="<message>",
        example_prompt="Affiche un rappel pour sortir le chien.",
        example_response="[NOTIFY Sortir le chien] Notification affichée."
    ),
}


def get_all_commands() -> List[CommandDefinition]:
    """Retourne la liste des commandes activées."""
    return [cmd for cmd in COMMAND_REGISTRY.values() if cmd.enabled]


def get_command_by_tag(tag: str) -> Optional[CommandDefinition]:
    """Recherche une commande par son tag exact (insensible à la casse)."""
    return COMMAND_REGISTRY.get(tag.upper())
