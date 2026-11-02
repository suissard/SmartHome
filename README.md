# 🏠 SmartHome — Assistant Vocal Domotique 100% Local & Privé

SmartHome est un assistant vocal intelligent, modulaire, ultra-réactif et entièrement exécuté en local (*privacy-first*, aucune dépendance au cloud). Il transforme un ordinateur ou un serveur domestique en un majordome vocal capable d'écouter un mot-clé de réveil (*wake word*), de transcrire la parole, de raisonner via un modèle de langage (LLM) et de répondre vocalement avec une intonation naturelle.

---

## 🌟 Points Forts & Fonctionnalités

- **🔒 100% Souverain ou Cloud Flexible** : Choisissez une exécution 100% hors-ligne (local) ou basculez facilement vers **OpenRouter** pour le LLM, le STT et le TTS via `.env`.
- **⚡ Détection de Mot-Clé Instantanée** : Propulsé par **openWakeWord** (modèles ONNX légers et optimisés).
- **🎙️ Transcription Vocale (STT)** : Support de **faster-whisper** en local (CPU/GPU) ou **OpenRouter / Whisper API** en cloud, avec VAD temps réel.
- **🧠 Intelligence & Raisonnement (LLM)** : Connecté au choix à **Ollama** en local (`qwen2.5:7b`, `gemma`, etc.) ou à **OpenRouter** (`meta-llama/llama-3.3-70b-instruct`, `gpt-4o-mini`, `claude-3.5-sonnet`, `gemini-2.5-flash`, etc.).
- **🔊 Synthèse Vocale Fluide (TTS)** : Basé sur **Piper TTS** (moteur neural ONNX local) ou **OpenRouter Speech API** avec traitement post-audio (atténuation des clics/pops et fondu progressif).
- **🔔 Signaux Sonores & Retours Vocaux** : Accords harmoniques, carillons (*ding* de fin de phrase), et phrases personnalisables (*"Que puis je pour toi ?"*, *"Bisous a plus tard"*).
- **⚡ Réponse Vocale en Streaming** : l'assistant commence à parler dès la première phrase générée, pendant que le LLM écrit la suite.
- **✋ Barge-in** : redites le mot-clé pendant qu'il parle (ou touchez le micro sur le téléphone) pour lui couper la parole et enchaîner.
- **💤 Fin de conversation** : dites « au revoir », « c'est tout » ou « stop » (liste `CONVERSATION_END_PHRASES`) pour le remettre en veille aussitôt ; les formulations libres (« je vais me coucher ») passent par l'outil `sleep` du LLM.
- **🔇 Résistant au bruit** : la détection de voix Silero (locale) ignore ventilateur, musique ou claquements ; les phrases inventées par Whisper dans le bruit sont écartées (`VAD_ENGINE`, `STT_IGNORED_PHRASES`). Testez votre micro avec `python audio/vad.py`.
- **💬 Mode Conversation Suivie (*Follow-up*)** : Après le réveil par mot-clé, l'assistant reste en veille active pendant 30 secondes pour enchaîner les questions sans répéter le mot d'activation.

---

## 🏗️ Architecture & Flux de Données

```
                  ┌────────────────────────────────────────┐
                  │          Microphone (PyAudio)          │
                  └───────────────────┬────────────────────┘
                                      │  Flux Audio (16kHz / 16-bit Mono)
                                      ▼
                        ┌───────────────────────────┐
                        │   1. Détection Wake Word  │ ◄── openWakeWord
                        │     (wakeword.py)         │     (ex: "Salut Jarvis")
                        └─────────────┬─────────────┘
                                      │  Mot-clé détecté ! ──► Signal / Phrase Réveil
                                      ▼
                        ┌───────────────────────────┐
                        │    2. Écoute & STT        │ ◄── faster-whisper (CPU int8)
                        │     (transcribe.py)       │     + VAD & pré-buffer circulaire
                        └─────────────┬─────────────┘
                                      │  Texte transcrit
                                      ▼
                        ┌───────────────────────────┐
                        │    3. Cerveau LLM         │ ◄── Ollama API (Local)
                        │     (llm.py)              │     (Qwen 2.5 7B - Prompt concis)
                        └─────────────┬─────────────┘
                                      │  Réponse textuelle
                                      ▼
                        ┌───────────────────────────┐
                        │    4. Synthèse Vocale     │ ◄── Piper TTS (ONNX)
                        │     (tts.py)              │     + Traitement audio (Fade-out)
                        └─────────────┬─────────────┘
                                      │  Lecture audio + Ding de fin de tour
                                      ▼
                  ┌────────────────────────────────────────┐
                  │        Haut-Parleurs (SoundDevice)     │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                 [ Fenêtre de conversation active (30s) ]
                     ├── Nouvelle question ? ──► Retour à l'étape 2
                     └── Timeout silence ──────► Phrase/Signal Veille ──► Veille Mot-Clé
```

