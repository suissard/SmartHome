# 🤖 Guide d'Architecture & Directives pour Agents — SmartHome

Ce document est destiné aux agents IA (et aux développeurs) qui lisent, maintiennent, optimisent ou étendent le code du projet **SmartHome**.

---

## 🎯 1. Vision & Philosophie du Projet

**SmartHome** est un assistant vocal domotique conçu avec les principes suivants :
1. **100% Local & Souverain** : Aucune donnée audio ou textuelle ne doit transiter par des serveurs tiers ou le cloud.
2. **Faible Latence (Temps Réel)** : Le pipeline audio de bout en bout (Détection -> STT -> LLM -> TTS) est optimisé pour une réponse rapide et naturelle.
3. **Modularité Découplée** : Chaque étape du pipeline réside dans un module autonome, testable individuellement via son propre point d'entrée CLI.
4. **Continuité Conversationnelle** : Gestion d'une session de dialogue active (follow-up) pour éviter d'imposer à l'utilisateur de répéter le mot-clé à chaque échange.

---

## 📐 2. Cartographie Technique des Composants

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                         main.py                                                         │
│                                            (Orchestrateur & Machine à États)                                            │
└────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬────────┘
         │                   │                   │                   │                   │                   │
         ▼                   ▼                   ▼                   ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ audio/wakeword  │ │audio/transcribe │ │     llm/llm     │ │    audio/tts    │ │ audio/feedback  │ │  audio/ducking  │ │    actions/     │
│  (openWakeWord) │ │ (faster-whisper)│ │ (Ollama/Router) │ │   (Piper TTS)   │ │ (Sons & Signaux)│ │(PipeWire/Pulse) │ │ (Modules & OS)  │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘ └────────┬────────┘ └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │                   │                   │                   │                   │
         └───────────────────┴───────────────────┴─────────┬─────────┴───────────────────┴───────────────────┴───────────────────┘
                                                           ▼
                                           ┌───────────────────────────────┐
                                           │          core/config          │
                                           │   (Chargeur .env & Typage)    │
                                           └───────────────────────────────┘
