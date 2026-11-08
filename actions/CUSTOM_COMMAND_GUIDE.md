# Guide : créer une commande personnalisée SmartHome

Ce guide est envoyé à l'agent IA chargé de créer une nouvelle commande (action) SmartHome
par l'outil `create_command` (réservé aux superadministrateurs). Suis-le à la lettre.

## 1. Ce que tu dois produire

- **Un seul nouveau fichier** : `actions/modules/<nom>.py` (nom en `snake_case`, sans espace ni accent).
- **Rien d'autre**, sauf si la commande a besoin d'un réglage (voir §5) ou d'un test (voir §7).
- Ne modifie **jamais** : `actions/base.py`, `actions/registry.py`, `actions/manager.py`, `core/`, `gateway/`,
  `main.py`, les modules existants de `actions/modules/`, `.env` (secrets), `profiles/`, `pocketbase/`.
- N'exécute **aucune** commande git qui écrit (`commit`, `push`, `reset`, `checkout`...). L'humain relira et commitera.
- N'installe aucun paquet système ni Python. Si la commande a besoin d'un outil externe, le script vérifie sa
  présence (`command -v`) et échoue proprement avec un message clair sur stderr.

Le fichier est découvert automatiquement au démarrage par `actions/registry.py` : aucune déclaration ailleurs.
La commande devient à la fois un tag (`[MON_TAG args]`) et un outil de function calling (`mon_tag`).

## 2. Squelette obligatoire

```python
"""
Module d'action <rôle en une phrase>.
<Dépendances système éventuelles, ex: s'appuie sur playerctl.>
"""

from typing import List
from actions.base import BaseAction

_SCRIPT = r"""
ARG="${1:-}"
if [ -z "$ARG" ]; then
    echo "Usage : <nom> <argument>" >&2
    exit 1
fi
if ! command -v outil >/dev/null 2>&1; then
    echo "Erreur : outil introuvable." >&2
    exit 1
fi
outil "$ARG" || exit 1
echo "Fait : $ARG"
"""

_SCRIPT_WINDOWS = r"""
$arg = $args[0]
if (-not $arg) { Write-Error "Usage : <nom> <argument>"; exit 1 }
# ...
Write-Output "Fait : $arg"
"""


class MonAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MON_TAG",
            description="Phrase claire pour le LLM : ce que fait la commande et QUAND l'utiliser.",
            script_code=_SCRIPT,
            script_code_windows=_SCRIPT_WINDOWS,
            has_args=True,
            args_hint="<argument attendu, ex: 10m>",
            example_prompt="Phrase d'exemple de l'utilisateur.",
            example_response="[MON_TAG valeur] Courte confirmation vocale.",
            danger="safe",
            done_message="C'est fait.",
        )

    def build_args(self, args: str = "") -> List[str]:
        # Facultatif : valide et normalise l'argument ; retourner [] fait échouer proprement le script
        value = (args or "").strip()
        return [value] if value else []


ACTIONS = [MonAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/<nom>.py")
    action = ACTIONS[0]
    print(f"Action : [{action.tag}] (outil « {action.tool_name} ») chargée avec succès.")
    print(f"Arguments construits : {action.build_args('exemple')}")
```

## 3. Règles sur les champs de `BaseAction`

| Champ | Règle |
|---|---|
| `tag` | MAJUSCULES et `_` uniquement (`[A-Z_]+`), **unique** (vérifie `actions/modules/` et `python -m actions.registry`). Le nom d'outil est `tag.lower()`. |
| `description` | En français, une ou deux phrases : l'effet **et** le moment où l'utiliser. C'est ce que lit le LLM pour choisir. |
| `script_code` | Bash, **jamais vide**, doit passer `bash -n`. Arguments reçus en `$1`, `$2`... Code retour 0 = succès, sinon échec avec message sur stderr. Une ligne de résultat courte sur stdout (elle est rendue au LLM). |
| `script_code_windows` | PowerShell équivalent (arguments dans `$args`). Si impossible sous Windows, laisse `""` : l'action y sera refusée proprement. |
| `has_args` / `args_hint` | `has_args=True` seulement si un argument est nécessaire ; `args_hint` décrit le format attendu. |
| `example_prompt` / `example_response` | Un exemple réaliste ; la réponse contient le tag puis une courte phrase prononçable. |
| `danger` | `"safe"` par défaut. `"confirm"` si l'action est destructive, irréversible, coûteuse, envoie quelque chose à l'extérieur, ou coupe le travail en cours (extinction, suppression, envoi de message...). |
| `done_message` | Phrase dite après exécution par un modèle de décision. Variables `string.Template` : `${ARGS}`, `${OUTPUT}`, `${COMMAND}`. |
| `force_confirm` | `False` par défaut. `True` : confirmation demandée même si l'utilisateur a désactivé `ACTIONS_CONFIRM_DANGEROUS` (réservé aux actions qui touchent à l'assistant lui-même). |
| `confirm_text(args)` | Méthode facultative : question de confirmation propre à l'appel (vide = `description`). Lever `ValueError` refuse l'appel sans rien demander. |