---

## 📁 Structure du Projet

```text
SmartHome/
├── .env                # Fichier de variables d'environnement actif
├── .env.example        # Modèle de configuration documenté
├── .env.exemple        # Alias du modèle de configuration
├── config.py           # Chargeur centralisé et typé de la configuration
├── main.py             # Orchestrateur principal & boucle événementielle
├── wakeword.py         # Module de détection du mot-clé (openWakeWord)
├── transcribe.py       # Module de capture micro & transcription (faster-whisper)
├── llm.py              # Connecteur LLM local via Ollama (qwen2.5:7b)
├── tts.py              # Synthèse vocale neuronale locale (Piper TTS)
├── feedback.py         # Signaux sonores (procéduraux/WAV) et retours vocaux
├── test_sound.py       # Script utilitaire de diagnostic audio (SoundDevice)
├── voices/             # Modèles de voix neuronales Piper (.onnx / .onnx.json)
│   ├── fr_FR-siwis-medium.onnx
│   ├── fr_FR-upmc-medium.onnx
│   └── fr_FR-tom-medium.onnx
├── wakewords/          # Modèles de mots-clés entraînés (.onnx / .tflite)
│   ├── Salut_Jarvisse_20260601_005854.onnx
│   ├── Hé_jarvisse_64x3_115000_20260811_124036.onnx
│   ├── Jarvis_20260729_231312.onnx
│   └── hey_smarthome_20260716_200659.onnx
├── requirements.txt    # Liste des dépendances Python
├── AGENTS.md           # Guide d'architecture et consignes pour agents de code
└── README.md           # Documentation générale du projet
```

---

## 🚀 Installation & Prérequis

> 📘 Pas à pas complet, du PC jusqu'à l'appli sur un téléphone Android : [docs/MISE_EN_SERVICE.md](docs/MISE_EN_SERVICE.md).

### Installation automatique (recommandée)

Un script installe tout : paquets système, environnement Python, dépendances, `.env`, modèles (openWakeWord, Whisper, Ollama) et, en option, le démarrage automatique. Il peut être relancé sans risque (le `.env` existant est conservé).

**Linux / macOS** (Debian/Ubuntu, Fedora, Arch, openSUSE, Homebrew) :

```bash
git clone <url-du-repo> SmartHome && cd SmartHome
./install.sh
./start.sh
```

