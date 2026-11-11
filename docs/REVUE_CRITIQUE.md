# Revue critique — SmartHome (novembre 2026)

Revue faite sur `main` (45b7c83) avec les modifications non commitées présentes à ce moment-là (agents externes,
images, nom de l'assistant). Ces modifications sont figées telles quelles dans le premier commit de la branche
`review/securite-robustesse` (7d29c79), séparées des correctifs qui suivent.

État de départ : 270 tests `unittest`, tous verts (`.venv/bin/python -m unittest discover -s tests -t .`).
État d'arrivée : 277 tests, tous verts.

---

## 1. Ce qui est solide

- **Architecture claire** : cœur `AssistantCore` indépendant des entrées/sorties, bus d'événements, registres de
  fournisseurs, satellites (micro local, PWA, MCP) branchés sur le même cœur. Ajouter un fournisseur ne demande
  aucun `if PROVIDER == ...`.
- **Sécurité pensée dès le départ** : aucun shell pour les agents, CSP stricte, refus d'écouter hors loopback sans
  jeton, filtres PocketBase sur des identifiants validés, chemins d'images résolus et bornés, format réel des
  images vérifié, confirmation forcée pour `set_setting`.
- **Tests** nombreux et rapides (7 s), avec de vrais faux fournisseurs plutôt que des mocks fragiles.
- **Documentation** (`AGENTS.md`) exhaustive et tenue à jour.

## 2. Problèmes trouvés

Gravité : 🔴 à corriger tout de suite · 🟠 important · 🟡 dette technique.

| # | Gravité | Problème | État |
|---|---|---|---|
| 1 | 🔴 | **Escalade de droits par expiration de session.** Une session WebSocket inactive plus de `GATEWAY_SESSION_TIMEOUT` (1 h) était supprimée alors que le client restait connecté. Le message suivant passait par `respond()` → `open_session(sid)` **sans utilisateur** : nouvelle session sans propriétaire, donc `tool_policy(None)` = aucune restriction (un invité récupérait tous les outils, y compris `agent`, réservé, et `create_command`), plus de confirmation et plus d'historique. | ✅ corrigé |
| 2 | 🟠 | **`load_conversation` faisait confiance au client.** L'identifiant n'était pas validé (il devenait l'identifiant de la session et était écrit tel quel dans PocketBase). Sans historique serveur, les messages du client étaient injectés tels quels dans le contexte du LLM, y compris avec un rôle `system` ou `tool`. | ✅ corrigé |
| 3 | 🟠 | **Message transformé en option d'agent.** Un message qui commence par `-` devenait une option de la commande de l'agent (ex. `--dangerously-skip-permissions` pour Claude Code) dès que `AGENTS_PROMPT_PREFIX` était vide. Même risque pour l'identifiant de session renvoyé par l'agent. | ✅ corrigé |
| 4 | 🟠 | **Un agent qui ignore SIGTERM n'était jamais arrêté.** `_kill()` n'envoyait que SIGTERM : la lecture de la sortie restait bloquée, donc ni l'interruption ni `AGENTS_TIMEOUT` n'étaient tenus (thread bloqué, verrou de session pris). | ✅ corrigé (SIGKILL après `AGENTS_KILL_GRACE`) |
| 5 | 🟠 | **L'assistant pouvait élargir `ACTIONS_OPEN_ALLOWED_APPS`** via `[SET_SETTING]`. C'est une limite de sécurité au même titre que `FILES_SEARCH_DIRS`, qui était déjà bloqué. Une injection de consigne (nom de fichier, réponse d'agent) n'avait besoin que d'un « oui » distrait. | ✅ corrigé (bloqué par défaut) |
| 6 | 🟡 | **Confirmation dupliquée dans la passerelle** (chemins texte et voix copiés-collés), qui lisait en plus les mots de confirmation dans une copie des réglages prise à la connexion. | ✅ factorisé |
| 7 | 🟡 | **`HistoryStore.append` réessayait sans `tools` après n'importe quelle erreur** : double requête vers un PocketBase injoignable et erreurs de programmation masquées. | ✅ corrigé |
| 8 | 🟠 | **Liste des conversations tronquée** : `list_conversations()` ne lit que les 300 derniers messages. Les anciennes conversations disparaissent du tiroir et `message_count` est faux, alors que la doc promet « l'historique complet ». | ⏳ à faire |
| 9 | 🟠 | **Plusieurs appareils sur une même session** : la déconnexion de l'un met `confirm = None` pour tous (actions dangereuses refusées sur l'autre appareil jusqu'à sa reconnexion). | ⏳ à faire |
| 10 | 🟡 | **Sessions sans propriétaire = accès total.** `tool_policy(None)` et `agents_allowed(None)` renvoient « tout permis ». Le correctif n°1 ferme le chemin connu, mais le principe reste fragile : un oubli d'`user=` suffit à rouvrir la faille. | ⏳ à faire |
| 11 | 🟡 | **Fichiers trop gros** : `gateway/web/app.js` (3 176 lignes), `style.css` (2 881), `websocket_endpoint` (une fermeture de ~500 lignes), `AssistantCore.respond` (~170 lignes). | ⏳ à faire |
| 12 | 🟡 | **Outillage** : pas de CI, pas de `pytest` ni de linter dans le venv, `sys.path.insert` dans chaque module (pas de `pyproject.toml`), journalisation par `print` (pas de niveaux, pas de rotation). | ⏳ à faire |
| 13 | 🟡 | **Processus de travail** : 20 fichiers (+1 782 lignes) non commités sur `main` au moment de la revue. Une panne de disque ou un `git checkout .` effaçait des jours de travail. | à adopter |
| 14 | 🟡 | La question de confirmation est synthétisée et envoyée même si le client a coupé la voix. | ⏳ à faire |

## 3. Correctifs de cette branche

Un commit par sujet, chacun avec son test :

1. `f7bd585` **Sessions** : `Session.clients` (une session suivie par un client connecté n'expire plus) et
   `respond(user=)` (la passerelle donne le compte, une session disparue est recréée avec ses droits).
2. `load_conversation` : identifiant validé (`is_safe_id`), messages du client filtrés (`sanitize_messages`).
3. **Agents** : texte commençant par `-` décalé d'une espace, identifiant de session suspect ignoré, SIGTERM puis
   SIGKILL (`AGENTS_KILL_GRACE`, ajouté à `Settings`, `.env.example` et `.env`).
4. `ACTIONS_OPEN_ALLOWED_APPS` ajouté à `ACTIONS_SETTINGS_BLOCKED` (valeur par défaut, `.env.example`, `.env`).
5. Passerelle : `answer_confirmation()` réunit la résolution texte et voix et relit `core.settings`.
6. Historique : repli sans `tools` seulement sur un refus de PocketBase.

> ⚠️ `.env` n'est pas versionné : les deux réglages modifiés (`AGENTS_KILL_GRACE` ajouté,
> `ACTIONS_SETTINGS_BLOCKED` complété) ont aussi été écrits dans le `.env` local de cette machine.

## 4. Plan pour la suite (par priorité)

### Priorité 1 — Sécurité, refuser par défaut
- Remplacer « `user=None` = tout permis » par un utilisateur système explicite (`system_user()`), et faire que
  `tool_policy(None)` refuse tout. Points à mettre à jour : `respond()`, `mcp_server.py`, le bloc
  `__main__` de `assistant.py`, les tests qui ouvrent des sessions sans compte.
- Confirmation par client : garder une pile des gestionnaires `confirm` (un par client attaché) au lieu d'un
  seul champ, retirer seulement celui du client qui part (problème n°9).

### Priorité 2 — Justesse fonctionnelle
- `list_conversations` : paginer jusqu'au bout avec `fields=conversation,role,content,created,tools` pour
  alléger, ou ajouter une collection `conversations` (titre, dates, compteur) mise à jour à chaque échange.
  La seconde option est plus propre et rapide pour un gros historique.
- Ne synthétiser la question de confirmation que si le client a demandé la voix (`speak`).

### Priorité 3 — Maintenabilité
- `gateway/app.py` : sortir les gestionnaires de `websocket_endpoint` dans une classe `ClientConnection`
  (état : `user`, `session`, `pending`, `speeches`) avec une table `type → méthode` au lieu de la chaîne de `elif`.
- `AssistantCore.respond` : découper en étapes (`_transcribe`, `_handle_end_phrase`, `_handle_images`,
  `_run_llm`, `_post_process`), testables séparément.
- `app.js` : modules ES natifs (pas de build nécessaire) : `ws.js`, `chat.js`, `settings.js`, `auth.js`,
  `conversations.js`, `audio.js`.

### Priorité 4 — Outillage
- `pyproject.toml` (paquet installable, fin des `sys.path.insert`), `requirements-dev.txt` (`pytest`, `ruff`).
- GitHub Actions : `unittest` sur Ubuntu avec les dépendances audio lourdes installées sans matériel (les tests
  n'utilisent pas de micro), plus `ruff check`.
- Passer de `print` à `logging` (même format avec émojis, niveaux, fichier tournant dans `logs/`).
- Retirer `recordings/*.wav` du dépôt (608 Ko d'essais) ou les déplacer dans `tests/fixtures/` s'ils servent.

### Processus
- Travailler sur une branche par fonctionnalité et committer souvent ; `main` ne reçoit que des fusions.
