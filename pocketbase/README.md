# Comptes utilisateurs (PocketBase)

Facultatif : sans PocketBase (`AUTH_PROVIDER=none`), SmartHome fonctionne comme avant avec le seul jeton `GATEWAY_AUTH_TOKEN`.

PocketBase ne sert qu'à **identifier** les personnes qui utilisent la PWA. La PWA ne lui parle jamais :
la passerelle vérifie l'identifiant et le mot de passe, puis lie la session au compte (son rôle limite les outils
et l'accès aux paramètres, voir `AUTH_ROLE_TOOLS` et `AUTH_ADMIN_ROLES` dans `.env`).
Le micro de l'ordinateur n'identifie pas la voix : il utilise le compte fixe « Foyer » (`AUTH_LOCAL_ROLE`).

## Mise en place

Le plus simple : `./install.sh` (ou `install.ps1`) et répondre « Oui, un compte par personne » à la question des comptes.
Le script règle `.env` (`AUTH_PROVIDER=pocketbase`, passerelle active, jeton administrateur), télécharge
PocketBase `POCKETBASE_VERSION` (archive officielle, somme SHA-256 vérifiée) et propose de créer le compte administrateur.
Options sans question : `./install.sh --accounts` (`-Accounts` sous Windows).

À la main :

```bash
.venv/bin/python -m core.pocketbase install   # binaire dans pocketbase/
.venv/bin/python -m core.pocketbase admin     # compte administrateur de PocketBase
```

puis `AUTH_PROVIDER=pocketbase` dans `.env`.

## Fonctionnement

- **Lancement** : au démarrage de la passerelle (`main.py` avec `GATEWAY_ENABLED=true`, ou `python -m gateway`),
  si `POCKETBASE_URL` est locale et ne répond pas, SmartHome lance `pocketbase/pocketbase serve` et l'arrête en quittant
  (`POCKETBASE_AUTOSTART=false` pour le gérer vous-même). Un PocketBase déjà en marche est réutilisé.
  `./stop.sh` / `stop.ps1` arrêtent aussi un PocketBase resté orphelin.
- **Données** : `pocketbase/pb_data/` (non versionné, à sauvegarder). Journal : `pocketbase/pocketbase.log`.
- **Schéma** : `pb_migrations/` (versionné) est appliqué au lancement ; `--automigrate=false` empêche l'interface
  d'écrire de nouvelles migrations dans le projet. La migration ajoute le champ `role` (`admin`, `member`, `guest`)
  à la collection `users`, ferme l'inscription libre et interdit de changer son propre rôle ; une seconde ajoute
  `instructions` (consignes personnelles).
- **Profil** : chacun modifie son prénom et ses consignes dans la PWA (Réglages → Mon profil). Ils sont ajoutés au
  prompt système de ses conversations (`AUTH_USER_PROMPT`, `AUTH_USER_INSTRUCTIONS_PROMPT`) et ne changent que le ton :
  les outils permis restent ceux du rôle.
- **Voix** : chacun choisit aussi sa voix parmi les voix Piper de `voices/` (bouton « Écouter » pour l'essayer).
  Ajouter une voix = déposer son `.onnx` et son `.onnx.json` dans `voices/`. Avec `TTS_PROVIDER=ollama` ou
  `openrouter`, le choix n'est pas proposé. Champ `voice` ajouté par une troisième migration.
- **Historique** : les conversations de chaque compte sont conservées, sans limite de durée (projet local), dans la
  collection `messages` (quatrième migration). À la connexion, la PWA réaffiche la dernière conversation et l'assistant
  en retrouve le contexte, même après un redémarrage. Supprimer, relancer ou corriger un message est enregistré ;
  « Nouvelle conversation » en commence une autre (l'ancienne reste en base). Chacun ne voit que ses messages ;
  l'administrateur de PocketBase (`/_/`) les voit tous. Le jeton maître et le micro « Foyer » ne sont pas enregistrés.
  Indépendamment de PocketBase, tous les échanges (micro « Foyer » compris) et les notes des réponses sont gardés
  indéfiniment dans l'archive locale `data/archive.sqlite3` (voir `core/archive.py`) : une suppression dans la PWA
  ne fait que les masquer. Les conversations du micro s'affichent dans la PWA (lecture seule, rôles `ARCHIVE_HOUSEHOLD_ROLES`).
  Lire la dernière conversation d'un compte : `.venv/bin/python core/history.py`.
- **Comptes du foyer** : interface `http://127.0.0.1:8090/_/` (collection `users`, champ `role`), depuis la machine
  elle-même (sur un serveur sans écran : `ssh -L 8090:127.0.0.1:8090 serveur`).
- **État** : `.venv/bin/python -m core.pocketbase` ; vérifier un compte : `.venv/bin/python core/users.py`.

`GATEWAY_AUTH_TOKEN` reste obligatoire pour un accès depuis le réseau : il reste l'accès administrateur
(appairage par QR code, serveur MCP, `python -m gateway.client`). Sur une passerelle locale sans jeton,
tout client local est administrateur et les comptes ne sont pas demandés.
