"""
Base d'abstraction pour les actions système de SmartHome.
Chaque action hérite de BaseAction et encapsule ses métadonnées et son script d'exécution embarqué.
Prend en charge Linux (bash) et Windows (PowerShell / Win32).
"""

from dataclasses import dataclass, field
import re
import shlex
import subprocess
import sys
from typing import Dict, Optional, List, Tuple

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def percent_choices(up: str, down: str) -> Dict[str, str]:
    """Choix d'un réglage en pourcentage pour un modèle de décision : 0 à 100 % par pas de 10, plus ou moins."""
    choices = {str(v): f"{v} %" for v in range(0, 101, 10)}
    choices.update({"up": up, "down": down})
    return choices


@dataclass
class BaseAction:
    """Classe de base représentant une commande système autonome avec son script embarqué."""
    tag: str
    description: str
    script_code: str = ""
    script_code_windows: str = ""
    has_args: bool = False
    args_hint: str = ""
    example_prompt: str = ""
    example_response: str = ""
    enabled: bool = True
    # "safe" : exécution directe ; "confirm" : confirmation de l'utilisateur exigée (extinction, redémarrage...)
    danger: str = "safe"
    # Phrase prononcée après exécution par un modèle de décision (qui ne rédige pas de réponse).
    # Variables : ${ARGS} (argument choisi), ${COMMAND}, ${OUTPUT} (sortie du script). Vide = réponse type générique.
    done_message: str = ""
    # Confirmation exigée même si ACTIONS_CONFIRM_DANGEROUS=false (ex: l'assistant modifie ses propres paramètres)
    force_confirm: bool = False

    # Regex compilée pour détecter ce tag spécifique dans une réponse LLM
    _pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._init_pattern()

    def _init_pattern(self):
        if self.has_args:
            pattern_str = rf"\[{re.escape(self.tag)}(?:\s+([^\]]+))?\]"
        else:
            pattern_str = rf"\[{re.escape(self.tag)}\]"
        self._pattern = re.compile(pattern_str, flags=re.IGNORECASE)

    @property
    def pattern(self) -> re.Pattern:
        if self._pattern is None:
            self._init_pattern()
        return self._pattern

    @property
    def tool_name(self) -> str:
        """Nom de l'outil exposé au LLM en function calling (ex: VOLUME -> volume)."""
        return self.tag.lower()

    @property
    def parameters(self) -> dict:
        """Schéma JSON des arguments pour le function calling (un argument texte libre si has_args)."""
        if not self.has_args:
            return {"type": "object", "properties": {}}
        return {
            "type": "object",
            "properties": {"args": {"type": "string", "description": self.args_hint or "Argument de la commande"}},
            "required": ["args"],
        }

    def decision_choices(self) -> Optional[Dict[str, str]]:
        """Valeurs possibles de l'argument pour un modèle de décision, qui choisit au lieu d'écrire :
        {valeur: description prononçable}. None = argument libre, action non proposée à ces modèles."""
        return None

    def confirm_text(self, args: str = "") -> str:
        """Question de confirmation propre à cet appel (vide = description de l'action).
        Peut lever ValueError si l'argument est invalide : l'action est alors refusée sans rien demander."""
        return ""

    def build_args(self, args: str = "") -> List[str]:
        """Découpe les arguments passés pour le script bash ou powershell. Peut être surchargé."""
        args_clean = (args or "").strip()
        if not args_clean:
            return []
        try:
            return shlex.split(args_clean)
        except Exception:
            return args_clean.split()

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        """Exécute l'action de manière asynchrone non-bloquante."""
        if dry_run:
            print(f"🔍 [ACTIONS] [DRY RUN] Tag [{self.tag}] avec args: {args}")
            return True

        if sys.platform == "win32":
            return self.execute_windows(args, dry_run=dry_run)

        cmd_args = self.build_args(args)
        cmd_exec = ["bash", "-c", self.script_code, "_"] + cmd_args

        if not self.script_code.strip():
            print(f"⚠️ [ACTIONS] Aucun script défini pour [{self.tag}]")
            return False

        try:
            print(f"🚀 [ACTIONS] Exécution [{self.tag}] (args: {cmd_args})")
            subprocess.Popen(
                cmd_exec,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
        except Exception as e:
            print(f"❌ [ACTIONS] Erreur lors de l'exécution de [{self.tag}] : {e}")
            return False

    def execute_sync(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        """Exécute l'action de manière synchrone."""
        if sys.platform == "win32":
            return self.execute_sync_windows(args, timeout=timeout)

        cmd_args = self.build_args(args)
        cmd_exec = ["bash", "-c", self.script_code, "_"] + cmd_args

        try:
            print(f"🚀 [ACTIONS] Exécution synchrone [{self.tag}] (args: {cmd_args})")
            res = subprocess.run(cmd_exec, capture_output=True, text=True, timeout=timeout)
            if res.returncode == 0:
                print(f"✅ [ACTIONS] [{self.tag}] Succès : {res.stdout.strip() or 'OK'}")
            else:
                print(f"❌ [ACTIONS] [{self.tag}] Échec (code {res.returncode}) : {(res.stderr or res.stdout).strip()}")
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            print(f"❌ [ACTIONS] Erreur lors de l'exécution de [{self.tag}] : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        """Exécution asynchrone par défaut sous Windows."""
        code, out, err = self.execute_sync_windows(args, timeout=10.0)
        return code == 0

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        """Exécution synchrone par défaut sous Windows via PowerShell."""
        if not self.script_code_windows.strip():
            print(f"⚠️ [ACTIONS] Action [{self.tag}] non prise en charge sous Windows.")
            return -1, "", f"Action [{self.tag}] non prise en charge sous Windows."

        cmd_args = self.build_args(args)
        ps_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", self.script_code_windows] + cmd_args
        try:
            print(f"🚀 [ACTIONS] [Windows] Exécution [{self.tag}] (args: {cmd_args})")
            res = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=timeout)
            if res.returncode == 0:
                print(f"✅ [ACTIONS] [{self.tag}] Succès : {res.stdout.strip() or 'OK'}")
            else:
                print(f"❌ [ACTIONS] [{self.tag}] Échec (code {res.returncode}) : {(res.stderr or res.stdout).strip()}")
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            print(f"❌ [ACTIONS] Erreur Windows [{self.tag}] : {e}")
            return -1, "", str(e)


class PythonAction(BaseAction):
    """Action écrite en Python (aucun script) : mêmes résultats sous Linux et Windows, en function calling comme en
    mode tags. Les sous-classes implémentent `run(args) -> (code, sortie, erreur)` ; une ValueError devient un échec
    lisible par le LLM."""

    def run(self, args: str) -> Tuple[int, str, str]:
        raise NotImplementedError

    def execute_sync(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            return self.run(args)
        except ValueError as e:
            return 1, "", str(e)

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return self.execute_sync(args, timeout)

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print(f"🧪 [DRY-RUN] [{self.tag}] {args}")
            return True
        code, out, err = self.execute_sync(args)
        print(f"{'✅' if code == 0 else '⚠️'} [ACTIONS] [{self.tag}] {out or err}")
        return code == 0

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        return self.execute(args, dry_run)


# Alias de compatibilité
CommandDefinition = BaseAction


if __name__ == "__main__":
    print("🧪 [DEBUG] Test de BaseAction")
    sample_action = BaseAction(
        tag="ECHO_TEST",
        description="Action de test echo",
        script_code='echo "Hello from action: $1, $2"',
        script_code_windows='Write-Output "Hello from action: $args"',
        has_args=True
    )
    print(f"Action : [{sample_action.tag}]")
    code, out, err = sample_action.execute_sync("world 42")
    print(f"Code : {code} | Sortie : {out.strip()} | Erreur : {err.strip()}")
