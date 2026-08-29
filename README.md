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
├── voice.onnx          # Modèle de voix français pour Piper TTS
├── voice.onnx.json     # Configuration phonétique et échantillonnage de la voix
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

### 1. Prérequis Système

- **Système d'exploitation** : Linux (testé sur Ubuntu / Debian) ou macOS / Windows avec support PortAudio.
- **Python** : Version 3.10 ou supérieure.
- **Bibliothèques audio système** (sous Ubuntu/Debian) :
  ```bash
  sudo apt update
  sudo apt install -y python3-pyaudio portaudio19-dev libasound2-dev espeak-ng
  ```
- **Ollama** : Pour exécuter le modèle LLM en local.
  - Installer Ollama : [ollama.com](https://ollama.com)
  - Télécharger le modèle par défaut :
    ```bash
    ollama pull qwen2.5:7b
    ```

### 2. Installation de l'environnement virtuel & Configuration

```bash
# Cloner le dépôt et se placer dans le dossier
git clone <url-du-repo> SmartHome
cd SmartHome

# Créer et activer l'environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# Installer les dépendances Python
pip install --upgrade pip
pip install -r requirements.txt

# Initialiser votre fichier de configuration d'environnement
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
| **Configuration** | `python config.py` | Affiche l'ensemble des variables chargées depuis `.env`. |
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
TTS_MODEL_PATH=voice.onnx
TTS_CONFIG_PATH=voice.onnx.json
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

## 🛡️ Licence & Contribution

Projet développé pour un contrôle domotique intelligent et respectueux des données personnelles.
Les contributions, suggestions et améliorations de modèles sont les bienvenues !