```


### 2.1 [main.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/main.py) — Orchestrateur Principal
- **Responsabilité** : Satellite local : flux micro partagé (`PyAudio`), wake word, ducking, feedbacks et lecture de la voix. Le traitement (LLM, outils, actions) est délégué à `AssistantCore` (session persistante `"local"`, confirmation vocale). Démarre la passerelle en arrière-plan si `GATEWAY_ENABLED=true`, sur le même cœur. Affiche les fournisseurs actifs au démarrage.
- **Paramètres Clés** :
  - `FOLLOW_UP_TIMEOUT` (configurable via `.env`) : Durée (en secondes) pendant laquelle l'assistant reste en écoute active après une réponse. La barre d'écoulement s'adapte dynamiquement à cette durée.
- **Cycle de Fonctionnement** :
  1. Écoute passive par paquets (`CHUNK = 1280` à `RATE = 16000`).
  2. Si le mot-clé est validé (`score > threshold`), atténuation audio globale via `ducker.duck()`, notification `feedback.on_wakeword_detected()`, puis passage en mode `in_conversation = True`.
  3. Boucle de follow-up : appel de `transcriber.record_and_transcribe(...)`.
  4. Si du texte (ou de l'audio en mode direct) est reçu : `run_local_turn()` lance `core.respond("local", on_sentence=speech.say)` dans un thread ; chaque phrase est prononcée dès qu'elle est générée (`SpeechPipeline`) pendant que le thread principal continue de lire le micro (`mic_lock` partagé avec la confirmation vocale) pour détecter une interruption (`BargeInDetector`). Interruption → `core.cancel()` + `speech.interrupt()` + son `BARGE_IN_SOUND`, et écoute immédiate ; sinon signal de fin de tour `feedback.on_response_end()`.
  5. Si timeout de silence : notification de mise en veille `feedback.on_timeout()`, purge du flux, restauration du son système via `ducker.unduck()`, et retour en veille passive.
  6. **Micro du téléphone utilisé** ([core/remote_voice.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/remote_voice.py), `RemoteVoiceGuard`, `REMOTE_VOICE_SLEEP` / `REMOTE_VOICE_HOLD`) : l'ordinateur entend la même voix. La PWA envoie `{"type": "listening", "active"}` à l'ouverture / fermeture de son micro (événement `remote_listening`) ; un `transcript` d'une session distante compte aussi. Tant que la garde est active (micro distant ouvert, puis `REMOTE_VOICE_HOLD` s), le mot-clé est ignoré, l'écoute active est abandonnée (`record_and_transcribe(should_stop=)`) et une réponse locale en cours est coupée : retour direct en veille, sans son.
  7. **Fin de conversation demandée** (`reply.end_conversation`) : même retour en veille, sans attendre le timeout. Déclenchée par une phrase de `CONVERSATION_END_PHRASES` (énoncé entier, aux mots `CONVERSATION_END_FILLERS` près : traitée par `AssistantCore` sans appeler le LLM) ou par l'outil `sleep` / tag `[SLEEP]` ([actions/modules/sleep.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions/modules/sleep.py)) que le LLM choisit pour les formulations libres. L'événement `response` porte `end_conversation` (la PWA affiche « Conversation terminée »).

### 2.2 [actions/](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions) — Système Modulaire de Commandes & Actions OS
- **Responsabilité** : Détection des tags d'actions insérés par le LLM (`[SHUTDOWN]`, `[REBOOT]`, `[LOCK]`, `[VOLUME]`, `[MUTE]`, `[OPEN]`, etc.), exécution asynchrone non-bloquante et purification du texte transmis à la synthèse vocale.
- **Architecture Multi-Plateforme (Linux & Windows)** :
  - `actions/base.py` : Classe de base abstraite `BaseAction` encapsulant métadonnées, script bash embarqué (`script_code`), script PowerShell (`script_code_windows`), exécution bash (`Linux`) ou PowerShell / API Win32 (`Windows`), avec logging détaillé des sorties et codes retours.
  - `actions/modules/*.py` : Modules d'actions 100% autonomes (`volume.py`, `media.py`, `notify.py`, `open_app.py`, `lock.py`, `screen_off.py`, `shutdown.py`, `reboot.py`, `sleep.py`, `brightness.py`, `screenshot.py`, `timer.py`, `system_info.py`, `close_app.py`, `audio_output.py`, `create_command.py`, `assistant_settings.py`, `agent.py`, `files.py`).
    - *Windows* : Luminosité gérée par CIM/WMI (`WmiMonitorBrightnessMethods`), volume et médias via `ctypes.windll.user32.keybd_event` (touches multimédia virtuelles), extinction de l'écran via `SendMessageW(SC_MONITORPOWER)`, verrouillage via `LockWorkStation()`, extinction et redémarrage via `shutdown.exe`, notifications via PowerShell Toast/Balloon encodé en Base64 UTF-16LE.
  - `actions/registry.py` : Chargeur dynamique avec auto-découverte des définitions sans couplage.
  - `actions/manager.py` : Moteur d'extraction regex générique et d'exécution asynchrone déléguée sans logique en dur (mode tags, repli des modèles sans function calling).
- **Création de commandes par IA** ([actions/modules/create_command.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions/modules/create_command.py), outil `create_command`, `danger="confirm"`) : réservée aux superadmins (`AUTH_SUPERADMIN_TOOLS`, retiré par `tool_policy()` de tout autre compte, jeton maître et micro compris ; refusé par `execute_action` du serveur MCP). Envoie la consigne + le guide [actions/CUSTOM_COMMAND_GUIDE.md](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions/CUSTOM_COMMAND_GUIDE.md) à l'agent `ACTIONS_AGENT_COMMAND` (`agy --dangerously-skip-permissions --model ACTIONS_AGENT_MODEL --add-dir <dir> --print-timeout … -p <consigne>`, lancé dans `ACTIONS_AGENT_DIR`, vide = projet), en arrière-plan, journal dans `ACTIONS_AGENT_LOG_DIR`, notification à la fin. La commande créée est chargée au redémarrage. Toute évolution du format des actions doit être reportée dans ce guide.
- **Paramètres de l'assistant par lui-même** ([actions/modules/assistant_settings.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions/modules/assistant_settings.py)) : `get_settings` (lecture, filtre facultatif) et `set_setting` (`NOM=valeur` ou JSON `{"NOM": valeur}`) sur les champs `EDITABLE` de `settings_store`, moins `ACTIONS_SETTINGS_BLOCKED` (clé API, `ACTIONS_CONFIRM_DANGEROUS`, `FILES_SEARCH_DIRS`, `ACTIONS_OPEN_ALLOWED_APPS` : l'assistant n'élargit jamais lui-même ses limites). Réservés aux rôles `AUTH_ADMIN_ROLES` (`AUTH_ADMIN_TOOLS`, retirés par `tool_policy()` des autres comptes). `set_setting` a `force_confirm=True` : confirmation toujours demandée, même si `ACTIONS_CONFIRM_DANGEROUS=false`, avec une question construite par `confirm_text()` (« changer « libellé » de « ancien » à « nouveau » ») ; une valeur invalide ou déjà en place est refusée avant toute question. L'écriture passe par `AssistantCore.update_settings()` (installé via `settings_store.set_owner()`, car le registre d'actions recharge ses modules), puis émet `settings_changed` ; sans cœur actif (serveur MCP), refus.
- **Exposition au LLM** : chaque action devient aussi un outil de function calling (`tool_name`, schéma `parameters`) et déclare `danger` (`"safe"` ou `"confirm"` pour SHUTDOWN / REBOOT).
- **Confirmation WebSocket Gateway** : Lorsqu'une action nécessite une confirmation (`danger="confirm"`), la Gateway émet un message `confirm_request` et attend une réponse. Si l'utilisateur répond par la parole ou un message texte ("oui", "confirme", "non", etc.), `gateway/app.py` intercepte et résout immédiatement la confirmation en attente sans bloquer le verrou de session ni lancer un nouveau tour LLM concurrent.

### 2.2 quater [core/images.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/images.py) & [actions/modules/files.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions/modules/files.py) — Images & Recherche de Fichiers
- **Images envoyées** (PWA : trombone, coller, glisser-déposer ; le navigateur réduit l'image à `IMAGES_MAX_SIDE` px en JPEG) : champ `images` des messages WS `text` / `audio` et de `POST /api/ask` (`[{data: base64 | data URL, name?}]`). `decode_uploads()` vérifie le nombre (`IMAGES_MAX_PER_MESSAGE`), la taille (`IMAGES_MAX_BYTES`) et le **format réel** (signature des octets : PNG, JPEG, GIF, WebP, BMP ; le type annoncé est ignoré). `AssistantCore.respond(images=)` : modèle avec vision → images jointes au dernier tour (`LLMProvider.chat(images=)` : champ `images` d'Ollama, `image_url` en data URL pour OpenRouter), l'historique ne garde que leur mention ; **sans vision** (`accepts_images()` : capacité `vision` d'Ollama, modalité `image` d'OpenRouter, `LLM_IMAGE_INPUT=on|off` force, jamais pour un modèle de décision) → événement `warning` (`IMAGES_NO_VISION_MESSAGE`, `${MODEL}`) et seul le texte est traité ; image seule → l'alerte est la réponse, sans appel au LLM. La PWA prévient dès qu'une image est jointe (`llm.vision` de `ready` / `model_info()`). Agent externe relié : les images sont copiées dans `IMAGES_UPLOAD_DIR` et l'agent reçoit leur chemin.
- **Images montrées** : outils `search_files` (tag `[SEARCH_FILES motif]` : tous les mots du chemin, accents et casse ignorés, ou motif `*.png` ; plus récents d'abord, `FILES_SEARCH_MAX_RESULTS`) et `show_image` (`[SHOW_IMAGE chemin]`), limités aux dossiers `FILES_SEARCH_DIRS` (profondeur `FILES_SEARCH_MAX_DEPTH`, fichiers cachés ignorés ; `resolve_allowed()` refuse `..` et les liens symboliques qui sortent). Après `show_image`, `AssistantCore._show_image()` relit l'image et émet l'événement `image` (`{name, mime, data, path}`, aussi dans `Reply.images`) : bulle image dans la PWA, clic = visionneuse. `FILES_SEARCH_DIRS` est dans `ACTIONS_SETTINGS_BLOCKED` : l'assistant ne peut pas élargir lui-même ce qu'il lit. Les images ne sont pas conservées dans l'historique (PocketBase, appareil) : seule la pastille d'outil ou la mention reste.

### 2.2 ter [core/agents.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/agents.py) — Agents Externes (Hermes, Claude Code, Antigravity)
- **But** : « j'aimerais parler à Hermes » relie la conversation (micro local ou PWA) à un agent IA installé sur la machine, qui répond directement à travers SmartHome (texte en streaming, voix alternative), jusqu'au retour à l'assistant.
- **Fiches** : `agents.json` (`AGENTS_CONFIG_FILE`, relu dès qu'il change) : `command` (liste d'arguments, `{prompt}`, jamais de shell), `resume_args` (`{session}` : identifiant renvoyé par l'agent, conservé par `Session.agent_sessions` pour garder le fil), `output` (`text`, `hermes`, `claude`, `antigravity` : lecteurs `OUTPUT_PARSERS` du JSON en flux), `color`, `voice`, `aliases`, `cwd`, `timeout`. `AgentRunner` lit la sortie ligne par ligne, tue le groupe de processus sur interruption (`session.cancel`) ou délai (`AGENTS_TIMEOUT`). La commande est cherchée dans le `PATH` complété par `AGENTS_EXTRA_PATH` (`search_path()` : un service systemd n'a pas `~/.local/bin`, où s'installent `agy` et `claude`), aussi pour `create_command`. **Repli** : un agent non installé n'est ni proposé (menu PWA, outil `agent`) ni relié (`set_agent` lève `ValueError`) ; un agent qui échoue (`AgentError`) rend la conversation à l'assistant (`AGENTS_ERROR_MESSAGE`). `AGENTS_PROMPT_PREFIX` précède chaque message (réponse lue à voix haute).
- **Bascule** : `detect_switch()` (formules `AGENTS_SWITCH_TRIGGERS` + nom/alias, dans les premiers mots, accents ignorés) sans LLM ; l'outil `agent` / tag `[AGENT nom]` ([actions/modules/agent.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/actions/modules/agent.py)) pour les formulations libres. Une demande qui dit autre chose que la mise en relation (« passe-moi Claude, quelle heure est-il ? ») est transmise entière à l'agent. Retour : `AGENTS_RETURN_PHRASES`, « parler à » un nom de `AGENTS_ASSISTANT_NAMES`, fin de conversation / veille (`AGENTS_LEAVE_ON_SLEEP`), nouvelle conversation, ou la pastille de la PWA.
- **Routage** (`AssistantCore._route_to_agent`) : tant que `Session.agent` est défini, le LLM n'est pas appelé ; un enregistrement est toujours transcrit (même en STT direct). Les échanges avec l'agent ne vont pas dans l'historique du LLM ni dans PocketBase. Événements : `agent_changed` (`{agent: {name, label, color, voice} | null}`), `response.agent`.
- **Voix** : `session_voice()` renvoie la voix de l'agent (fiche, `AGENTS_DEFAULT_VOICE`, sinon une autre voix installée que celle de l'assistant) ; `SpeechPipeline(voice=callable)` résout la voix à chaque phrase demandée, l'annonce `AGENTS_SWITCH_MESSAGE` est donc dite par l'agent. Le texte prononcé passe par `strip_markdown()` (`core/sentences.py`).
- **Droits** : `AGENTS_ROLES` (superadmins toujours) ; l'outil `agent` est retiré des autres comptes par `tool_policy()`.
- **PWA** : la pastille du modèle devient celle de l'agent (couleur, nom, transition flou/reflet/largeur) ; un clic ouvre le menu des interlocuteurs (`{"type": "set_agent", "agent": nom | null}`) ; bulles et séparateurs aux couleurs de l'agent.

### 2.2 quinquies [core/archive.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/archive.py) — Archive des Conversations & Notes
- **But** : données d'entraînement conservées **indéfiniment**, base SQLite locale `ARCHIVE_DB_PATH` (`data/`, non versionné, bibliothèque standard), `ARCHIVE_ENABLED`. `AssistantCore._archive_exchange()` y ajoute tout échange terminé, quelle que soit l'origine (`source` : `local` = micro de l'ordinateur, `pwa` = passerelle, `api` = sans utilisateur), avec compte, session et modèle. Les échanges avec un agent externe n'y vont pas (comme l'historique).
- **Jamais effacée** : supprimer un message / une conversation dans la PWA la masque (`deleted_at`) ; corriger une réponse ajoute une version (`model = "edit"`), l'ancienne est marquée `superseded_by`. L'historique PocketBase, lui, est toujours réellement modifié (vue de l'utilisateur).
- **Conversations du micro dans la PWA** : la voix n'étant pas identifiée, elles appartiennent au foyer, visibles par les rôles `ARCHIVE_HOUSEHOLD_ROLES` (superadmins toujours) via `AssistantCore.sees_household()`. `list_conversations()` les ajoute (`"source": "local"`, pastille « Micro », pas de suppression) ; `load_conversation` avec `"source": "local"` → `household_conversation()` : **lecture seule**, la session ne change pas (écrire ou parler en commence une nouvelle). `main.py` appelle `new_local_conversation()` à chaque retour en veille (un réveil = une conversation ; le contexte du LLM est gardé). Chaque échange au micro émet `history_updated` (relayé aux PWA autorisées : liste et conversation affichée rafraîchies). Sans PocketBase, les conversations du jeton maître sont aussi relues depuis l'archive.
- **Notes des réponses** (`FEEDBACK_ENABLED`) : pouce sous chaque réponse de la PWA → échelle -2…+2 (enregistrée dès le clic) → commentaire facultatif (`FEEDBACK_COMMENT_MAX_CHARS`). Message WS `feedback` → `AssistantCore.set_feedback()` : on ne note que ce qu'on peut lire (sa conversation, ou celles du micro si visibles) ; un échange antérieur à l'archive est copié depuis PocketBase. Une note par personne et par réponse (la nouvelle remplace l'ancienne), renvoyée avec les messages (`feedback: {rating, comment}`).
- **Export** : `python core/archive.py export fichier.jsonl [--visible]` (une ligne par conversation, versions masquées/corrigées comprises sauf `--visible`, notes jointes aux réponses).

### 2.2 bis [core/tools.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/tools.py) & [audio/confirm.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/confirm.py) — Registre d'Outils Unifié & Confirmation
- **Registre** : `build_tool_registry()` réunit les actions locales et les outils des serveurs MCP connectés (schéma JSON, danger, exécuteur). Le propre serveur MCP de SmartHome est ignoré (doublons), ainsi que tout serveur marqué `"expose_to_llm": false` dans `mcp_servers.json`.
- **Danger des outils MCP** : `"tool_danger": "safe" | "confirm"` dans la config du serveur, sinon déduit des annotations MCP (`read_only_hint` / `destructive_hint` ; sans annotation → `confirm`, conformément à la spécification).
- **Politique de confirmation unique** : `request_confirmation()` est appelée pour tout outil ou tag `confirm`. `main.py` installe `VoiceConfirmer` (question TTS, écoute, mots `ACTIONS_CONFIRM_WORDS` / `ACTIONS_CANCEL_WORDS`, ou classification par le LLM en mode STT direct). Sans gestionnaire installé (serveur MCP), l'action est refusée.

### 2.3 [audio/wakeword.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/wakeword.py) — Détection de Mot-Clé
- **Technologie** : `openwakeword` avec moteur d'inférence ONNX Runtime.
- **Format Audio requis** : `RATE = 16000` Hz, 1 canal (mono), `FORMAT = paInt16`, `CHUNK = 1280` échantillons (80 ms par trame).
- **Fonctionnement** :
  - `process_chunk(audio_chunk)` injecte la trame dans le buffer prédictif d'OpenWakeWord.
  - Si le score dépasse `threshold` (par défaut `0.5`), le buffer interne est purgé via `self.oww.reset()` pour éviter les détections fantômes consécutives.
- **Écoute coupée** (`WAKEWORD_ENABLED=false`, réglage `LIVE`) : `main.py` lit toujours le flux micro mais ne l'analyse plus (relu à chaque trame dans `core.settings`). La PWA l'affiche en tête des réglages (carte `wakeword-card`, interrupteur réservé aux admins via `update_settings`) et par la pastille « Mot-clé coupé » de la barre du haut. `AssistantCore.local_microphone` (posé par `main.py`) dit si un micro local existe ; état transmis dans `ready.wakeword`, `profile_saved` et `settings_changed` (`{enabled, available}`).

### 2.4 [audio/transcribe.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/transcribe.py) & [audio/stt.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/stt.py) — Enregistrement & STT
- **Technologie** : `transcribe.py` gère uniquement l'enregistrement micro et la VAD ; la transcription est déléguée au fournisseur `STTProvider` choisi par `STT_PROVIDER` dans le registre `STT_PROVIDERS` de `stt.py` (`whisper` via `faster-whisper`, `ollama` via `/v1/audio/transcriptions` d'Ollama avec `OLLAMA_STT_MODEL` (ex: lfm3-audio, capacité `audio` vérifiée au chargement), `openrouter` via `/audio/transcriptions`, ou `direct` — alias `none`/`bypass` — pour le bypass STT vers LLM multimodal). En mode direct, le choix se fait **à chaque demande** selon le modèle actif (`AssistantCore.audio_to_llm()`) : un modèle qui comprend l'audio reçoit l'enregistrement, sinon `STT_FALLBACK_PROVIDER` (`create_fallback_stt()`) transcrit.
- **Gestion VAD & Audio** :
  - `pre_buffer` (`deque(maxlen=4)`) : Conserve les 4 dernières trames (320 ms) pour ne jamais couper l'attaque de la voix.
  - **VAD** ([audio/vad.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/vad.py), `SpeechDetector`) : `VAD_ENGINE=silero` (réseau Silero fourni par openWakeWord, local, ~0,3 ms/trame). Début de parole = niveau > `VOICE_THRESHOLD` **et** probabilité de voix ≥ `VAD_SPEECH_THRESHOLD` ; la fin de phrase suit la probabilité de voix (hystérésis), si bien qu'un bruit continu (ventilateur, musique) ne prolonge plus l'enregistrement jusqu'à `MAX_SPEECH_DURATION`. `VAD_ENGINE=energy` = ancien seuil de niveau seul.
  - Un enregistrement contenant moins de `VAD_MIN_SPEECH_DURATION` de parole n'est pas transcrit. Durées mesurées en temps audio (trames lues).
  - `silence_duration = 0.8s` : Seuil de silence consécutif marquant la fin naturelle d'une phrase.
  - **Anti-hallucinations** : `WHISPER_VAD_FILTER` (VAD intégrée à faster-whisper) et `STT_IGNORED_PHRASES` (« Sous-titres réalisés par… », transcriptions sans mot) appliqués par `STTProvider._discard_hallucination()`.
  - `_flush_stream()` : Purge le buffer résiduel de la carte son avant chaque écoute pour éliminer les bruits résiduels ou l'écho de la synthèse précédente.
- **Conversion & Transcription** : Assemblage des trames dans un buffer WAV en mémoire (`io.BytesIO`). Si `STT_PROVIDER=none` ou `direct`, retourne directement les octets WAV sans charger ni appeler de moteur STT. Sinon, effectue la transcription via Whisper local ou OpenRouter.

### 2.5 [llm/llm.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/llm/llm.py) & [llm/providers.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/llm/providers.py) — Raisonnement & Génération
- **Technologie** : `providers.py` définit l'interface `LLMProvider.chat(messages, ...)` et ses implémentations (`ollama` en local, `openrouter` via l'API OpenAI compatible), sélectionnées par `LLM_PROVIDER`. `llm.py` contient la classe `Conversation` (historique, prompt système, streaming console) et les fonctions de compatibilité (`ask_llm`, `get_history`...).
- **Appel d'Outils** (`LLM_TOOL_CALLING`) : `native` (function calling, boucle outil → résultat → LLM jusqu'à `LLM_MAX_TOOL_ROUNDS`), `tags` (`[VOLUME 40]` dans le texte), ou `auto` (natif, repli définitif sur les tags si le modèle lève `ToolsNotSupportedError`). Chaque fournisseur formate ses messages d'outils (`assistant_message`, `tool_message`).
- **Historique Conversationnel** : Maintient un buffer glissant des $N$ derniers messages (`LLM_HISTORY_MESSAGES`, par défaut 5) pour préserver le contexte des échanges récents. Fournit `get_history()`, `clear_history()`, et `add_history_message()`.
- **Support Multimodal Audio Direct** : Fonction `ask_llm(prompt=..., audio_bytes=...)` capable d'envoyer l'audio aux modèles multimodaux (OpenRouter : `input_audio` base64, ex: Gemini Flash, Voxtral ; Ollama : champ `images` du message, ex: gemma4, lfm3-audio). Capacité **par modèle** : `LLMProvider.accepts_audio(model)` lit la capacité `audio` de `/api/show` (Ollama) ou les `input_modalities` du catalogue `/models` (OpenRouter ; modèle absent du catalogue = accepté), résultat mis en cache ; `LLM_AUDIO_INPUT=on|off` force la réponse. Images : `accepts_images(model)` et `chat(images=)` sur le même principe (voir 2.2 quater).
- **Prompt Système Dynamique** : Reçoit automatiquement les définitions de commandes d'`ActionManager` pour permettre au LLM d'agir sur le système.
- **Streaming** : Supporte le streaming console immédiat pour un retour visuel en temps réel pendant la génération quel que soit le fournisseur actif.
- **Modèles de Décision** ([llm/decision.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/llm/decision.py)) : un modèle listé dans `LLM_DECISION_MODELS` (ex: `nimble`, endpoint Ollama `/v1/systemone`, `LLMProvider.decide()`) ne rédige pas : `Conversation.ask()` délègue à `run_decision()`, qui pose une question fermée « quelle commande ? » (outils + « aucune », seuil `LLM_DECISION_MIN_CONFIDENCE`), puis une question par argument (choix `BaseAction.decision_choices()`, `enum`, booléen, petite échelle d'entiers ; un outil à argument requis libre n'est pas proposé), exécute l'outil (confirmation comprise) et renvoie une phrase de confirmation : `LLM_DECISION_MESSAGES[outil]` (JSON dans `.env`), sinon `BaseAction.done_message`, sinon la réponse type (`LLM_DECISION_DONE_TEMPLATE`, `_NO_ARGS_TEMPLATE`, `REFUSED_TEMPLATE`, `UNKNOWN_TEXT`). Gabarits `string.Template` : `${COMMAND}`, `${ARGS}`, `${OUTPUT}`, `${TOOL}`, `${<ARGUMENT>}` (le `.env` est lu sans interpolation de variables). `LLMProvider.list_models()` liste les modèles et leurs capacités pour l'interface web.

### 2.6 [audio/tts.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/tts.py) — Synthèse Vocale
- **Technologie** : Fournisseurs `TTSProvider` (`piper` via ONNX neural local, `ollama` via `/v1/audio/speech` d'Ollama avec `OLLAMA_TTS_MODEL` / `OLLAMA_TTS_VOICE` — ex: lfm3-audio, `female-french`, WAV 24 kHz à en-tête « en flux » décodé par `decode_wav()`, vitesse 1 seulement — ou `openrouter` via `/audio/speech`) sélectionnés par `TTS_PROVIDER`. Les fournisseurs audio Ollama refusent au chargement un modèle sans la capacité requise (`check_ollama_capability()` de `core/providers.py`). La façade `TextToSpeech` sépare `synthesize()` (audio post-traité, sans lecture — utilisable pour un client distant) de `speak()` (synthèse + lecture locale).
- **Post-Traitement Audio Anti-Pops & Fluidité** :
  1. *Ponctuation forcée* : Ajout automatique d'un point final si manquant pour garantir une intonation descendante naturelle.
  2. *Fade-Out (50 ms)* : Atténuation linéaire en fin de signal pour supprimer les clics numériques de fin de flux.
  3. *Padding de silence* : Insertion de 100 ms de silence en début de buffer et 400 ms en fin de buffer.
  4. *Lecture synchrone* : Exécution via `sounddevice` (`sd.play` + `sd.wait`).
- **Voix par compte** : `synthesize(text, voice=)` ; Piper liste les voix de `voices/` (`list_piper_voices()`, modèle `.onnx` + `.onnx.json`, identifiant = nom du fichier, jamais un chemin), garde toujours la voix configurée et au plus `TTS_VOICE_CACHE_SIZE` autres voix (LRU). OpenRouter et Ollama ne proposent pas de choix (`voices()` vide : le sélecteur de la PWA est masqué).

### 2.6 bis [audio/speech.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/speech.py), [core/sentences.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/sentences.py) & [audio/barge_in.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/barge_in.py) — Parole en Streaming & Barge-in
- **Découpage** : `SentenceSplitter` valide une fin de phrase seulement quand le caractère suivant est connu (« 40.5 » jamais coupé), regroupe les morceaux trop courts (`TTS_STREAM_MIN_CHARS`) et retire les tags d'actions.
- **SpeechPipeline** : deux threads (synthèse de la phrase suivante pendant la lecture de la précédente), `interrupt()` vide la file et coupe le son, `close()` arrête les threads. Le « sink » joue localement ou envoie l'audio à un client (passerelle : événements `audio_chunk`).
- **Annulation** : chaque session a un `cancel` (`core.cancel(session)`) vérifié à chaque fragment généré ; `ResponseInterrupted` interrompt la génération sans rien garder dans l'historique (événement `interrupted`).
- **Barge-in** (`BARGE_IN_MODE`) : `wakeword` (redire le mot-clé, robuste à l'écho), `voice` (voix forte continue, avec casque ou annulation d'écho), `off`. Côté PWA, le bouton principal parle (ou envoie dès qu'un texte est saisi) ; le bouton `voice-stop`, visible seulement pendant la voix, sert d'indicateur et la coupe. Ce bouton, le micro ou l'envoi d'un message pendant une réponse coupent la voix et envoient `{"type": "stop"}`.

### 2.7 [audio/feedback.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/feedback.py) — Sons & Signaux Vocaux de Cycle de Vie
- **Technologie** : Synthèse harmonique procédurale (`numpy` + `sounddevice`) & lecteur WAV.
- **Rôle** : Gère les retours sonores (bips, carillons, accords ascendants/descendants, ding) et vocaux (phrases TTS) pour la détection du wake word, la fin de parole de l'IA et le timeout d'écoute active.

### 2.8 [audio/ducking.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/ducking.py) — Atténuation Audio Système (Ducking)
- **Technologie** : `pactl` JSON (compatible PipeWire & PulseAudio).
- **Rôle** : Réduit le volume de toutes les applications tierces (musique, vidéos, jeux, etc.) à un niveau paramétrable (ex: 20%) dès que l'assistant écoute ou parle, et rétablit les volumes initiaux à la mise en veille. Filtre le PID de l'assistant pour ne pas altérer la voix de sortie.

### 2.8 bis [audio/media_pause.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/audio/media_pause.py) — Pause des Médias
- **Technologie** : `playerctl` (MPRIS). `MEDIA_PAUSE_ENABLED` (réglable dans l'interface web, au redémarrage).
- **Rôle** : au mot-clé, `MediaPauser.pause()` met en pause les seuls lecteurs en état `Playing` et les mémorise ; à la mise en veille, `resume()` relance ceux-là seulement (un média déjà en pause n'est jamais relancé).

### 2.9 [core/config.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/config.py) & [core/providers.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/providers.py) — Configuration & Registre de Fournisseurs
- **Technologie** : modèle `pydantic` `Settings` (validé au démarrage, erreurs lisibles) + `python-dotenv`. Priorité : profil / réglages utilisateur (`.env`, surcharges locales) > variables de la machine (`os.environ`) > valeurs par défaut. Le nouveau code reçoit `get_settings()` par injection ; les constantes de module restent exportées pour compatibilité.
- **Registre** : `ProviderRegistry` associe un nom (et ses alias) à une classe instanciée avec `Settings`. Chaque fournisseur expose `describe(settings)` (résumé sans instanciation), utilisé par `main.py` et le serveur MCP.
- **Rôle** : Charge `.env` avec conversion de types stricte (`int`, `float`, `bool`, `str`, `Optional`) et fallbacks par défaut pour toutes les constantes du projet (providers LLM/STT/TTS, OpenRouter, audio, wake word, whisper, ollama, piper, feedbacks, ducking, actions, serveur MCP).

### 2.9 ter-a [core/profiles.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/profiles.py) — Profils de Configuration
- `profiles/<nom>.env` (`hybrid` par défaut, `mix`, `local-gemma`, `local-lfm`, `local-decision`, `cloud`) ne contient que les réglages d'architecture (fournisseurs, modèles). Priorité : profil / réglages utilisateur > variables de la machine (`os.environ`) > défauts ; le profil ne s'applique qu'au vrai `.env` (pas aux fichiers passés à `load_settings` dans les tests).
- Choix : `--profile <nom>` (retiré de `sys.argv` avant l'import de `core.config`), `SMARTHOME_PROFILE`, ou menu aux flèches de `start.sh` (`choose_profile()`, affiché sur stderr car stdout est capturé ; `--no-menu` le passe). Sans choix : dernier profil du menu (`profiles/.last`, non versionné), sinon `hybrid`.
- **Assistant** ([core/wizard.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/wizard.py), `./start.sh --setup` ou entrée du menu) : une méthode `step_*` par question, sur les menus de [core/menu.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/menu.py) (`GoBack` = question précédente). Il ne propose que ce qui est disponible (capacités Ollama, clé OpenRouter), crée `profiles/perso.env` (non versionné) et n'écrit la clé que dans `.env`. Un nouveau profil = un nouveau fichier ; la première ligne `# Titre : description` sert au menu.
- Un champ défini par le profil et modifié depuis l'interface est écrit dans `profiles/<nom>.local.env` (`settings_store.save_changes`, non versionné, relu par `profile_values()`), les autres dans `.env`.
- Quand `MEDIA_PAUSE_ENABLED` (défaut `true`) est actif, `main.py` désactive le ducking : la pause suffit.
- **Assistant d'installation** ([core/install_wizard.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/install_wizard.py), lancé par `install.sh` / `install.ps1` dans un terminal interactif, sauf `-y` / `--no-menu`) : tourne avec le Python du système, **avant le venv** → bibliothèque standard uniquement (`core/menu.py` chargé par son chemin, `.env` et profils lus sans python-dotenv). Questions : machine (poste / serveur), profil (enregistré dans `profiles/.last`), Ollama (installer / déjà là / distant → `OLLAMA_HOST` / non, selon les besoins du profil calculés par `profile_needs()`), modèle Ollama si profil choisi plus tard, paquets système (tout / base / rien), modèles, adresse d'écoute (serveur), comptes utilisateurs (`ACCOUNTS`, PocketBase), démarrage automatique. Il écrit un plan `CLÉ=valeur` sur stdout (codes : 0 validé, 1 annulé, 130 interrompu), lu par le script d'installation ; les options `--no-*` retirent la question correspondante.

### 2.9 bis [core/assistant.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/assistant.py) & [core/events.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/events.py) — Cœur de Service & Bus d'Événements
- **AssistantCore** : indépendant des entrées/sorties. Partage un fournisseur LLM, un STT, un TTS et un registre d'outils entre des **sessions** (conversation, historique, gestionnaire de confirmation et verrou propres ; expiration après `GATEWAY_SESSION_TIMEOUT`, sauf sessions persistantes). `respond(session, text|audio_wav, synthesize)` exécute le pipeline complet (bloquant, à appeler via `asyncio.to_thread` côté serveur) et renvoie un `Reply`.
- **EventBus** : publie `transcript`, `token`, `tool`, `confirm_request`, `response`, `error`, `settings_changed` (abonnement global ou par session, thread-safe). La console de `main.py` et chaque client WebSocket sont des abonnés.
- **Paramètres à chaud** ([core/settings_store.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/settings_store.py)) : `EDITABLE_GROUPS` liste les champs modifiables depuis l'interface (dont la clé API `OPENROUTER_API_KEY` saisie de façon masquée), avec leur prise d'effet (immédiate ou au redémarrage) ; l'aide affichée vient des commentaires de `.env.example`. `VISIBLE_WHEN` décrit quand un champ est utile (alternatives `{variable: valeurs}`, `LLM_MODE` calculé par `app.js`) : l'interface masque les autres. `AssistantCore.update_settings()` valide, réécrit les lignes concernées de `.env` ou de la surcharge du profil (commentaires conservés), remplace la configuration courante (`config.set_settings`) et met à jour toutes les sessions (historique conservé). Les constantes de module de `config.py` gardent leur valeur de démarrage : un champ lu par `main.py`, le micro ou la voix doit être marqué `RESTART`.

### 2.9 ter [gateway/](file:///home/suissard/PROGRAMMATIONS/SmartHome/gateway) — Passerelle Réseau (LAN / Tailscale)
- **Technologie** : Starlette + uvicorn. `GET /health`, `POST /api/ask` (sans confirmation possible : actions dangereuses refusées), `WS /ws` (protocole JSON décrit en tête de `gateway/app.py` : streaming, outils, confirmations aller-retour, gestion multi-conversations, voix WAV en base64).
- **Sécurité** (`core/security.py`, partagé avec le serveur MCP) : jeton `GATEWAY_AUTH_TOKEN` (en-tête Bearer, ou premier message `auth` pour les navigateurs), refus de démarrer hors loopback sans jeton.
- **Comptes utilisateurs** ([core/users.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/users.py), facultatif) : `AUTH_PROVIDER` choisit l'annuaire dans `USER_DIRECTORIES` (`none` = jeton unique ; `pocketbase` = API REST de PocketBase, bibliothèque standard, voir [pocketbase/README.md](file:///home/suissard/PROGRAMMATIONS/SmartHome/pocketbase/README.md)). [core/pocketbase.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/pocketbase.py) télécharge `POCKETBASE_VERSION` (SHA-256 vérifié, `install`), crée l'administrateur (`admin`) et, via `ensure_running()` appelé par `main.py` (passerelle active) et `python -m gateway`, lance le binaire du projet si `POCKETBASE_URL` est locale et muette (`--automigrate=false`, migrations de `pocketbase/pb_migrations`), puis l'arrête en quittant ; `stop.sh` / `stop.ps1` arrêtent un PocketBase orphelin. La PWA ne parle jamais à PocketBase : le message `auth` porte `identity` + `password` (connexion explicite, prioritaire), le jeton maître `token` (→ `admin_user()`), ou `user_token` (jeton de compte renouvelé, renvoyé dans `ready.user.token`). Chaque session a un propriétaire (`Session.user`) : `open_session(..., user=)` ne reprend jamais la session d'un autre compte (ni la session `local`, sans propriétaire). Le rôle donne une `ToolPolicy` (`AUTH_ROLE_TOOLS` : noms, `*`, `safe`, `-nom`) appliquée à la vue d'outils de la conversation (`ToolRegistry.restricted()`) et au mode tags (`ActionManager`, prompt et exécution) ; paramètres, liste des modèles et redémarrage sont réservés à `AUTH_ADMIN_ROLES` (`settings_error` sinon, boutons `.admin-only` masqués côté PWA). Le micro local utilise `local_user()` (« Foyer », `AUTH_LOCAL_ROLE`) : la voix n'est pas identifiée. **Profil** : un compte de l'annuaire (`User.has_profile`) a un prénom et des consignes (`instructions`, champ PocketBase, `AUTH_INSTRUCTIONS_MAX_CHARS`) ; `user_prompt()` (gabarits `AUTH_USER_PROMPT`, `AUTH_USER_INSTRUCTIONS_PROMPT`) les ajoute au prompt système de ses sessions (`Conversation.user_prompt`). **Noms** : l'assistant s'appelle `ASSISTANT_NAME` (réglage `LIVE`, aussi reconnu par `detect_switch()` pour revenir à l'assistant), ou le nom choisi par le compte (champ PocketBase `assistant_name`, `assistant_name()`) ; `user_prompt()` ajoute toujours `ASSISTANT_NAME_PROMPT` (`${ASSISTANT_NAME}`), même sans profil. La PWA affiche le nom de l'auteur au-dessus de chaque bulle (`data-author` : prénom du compte, nom de l'assistant de `ready.assistant`). Message WS `update_profile` (`assistant_name` facultatif) → `directory.update_profile()` avec le jeton du compte (la règle PocketBase interdit de toucher à son rôle) → `AssistantCore.set_session_user()` → `profile_saved`. Les consignes ne changent que le style : les droits restent ceux du rôle. **Voix** : champ `voice` du compte (identifiant d'une voix de `TextToSpeech.voices()`, validé par la passerelle) ; `AssistantCore.session_voice()` la transmet à la synthèse de la session (réponses, voix en streaming via `SpeechPipeline(voice=)`, question de confirmation), voix configurée si elle n'est plus installée ; `preview_voice` → `voice_preview` (phrase `TTS_VOICE_PREVIEW_TEXT`). **Historique persistant & multi-conversations** ([core/history.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/history.py), `AssistantCore.history`) : projet local, tout est conservé sans limite. Collection PocketBase `POCKETBASE_MESSAGES_COLLECTION` (un enregistrement par message : `user`, `conversation`, `turn`, `role`, `content`, `seq`, `tools`), règles par propriétaire appliquées avec le jeton du compte. Chaque `Session` a un `conversation_id` ; `restore_history()` recharge la dernière conversation ou la conversation demandée via `load_conversation(conversation_id)`, `list_conversations()` liste l'historique complet pour affichage dans le tiroir latéral, et `delete_conversation()` permet d'en effacer une. Écritures dans un seul fil d'arrière-plan (ordre conservé), numéros d'échange filtrés avant d'entrer dans un filtre PocketBase. Ni le jeton maître ni le micro « Foyer » ne sont enregistrés.
- **Appairage** ([core/pairing.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/pairing.py)) : au démarrage, `print_pairing()` affiche l'URL de l'interface avec le jeton dans le fragment (`/#token=...`, jamais envoyé au serveur) et son QR code (`segno`). `GATEWAY_PUBLIC_URL` impose l'adresse ; sinon `GATEWAY_TAILSCALE_URL` (défaut) reprend l'URL HTTPS de `tailscale serve` pointant sur le port de la passerelle, ou l'IP Tailscale si l'écoute est sur `0.0.0.0`, `GATEWAY_QR_ENABLED=false` le désactive. `app.js` (`consumePairingToken()`) mémorise le jeton (fragment ou `?token=`) puis l'efface de la barre d'adresse.
- **Lancement** : dans `main.py` (`GATEWAY_ENABLED=true`) ou seul, sans micro : `python -m gateway`. Client de test : `python -m gateway.client`.
- **Interface web / PWA** (`gateway/web/`, servie à la racine, publique car sans secret) : HTML/CSS/JS sans dépendance ni build. `app.js` (authentification intuitive et accessible : bouton « Connexion » dans la barre du haut, badge de statut cliquable, carte d'authentification sur l'accueil déconnecté, bouton de connexion/changement de compte dans les réglages, dialogue de connexion multi-onglets « Compte utilisateur » / « Jeton passerelle » avec boutons de fermeture/annulation et détection automatique via `GET /health` ; tiroir latéral des conversations, historique interactif, pastilles d'outils visuelles avec icônes contextuelles, statuts et détails, WebSocket, streaming, confirmation avec compte à rebours, lecture de la voix, choix du modèle Ollama et case « modèle de décision », formulaire « Paramètres avancés » généré d'après `settings_store.describe()`), `recorder.js` + `recorder-worklet.js` (capture micro AudioWorklet, fin de phrase avec les seuils `VOICE_THRESHOLD`/`SILENCE_DURATION` transmis dans le message `ready`, rééchantillonnage 16 kHz et encodage WAV dans le navigateur), `sw.js` (cache réseau d'abord du squelette uniquement). Le micro exige le HTTPS hors localhost : `tailscale serve --bg 8765`.
- **Édition de la conversation** : appui long (ou clic droit) sur une bulle : supprimer, relancer à partir d'elle, modifier. Le client numérote chaque échange (`turn`, repris dans les événements et l'historique : la fenêtre glissante empêche de se fier à la position). `forget` efface côté serveur, sous le verrou de session, et les messages sortis de la fenêtre (`Conversation.older`) y reviennent ; relancer envoie `forget` avec le nouveau message ; modifier une réponse (`edit_answer`) ne rappelle pas le LLM.
- **Durcissement** : `SecurityHeadersMiddleware` (CSP stricte : aucun script inline ni ressource externe) et `LocalOnlyMiddleware` (sans jeton, toute requête relayée par un proxy — `X-Forwarded-For`, `Tailscale-User-Login` — est refusée).

- **Redémarrage** ([core/restart.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/core/restart.py)) : message WS `restart` → événement `restarting` → SIGINT (arrêt normal de `main.py` ou de la passerelle) → `restart_if_requested()` relance `sys.orig_argv` dans le même processus. Le client se reconnecte seul.

### 2.10 [mcp_server.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/mcp_server.py) — Serveur MCP (Model Context Protocol) Universel
- **Technologie** : `mcp.server.mcpserver.MCPServer` (MCP 2.x).
- **Rôle** : Expose l'intégralité des briques logiques et physiques sous forme de standard MCP :
  - **Tools (16 outils)** : `execute_action`, `list_actions`, `set_volume`, `media_control`, `send_notification`, `open_application`, `lock_session`, `screen_off`, `system_power`, `tts_speak`, `play_feedback_sound`, `set_system_ducking`, `stt_transcribe_file`, `ask_assistant`, `get_conversation_history`, `clear_conversation_history`.
  - **Resources (4 ressources)** : `smarthome://status`, `smarthome://actions`, `smarthome://history`, `smarthome://config`.
  - **Prompts (2 prompts)** : `smarthome_assistant`, `smart_home_planner`.
  - **Multi-Transport** : Supporte `stdio` (local pour Claude Desktop, Cursor, Antigravity) et `sse`/`streamable-http` (accessible sur le réseau local ou distant).


---

## 🔄 3. Diagramme de la Machine à États

```mermaid
stateDiagram-v2
    [*] --> VEILLE_PASSIVE

    state VEILLE_PASSIVE {
        [*] --> EcouteWakeWord
        EcouteWakeWord --> EcouteWakeWord : Chunk analysé (score < seuil)
    }

    VEILLE_PASSIVE --> SESSION_ACTIVE : Mot-clé détecté (score >= seuil) -> ducker.duck() + Feedback Wake Word

    state SESSION_ACTIVE {
        [*] --> ECOUTE_VAD
        ECOUTE_VAD --> ENREGISTREMENT : Niveau > 700 et voix (Silero)
        ENREGISTREMENT --> TRANSCRIPTION : Silence >= 0.8s ou Max 12s
        TRANSCRIPTION --> GENERATION_LLM : Texte valide
        GENERATION_LLM --> SYNTHESE_TTS : Réponse prête
        SYNTHESE_TTS --> FEEDBACK_FIN_REPONSE : Lecture audio finie
        FEEDBACK_FIN_REPONSE --> ATTENTE_FOLLOW_UP : Ding / Carillon émis
        ATTENTE_FOLLOW_UP --> ECOUTE_VAD : Parole détectée (< 30s)
    }

    SESSION_ACTIVE --> VEILLE_PASSIVE : Timeout silence global (30s) -> Feedback Veille + ducker.unduck()
    SESSION_ACTIVE --> VEILLE_PASSIVE : « Au revoir » / outil sleep -> Feedback Veille + ducker.unduck()
```

---

## 🛠️ 4. Directives de Développement & Règles pour les Agents

Lors de toute intervention sur ce codebase, veillez à respecter les règles suivantes :

### 1. Préservation des Points d'Entrée de Test Autonomes
Chaque module Python (`config.py`, `wakeword.py`, `transcribe.py`, `stt.py`, `llm.py`, `providers.py`, `tts.py`, `speech.py`, `barge_in.py`, `vad.py`, `sentences.py`, `feedback.py`, `ducking.py`, `confirm.py`, `tools.py`, `events.py`, `agents.py`, `images.py`, `profiles.py`, `remote_voice.py`, `menu.py`, `wizard.py`, `restart.py`, `assistant.py`, `decision.py`, `settings_store.py`, `users.py`, `pocketbase.py`, `history.py`, `archive.py`, `test_sound.py`) **doit impérativement conserver son bloc `if __name__ == "__main__":`**. Ces blocs permettent un diagnostic isolé sans charger toute la pile applicative.



### 2. Gestion des Flux Audio & Synchronisation
- **Attention au Microphone Lock** : L'objet `stream` (`pyaudio.Stream`) est partagé entre la détection de wake word et le transcripteur. Veillez à ne pas ouvrir plusieurs flux concurrents sur le même device audio sous Linux (risque de conflit ALSA/PulseAudio).
- **Purge de Buffer** : Toujours appeler `_flush_stream()` après une synthèse vocale ou avant un nouvel enregistrement pour éviter de réinjecter l'écho du TTS dans le STT.

### 3. Gestion des Modèles & Formats
- Les modèles de mot-clé doivent être placés dans le dossier `wakewords/` et chargés sous forme de fichiers ONNX compatibles avec OpenWakeWord.
- Pour Whisper, privilégiez `device="cpu"` et `compute_type="int8"` pour garantir une compatibilité universelle sur tout CPU moderne sans surcharger la mémoire vidéo du LLM.

### 4. Ajout d'un Fournisseur (LLM / STT / TTS)
- Créer une classe héritant de `LLMProvider`, `STTProvider` ou `TTSProvider`, prenant `settings: Settings` en constructeur, et la décorer avec `@LLM_PROVIDERS.register("nom")` (resp. `STT_PROVIDERS`, `TTS_PROVIDERS`).
- Importer les dépendances lourdes dans le constructeur (chargement paresseux), lever une exception en cas d'échec (l'appelant la convertit en message ⚠️), et ne jamais ajouter de `if PROVIDER == ...` ailleurs dans le code.

### 5. Centralisation des Variables & Configuration
- **Aucune variable de paramétrage ne doit être écrite en dur** directement dans les fonctions ou classes.
- Déclarez toujours les nouvelles variables dans `.env.example`, `.env` et comme champ typé (avec valeur par défaut et contraintes) du modèle `Settings` de `config.py`.

### 6. Accès Git
- La connexion à GitHub se fait **uniquement en SSH** : `origin` est `git@github.com:suissard/SmartHome.git`. Ne jamais utiliser l'URL HTTPS ni un jeton.


---

## 🚀 5. Roadmap Technique & Perspectives d'Évolution

Pour les futures évolutions du projet, les axes prioritaires sont :

1. **Intégration Domotique (Home Assistant)** :
   - Le *Function Calling* est en place (`core/tools.py`) : activer le serveur MCP Home Assistant dans `mcp_servers.json` suffit pour que ses outils soient proposés au LLM.
2. **Streaming Pipeline** : ✅ en place (parole phrase par phrase, ~2 s gagnées avant la première parole).
3. **Barge-in / Annulation d'Écho Acoustique (AEC)** :
   - ✅ Interruption par mot-clé (local) et par le bouton micro (PWA).
   - Reste : barge-in « à la voix » sans casque, via le module PipeWire `echo-cancel` comme source micro.
4. **Multi-room / MQTT Audio Satellite** :
   - Déporter la capture audio vers des satellites ESP32 / Raspberry Pi via protocole léger (ex: Wyoming / MQTT).