**Windows 10/11** (PowerShell ; Python et Ollama installés via `winget` si absents) :

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\start.ps1
```

**Serveur sans micro** (passerelle seule, écoute réseau, jeton `GATEWAY_AUTH_TOKEN` généré dans `.env`) :

```bash
./install.sh --server --service      # service systemd smarthome.service
```

| Option (`install.sh` / `install.ps1`) | Effet |
| :--- | :--- |
| `--server` / `-Server` | Passerelle seule (`python -m gateway`), `GATEWAY_HOST=0.0.0.0`, jeton généré |
| `--service` / `-Service` | Démarrage automatique : service systemd (utilisateur en poste, système en serveur) ou tâche planifiée Windows |
| `--host` / `-GatewayHost` | Adresse d'écoute de la passerelle en mode serveur |
| `--python` / `-Python` | Interpréteur Python à utiliser (≥ 3.10) |
| `--no-system-deps` / `-NoSystemDeps` | Ne rien installer au niveau système |
| `--no-ollama` / `-NoOllama` | Ni Ollama ni modèle LLM (ex : `LLM_PROVIDER=openrouter`) |
| `--no-models` / `-NoModels` | Aucun téléchargement de modèle |
| `-y` / `-Yes` | Répondre oui à tout (installation non interactive) |

Les modèles Ollama téléchargés sont ceux du `.env` (`OLLAMA_MODEL`, et `OLLAMA_STT_MODEL` / `OLLAMA_TTS_MODEL` si ces fournisseurs sont choisis) : modifiez-le avant de relancer le script pour en changer.

> ⚠️ Sous Windows, l'assistant, la voix et la passerelle fonctionnent, mais les actions système (volume, verrouillage, applications…) et le ducking reposent sur des scripts bash et `pactl` propres à Linux.

### Installation manuelle

- **Python** 3.10 ou supérieur, et sous Ubuntu/Debian :
  ```bash
  sudo apt update
  sudo apt install -y python3-venv python3-dev portaudio19-dev libasound2-dev libsndfile1
  ```
- **Ollama** ([ollama.com](https://ollama.com)) puis le modèle du `.env` : `ollama pull gemma4:12b`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

---

## 🎮 Utilisation

### Démarrer l'assistant complet

```bash
python main.py
```

1. Prononcez le mot-clé d'activation (ex : **« Salut Jarvis »**).
2. L'assistant confirme la détection (phrase configurée ex: *« Que puis je pour toi ? »* ou carillon sonore) et passe en écoute active 🎤.
3. Posez votre question (ex : *« Quel temps fait-il aujourd'hui ? »*).
4. L'assistant analyse, génère sa réponse via le LLM et vous répond à haute voix 🔊.
5. Un discret signal sonore (*ding*) retentit à la fin de sa phrase pour vous indiquer que vous pouvez réenchaîner.
6. Une barre d'écoulement dynamique s'affiche (durée paramétrable via `FOLLOW_UP_TIMEOUT` dans `.env`, ex: 10s ou 30s) : vous pouvez enchaîner directement sans répéter le mot-clé. Si aucune parole n'est détectée à l'issue de l'écoulement, l'assistant énonce sa phrase de fin (ex: *« Bisous a plus tard »*) et repasse en veille.

---

## 🧪 Tests Unitaires des Composants

Chaque fichier peut être exécuté de manière autonome pour tester et régler chaque brique individuellement :

| Composant | Commande de test | Objectif du test |
| :--- | :--- | :--- |
| **Configuration** | `python core/config.py` | Affiche et valide l'ensemble des variables chargées (environnement > `.env`). |
| **Fournisseurs** | `python core/providers.py` | Liste les fournisseurs LLM / STT / TTS disponibles. |
| **Audio / Sortie** | `python test_sound.py` | Liste les périphériques et joue un bip de contrôle. |
| **Mot-Clé** | `python wakeword.py` | Affiche un VU-mètre en direct et le score de détection. |
| **Transcription** | `python transcribe.py` | Enregistre au micro et transcrit votre voix en texte. |
| **LLM (Ollama)** | `python llm.py` | Ouvre un chat textuel dans le terminal avec le modèle. |
| **Synthèse (TTS)** | `python tts.py` | Demande une phrase au clavier et la prononce vocalement. |
| **Feedbacks & Sons** | `python feedback.py` | Teste les sons procéduraux (chimes, ding, beep) et les retours configurés. |

---

## ⚙️ Configuration & Personnalisation (.env)

Toutes les variables sont désormais centralisées dans le fichier `.env` (géré par [config.py](file:///home/suissard/PROGRAMMATIONS/SmartHome/config.py)).

### Exemple de configuration `.env` :

```ini
# --- Fournisseurs de Services (ollama / whisper / piper OU openrouter) ---
LLM_PROVIDER=ollama
STT_PROVIDER=whisper
TTS_PROVIDER=piper

# --- Configuration OpenRouter (si activé) ---
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct
OPENROUTER_STT_MODEL=openai/whisper-large-v3
OPENROUTER_TTS_MODEL=openai/tts-1
OPENROUTER_TTS_VOICE=nova

# --- Paramètres Audio ---
AUDIO_RATE=16000
AUDIO_CHUNK=1280
AUDIO_INPUT_DEVICE_INDEX=
AUDIO_OUTPUT_DEVICE_INDEX=