Facultatif : `decision_choices()` renvoie `{valeur: description prononçable}` (petit ensemble fermé de valeurs)
pour que les modèles de décision, qui ne rédigent pas de texte, puissent utiliser la commande. Sans elle, une
commande à argument libre ne leur est pas proposée. Exemple : `percent_choices()` de `actions/base.py`.

## 4. Sécurité du script

- Toujours citer les variables (`"$1"`, `"$ARG"`), jamais d'`eval`, jamais de `sh -c "$1"`.
- Valider l'argument (liste blanche, regex, bornes numériques) dans `build_args()` **ou** dans le script.
- Pas de `sudo`, pas d'écriture hors du dossier utilisateur, pas de suppression récursive.
- Une action longue (> 10 s, limite `ACTIONS_TIMEOUT`) doit se lancer en arrière-plan
  (`systemd-run --user`, `nohup ... &`) et rendre la main tout de suite (voir `actions/modules/timer.py`).
- Aucun accès réseau vers un service tiers sauf demande explicite de la consigne (projet 100 % local).

## 5. Réglages (seulement si nécessaire)

Aucune valeur de paramétrage écrite en dur (dossier, URL, limite...). Si la commande en a besoin :
1. Ajoute un champ typé avec valeur par défaut dans la classe `Settings` de `core/config.py`, section `ACTIONS_`,
   nommé `ACTIONS_<TAG>_<NOM>`, avec un commentaire d'une ligne au-dessus.
2. Ajoute la ligne commentée correspondante dans `.env.example` (section actions).
3. Lis-le dans le module avec `from core.config import get_settings` puis `get_settings().ACTIONS_<TAG>_<NOM>`.
N'écris **pas** dans `.env`.

## 6. Exemples à imiter

- Sans argument : `actions/modules/lock.py`, `actions/modules/sleep.py`.
- Avec argument validé et lancement en arrière-plan : `actions/modules/timer.py`.
- Avec liste blanche de valeurs : `actions/modules/open_app.py`.
- Avec confirmation : `actions/modules/shutdown.py`.
Lis au moins un de ces fichiers avant d'écrire le tien, et `AGENTS.md` pour l'architecture.

## 7. Vérifications obligatoires avant de terminer

Exécute depuis la racine du projet, avec l'environnement virtuel s'il existe (`.venv/bin/python`) :

```bash
python -m actions.modules.<nom>              # le bloc __main__ s'exécute sans erreur
python -m actions.registry                    # le nouveau tag apparaît, aucun avertissement de chargement
bash -n <<< "$(python -c 'from actions.modules.<nom> import ACTIONS; print(ACTIONS[0].script_code)')"
python -m unittest tests.test_actions_unit
```

N'exécute **pas** la commande pour de vrai si elle a un effet visible ou destructif : teste `build_args()`
et la syntaxe. Si un test échoue, corrige ton module (pas les tests existants).
Tu peux ajouter un test dans `tests/test_actions_unit.py` (classe à part, `unittest`, sans effet réel).

## 8. Compte rendu final

Termine par un court compte rendu en français, en texte brut :
- fichier(s) créé(s) ou modifié(s) ;
- tag, nom d'outil, niveau de danger, argument attendu ;
- résultat des vérifications du §7 ;
- dépendances système éventuelles, et rappel : la commande sera disponible **après redémarrage de SmartHome**.
Si la consigne est dangereuse, illégale, impossible ou trop vague, ne crée rien et explique pourquoi.
