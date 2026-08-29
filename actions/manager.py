import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

# Assure que la racine du projet est dans sys.path pour exécution autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from actions.base import BaseAction, CommandDefinition
from actions.registry import COMMAND_REGISTRY, get_all_commands, get_command_by_tag


class ActionManager:
    """Gestionnaire modulaire d'exécution des actions et constructeur de prompt dynamique."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def build_dynamic_system_prompt(self, base_prompt: str) -> str:
        """Génère le prompt système complet enrichi avec la liste des commandes disponibles."""
        if not self.enabled:
            return base_prompt

        commands = get_all_commands()
        if not commands:
            return base_prompt

        cmd_lines = []
        for cmd in commands:
            arg_str = f" {cmd.args_hint}" if cmd.has_args and cmd.args_hint else ""
            cmd_lines.append(f"- [{cmd.tag}{arg_str}] : {cmd.description}")

        examples_lines = []
        for cmd in commands:
            if cmd.example_prompt and cmd.example_response:
                examples_lines.append(f"  • Utilisateur : « {cmd.example_prompt} » -> Toi : {cmd.example_response}")

        dynamic_section = f"""

### ⚡ ACTIONS & COMMANDES SYSTÈME DISPONIBLES :
Tu as le contrôle du système et peux exécuter des actions physiques en insérant des tags spécifiques dans ta réponse.
Insère TOUJOURS le tag au début ou dans ta réponse quand l'utilisateur demande une action correspondante.

Tags disponibles :
{chr(10).join(cmd_lines)}

Règles impératives :
1. N'ajoute un tag QUE si l'utilisateur en fait expressément la demande.
2. Inclus TOUJOURS une courte phrase de confirmation vocale en plus du tag (les crochets et le tag seront retirés avant la synthèse vocale).
3. N'invente aucun autre format de tag.

Exemples de comportement attendu :
{chr(10).join(examples_lines[:5])}"""

        prompt_result = base_prompt.strip() + "\n" + dynamic_section

        # Enrichissement optionnel avec les outils des serveurs MCP connectés
        try:
            from core.config import MCP_CLIENT_ENABLED
            if MCP_CLIENT_ENABLED:
                from core.mcp_hub import get_mcp_hub
                hub = get_mcp_hub()
                mcp_section = hub.build_dynamic_prompt_section()
                if mcp_section:
                    prompt_result += "\n" + mcp_section
        except Exception:
            pass

        return prompt_result

    def extract_actions(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Analyse le texte, extrait les actions reconnues et retourne le texte nettoyé pour le TTS."""
        if not text:
            return "", []

        detected_actions: List[Dict[str, Any]] = []

        # Regex générique pour capturer tous les tags de type [COMMAND ...]
        general_pattern = re.compile(r"\[([A-Z_]+)(?:\s+([^\]]+))?\]")

        matches = list(general_pattern.finditer(text))
        for match in matches:
            tag_name = match.group(1).upper()
            raw_args = match.group(2).strip() if match.group(2) else ""

            cmd_def = get_command_by_tag(tag_name)
            if cmd_def:
                detected_actions.append({
                    "tag": tag_name,
                    "args": raw_args,
                    "definition": cmd_def,
                    "raw_match": match.group(0)
                })

        # Nettoyage de tous les tags [TAG ...] du texte pour la voix
        cleaned_text = general_pattern.sub("", text)
        # Nettoyage des espaces multiples résiduels
        cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

        return cleaned_text, detected_actions

    def execute_action(self, action: Dict[str, Any], dry_run: bool = False) -> bool:
        """Exécute l'action en déléguant son exécution à son propre script embarqué."""
        cmd_def: BaseAction = action["definition"]
        args = action.get("args", "")
        return cmd_def.execute(args, dry_run=dry_run)

    def process_response(self, response_text: str, dry_run: bool = False) -> str:
        """Point d'entrée principal pour traiter une réponse LLM :
        1. Extrait et exécute les actions détectées.
        2. Retourne le texte purifié prêt pour la synthèse vocale (TTS).
        """
        if not self.enabled:
            return response_text

        cleaned_text, actions = self.extract_actions(response_text)

        for act in actions:
            self.execute_action(act, dry_run=dry_run)

        return cleaned_text


# Instance singleton
_default_manager: Optional[ActionManager] = None


def get_action_manager() -> ActionManager:
    """Retourne l'instance globale d'ActionManager."""
    global _default_manager
    if _default_manager is None:
        from core.config import ACTIONS_ENABLED
        _default_manager = ActionManager(enabled=ACTIONS_ENABLED)
    return _default_manager



if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module ActionManager autonome")
    manager = ActionManager(enabled=True)

    test_prompt = manager.build_dynamic_system_prompt("Tu es un assistant vocal domotique.")
    print("\n--- Prompt Système Généré ---")
    print(test_prompt)
    print("------------------------------\n")

    test_responses = [
        "[SHUTDOWN] J'éteins l'ordinateur. Passez une excellente soirée !",
        "[VOLUME 30] Très bien, volume réglé à 30%.",
        "[OPEN firefox] J'ouvre votre navigateur Firefox.",
        "[MUTE] Son coupé immédiatement.",
        "Bonjour ! Il fait 22 degrés aujourd'hui."
    ]

    for resp in test_responses:
        print(f"\nTexte brut LLM : « {resp} »")
        clean, actions = manager.extract_actions(resp)
        print(f"Texte pour TTS : « {clean} »")
        print(f"Actions trouvées ({len(actions)}) : {[a['tag'] for a in actions]}")
        for act in actions:
            manager.execute_action(act, dry_run=True)
