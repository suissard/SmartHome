"""
Module d'actions de recherche de fichiers et d'affichage d'images (voir core/images.py).

- [SEARCH_FILES motif] / outil `search_files` : cherche des fichiers par nom dans les seuls dossiers FILES_SEARCH_DIRS
  (tous les mots, accents et casse ignorés, ou motif *.png). Lecture seule.
- [SHOW_IMAGE chemin] / outil `show_image` : montre une image de ces dossiers dans l'interface web. L'action vérifie
  le fichier ; AssistantCore l'envoie ensuite au client (événement « image »).
Rien n'est lu en dehors des dossiers FILES_SEARCH_DIRS, que l'assistant ne peut pas modifier (ACTIONS_SETTINGS_BLOCKED).
"""

from typing import Tuple

from actions.base import BaseAction
from core.config import Settings, get_settings

SHOW_IMAGE_TOOL = "show_image"


def _settings() -> Settings:
    from core.settings_store import get_owner
    owner = get_owner()
    return owner.settings if owner is not None else get_settings()


class _PythonAction(BaseAction):
    """Action exécutée en Python (aucun script système), identique sous Linux et Windows."""

    def check(self, args: str = "") -> Tuple[int, str, str]:
        raise NotImplementedError

    def execute_sync(self, args: str = "", timeout: float = 10.0):
        return self.check(args)

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0):
        return self.check(args)

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        return dry_run or self.check(args)[0] == 0

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        return self.execute(args, dry_run)


class SearchFilesAction(_PythonAction):
    def __init__(self):
        super().__init__(
            tag="SEARCH_FILES",
            description=(
                "Chercher des fichiers par leur nom dans les dossiers de l'utilisateur ouverts à l'assistant "
                "(photos, captures, documents). Donne des mots du nom (« vacances plage ») ou un motif (« *.png »). "
                "Renvoie les chemins trouvés, les plus récents d'abord ; utilise show_image pour montrer une image."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="Mots du nom de fichier ou motif (ex: vacances plage, *.png)",
            example_prompt="Tu as des photos de la plage ?",
            example_response="[SEARCH_FILES plage] Je regarde.",
        )

    def check(self, args: str = "") -> Tuple[int, str, str]:
        from core.images import search_files, search_roots
        s = _settings()
        roots = search_roots(s)
        if not roots:
            return 1, "", "Aucun dossier de recherche n'existe (FILES_SEARCH_DIRS)."
        results = search_files(args, s)
        if not results:
            return 0, f"Aucun fichier ne correspond à « {args} ».", ""
        return 0, f"{len(results)} fichier(s) :\n" + "\n".join(results), ""


class ShowImageAction(_PythonAction):
    def __init__(self):
        super().__init__(
            tag="SHOW_IMAGE",
            description=(
                "Montrer une image à l'utilisateur dans l'interface web (chemin donné par search_files). "
                "Seules les images des dossiers ouverts à l'assistant peuvent être montrées."
            ),
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="Chemin de l'image (tel que renvoyé par search_files)",
            example_prompt="Montre-moi la dernière capture d'écran.",
            example_response="[SHOW_IMAGE ~/Images/capture.png] Voici la capture.",
        )

    def check(self, args: str = "") -> Tuple[int, str, str]:
        from core.images import ImageError, load_image
        s = _settings()
        if not s.IMAGES_ENABLED:
            return 1, "", "Les images sont désactivées (IMAGES_ENABLED=false)."
        try:
            image, shown = load_image(args, s)
        except ImageError as e:
            return 1, "", str(e)
        return 0, f"Image affichée à l'utilisateur : {shown}", ""


SEARCH_FILES_ACTION = SearchFilesAction()
SHOW_IMAGE_ACTION = ShowImageAction()
ACTIONS = [SEARCH_FILES_ACTION, SHOW_IMAGE_ACTION]


if __name__ == "__main__":
    import sys
    print("🧪 [DEBUG] Test du module actions/modules/files.py")
    query = " ".join(sys.argv[1:]) or "*.png"
    print(SEARCH_FILES_ACTION.check(query))