# --- Wake Word ---
WAKEWORD_MODEL_PATH=wakewords/Salut_Jarvisse_20260601_005854.onnx
WAKEWORD_THRESHOLD=0.5

# --- Transcription Locale (Whisper) ---
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
VOICE_THRESHOLD=700
SILENCE_DURATION=0.8
FOLLOW_UP_TIMEOUT=30.0

# --- Cerveau LLM Local (Ollama) ---
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_HOST=http://localhost:11434
LLM_SYSTEM_PROMPT="Tu es un assistant vocal domotique. Réponds en français de manière claire, concise et directe (1 à 2 phrases max)."
LLM_STREAM=true

# --- Synthèse Vocale Locale (Piper TTS) ---
TTS_VOICE=fr_FR-siwis-medium
TTS_SPEECH_SPEED=1.15

# --- Signaux Sonores & Retours Vocaux ---
FEEDBACK_WAKEWORD_TYPE=phrase
FEEDBACK_WAKEWORD_TEXT="Que puis je pour toi ?"
FEEDBACK_WAKEWORD_SOUND=wake

FEEDBACK_RESPONSE_END_TYPE=sound
FEEDBACK_RESPONSE_END_SOUND=ding
FEEDBACK_RESPONSE_END_TEXT=

FEEDBACK_TIMEOUT_TYPE=phrase
FEEDBACK_TIMEOUT_TEXT="Bisous a plus tard"
FEEDBACK_TIMEOUT_SOUND=sleep

FEEDBACK_SOUND_VOLUME=0.5
```

---

## 🌍 Accès Distant (LAN & Tailscale)

La passerelle permet de parler à SmartHome depuis un autre appareil : **application web installable (PWA)** sur téléphone, client console, ou API HTTP. Réponse en streaming, voix synthétisée renvoyée à l'appareil, confirmation des actions dangereuses à l'écran.

### Téléphone (recommandé) : `tailscale serve`
Le micro d'un navigateur exige le HTTPS : `tailscale serve` le fournit (certificat automatique) en relayant la passerelle restée en local.

1. Générer un jeton et le placer dans `.env` (`GATEWAY_AUTH_TOKEN=<jeton>`, `GATEWAY_ENABLED=true`, `GATEWAY_HOST=127.0.0.1`) :
   ```bash
   openssl rand -hex 32
   ```
2. Lancer SmartHome (`python main.py`, ou `python -m gateway` sans micro), puis publier la passerelle sur le tailnet :
   ```bash
   tailscale serve --bg 8765
   ```
   (`tailscale serve status` affiche l'adresse `https://<machine>.<tailnet>.ts.net`, `tailscale serve reset` arrête la publication ; MagicDNS et HTTPS doivent être activés dans la console Tailscale.)
3. Sur le téléphone (connecté à Tailscale), ouvrir cette adresse, saisir le jeton, puis « Ajouter à l'écran d'accueil ».

Sans jeton configuré, la passerelle refuse toute requête relayée par un proxy : `tailscale serve` ne peut donc pas ouvrir l'accès à tout le tailnet par erreur.

### Choisir le modèle et régler l'assistant depuis l'interface
Dans **Réglages** : liste des modèles Ollama installés (avec leurs capacités), case **Modèle de décision**, puis **Paramètres avancés…** pour le prompt, l'historique, la voix, l'écoute, les retours sonores et les actions. Les valeurs sont enregistrées dans `.env` ; celles marquées « au redémarrage » s'appliquent au prochain lancement. Les secrets (clés, jetons) et l'adresse réseau ne sont jamais exposés.

**Modèles de décision** (ex: `ollama pull nimble`) : ils ne rédigent pas de réponse, ils choisissent la commande et ses arguments parmi des choix fermés (~0,5 s par commande). L'assistant prononce alors le message de confirmation de la commande (« Volume 30 %. », « J'ouvre le navigateur web. », l'état de la machine pour `system_info`…), ou « Je n'ai pas compris la commande. ». Chaque action déclare son message (`done_message`) ; il se remplace dans `LLM_DECISION_MESSAGES` (JSON, ex: `{"volume": "C'est parti, volume ${ARGS}."}`, modifiable dans les paramètres avancés). Variables : `${COMMAND}`, `${ARGS}`, `${OUTPUT}`, `${TOOL}`. Sans message, réponse type : « Commande ${COMMAND} initiée avec ${ARGS}. ». Seules les commandes dont les arguments ont des valeurs fermées leur sont proposées (une notification au texte libre, par exemple, ne l'est pas). Test en console : `python llm/decision.py`.

### Client console / script
Avec `GATEWAY_HOST` sur l'IP Tailscale (`tailscale ip -4`) ou derrière `tailscale serve` :
```bash
python -m gateway.client --url ws://100.x.y.z:8765/ws --token <jeton>
```

## 🔌 Serveur MCP Universel (Model Context Protocol)

SmartHome expose l'ensemble de ses fonctionnalités sous forme d'un **serveur MCP standardisé** (`mcp_server.py`), compatible avec tous les clients IA modernes (Claude Desktop, Antigravity IDE, Cursor, VS Code, Home Assistant, agents distants et scripts automatisés).

### 🚀 Lancement du serveur MCP

```bash
# 1. Mode Standard I/O (Local pour Claude Desktop, Cursor, Antigravity)
python mcp_server.py --transport stdio

# 2. Mode Serveur Réseau SSE (Accessible sur le LAN / Home Assistant)
python mcp_server.py --transport sse --host 0.0.0.0 --port 8000

# 3. Mode HTTP Streamable
python mcp_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

### ⚙️ Configuration Client (Claude Desktop / Cursor / Antigravity)

Ajoutez cette configuration dans votre fichier `claude_desktop_config.json` ou dans vos paramètres MCP :

```json
{
  "mcpServers": {
    "smarthome": {
      "command": "/home/suissard/PROGRAMMATIONS/SmartHome/.venv/bin/python",
      "args": [
        "/home/suissard/PROGRAMMATIONS/SmartHome/mcp_server.py",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### 🛠️ Outils Disponibles (MCP Tools)

| Outil MCP | Description |
| :--- | :--- |
| `list_actions` | Liste l'ensemble des commandes système avec description et exemples. |
| `execute_action(tag, args, dry_run)` | Exécute dynamiquement n'importe quelle commande par son tag. |
| `set_volume(volume)` | Règle le volume sonore (0-100, up, down, mute, unmute). |
| `media_control(command)` | Contrôle le lecteur multimédia MPRIS (play-pause, next, previous, stop). |
| `send_notification(message, title)` | Affiche une notification visuelle sur le bureau. |
| `open_application(app_name)` | Ouvre une application par son nom (ex: firefox, code, spotify, terminal). |
| `lock_session` | Verrouille immédiatement la session utilisateur. |
| `screen_off` | Met les écrans en veille (DPMS off). |
| `system_power(action)` | Éteint (`shutdown`) ou redémarre (`reboot`) l'ordinateur. |
| `tts_speak(text)` | Prononce une phrase à haute voix via Piper TTS ou OpenRouter. |
| `play_feedback_sound(sound_name)` | Joue un carillon ou son procédural (`wake`, `ding`, `sleep`, `beep`, `pop`). |
| `set_system_ducking(duck, volume_percent)` | Atténue ou rétablit le son des applications tierces. |
| `stt_transcribe_file(audio_path)` | Transcrit un fichier audio local en texte via Whisper. |
| `ask_assistant(prompt, execute_actions, speak_response)` | Dialogue avec le LLM, exécute les actions détectées et peut vocaliser. |
| `get_conversation_history` | Récupère l'historique des échanges en mémoire. |
| `clear_conversation_history` | Réinitialise la mémoire conversationnelle. |

### 📦 Ressources & Prompts MCP

- **Ressources** : `smarthome://status`, `smarthome://actions`, `smarthome://history`, `smarthome://config`.
- **Prompts** : `smarthome_assistant` (prompt système complet avec commandes), `smart_home_planner` (générateur de scénarios domotiques).

---

## 🛡️ Licence & Contribution

Projet développé pour un contrôle domotique intelligent et respectueux des données personnelles.
Les contributions, suggestions et améliorations de modèles sont les bienvenues !
