# 🚀 Mise en service — PC & smartphone Android

Ce guide amène SmartHome de zéro à « je parle à mon PC depuis mon téléphone ». Comptez environ 30 minutes.
Il suppose un PC sous **Linux** (Ubuntu / Debian, PipeWire ou PulseAudio) et un téléphone **Android avec Chrome**.

| Étape | Où | Résultat |
| :--- | :--- | :--- |
| 1. Installer | PC | L'assistant répond au micro du PC |
| 2. Ouvrir la passerelle | PC | Le PC accepte des clients authentifiés |
| 3. Relier par Tailscale | PC + téléphone | Accès HTTPS privé, à la maison comme dehors |
| 4. Installer l'appli | Téléphone | Icône SmartHome sur l'écran d'accueil |

---

## 1. 🖥️ Côté PC : installer et tester l'assistant

### 1.1 Prérequis

```bash
sudo apt update
sudo apt install -y python3-venv python3-pyaudio portaudio19-dev libasound2-dev
```

Installer [Ollama](https://ollama.com) (le cerveau local), puis le modèle configuré par défaut :

```bash
ollama pull gemma4:12b
```

> 💡 PC modeste (pas de carte graphique, 8 Go de RAM) : prenez `qwen2.5:7b` et mettez `OLLAMA_MODEL=qwen2.5:7b` dans `.env`.
> Sans GPU du tout, vous pouvez aussi utiliser OpenRouter (cloud) : `LLM_PROVIDER=openrouter` + `OPENROUTER_API_KEY`.

### 1.2 Installation

```bash
cd SmartHome
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Télécharger les modèles de base d'openWakeWord (analyse audio et détecteur de voix Silero) :

```bash
python -c "import openwakeword.utils; openwakeword.utils.download_models()"
```

Créer la configuration :

```bash
cp .env.example .env
```

Les voix Piper (`voices/`) et les mots-clés (`wakewords/`, « Salut Jarvis » par défaut) sont fournis avec le projet.

### 1.3 Vérifier le micro et le haut-parleur

```bash
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Si le bon micro n'est pas celui par défaut, notez son numéro et renseignez `AUDIO_INPUT_DEVICE_INDEX` (et `AUDIO_OUTPUT_DEVICE_INDEX` pour la sortie) dans `.env`.

Tests rapides, brique par brique :

```bash
python audio/vad.py
```
Parlez, puis faites du bruit sans parler : la barre « parole » ne doit monter que pour la voix (Ctrl+C pour quitter).

```bash
python audio/wakeword.py
```
Dites « Salut Jarvis » : le score doit dépasser 0,5.

### 1.4 Premier lancement

```bash
python main.py
```

Le récapitulatif de démarrage liste le LLM, le STT, la voix et les outils actifs. Ensuite :

1. Dites **« Salut Jarvis »** → l'assistant répond « Que puis-je pour toi ? ».
2. Posez une question ou donnez un ordre (« mets le volume à 30 »).
3. Enchaînez sans répéter le mot-clé tant que la barre de veille active défile.
4. **« Au revoir »** ou **« c'est tout »** le remet en veille ; redire le mot-clé pendant qu'il parle lui coupe la parole.

> En cas de son système resté bas après un arrêt brutal : `python main.py --reset-sound`.

---

## 2. 🔐 Côté PC : ouvrir la passerelle au téléphone

Générer un jeton secret (c'est le « mot de passe » du téléphone) :

```bash
openssl rand -hex 32
```

Dans `.env` :

```ini
GATEWAY_ENABLED=true
GATEWAY_HOST=127.0.0.1
GATEWAY_PORT=8765
GATEWAY_AUTH_TOKEN=<le jeton généré>
```

`GATEWAY_HOST` reste sur `127.0.0.1` : c'est Tailscale (étape 3) qui fera le lien chiffré jusqu'au téléphone.
Relancez `python main.py` : la ligne `Passerelle : ws://127.0.0.1:8765/ws (jeton requis)` doit apparaître.

> PC sans micro (serveur, mini-PC) : `python -m gateway` lance uniquement la passerelle, sans écoute locale.

---

## 3. 🌐 Relier le PC et le téléphone avec Tailscale

Tailscale crée un réseau privé chiffré entre vos appareils, qui marche aussi en 4G/5G hors de chez vous.
Le navigateur du téléphone n'autorise le micro qu'en **HTTPS** : `tailscale serve` le fournit, avec un vrai certificat.

### 3.1 Sur le PC

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Connectez-vous avec le lien affiché. Puis, dans la [console Tailscale](https://login.tailscale.com/admin/dns) → **DNS** :
activez **MagicDNS** et **HTTPS Certificates**.

Publiez la passerelle sur votre réseau Tailscale :

```bash
sudo tailscale serve --bg 8765
```

```bash
tailscale serve status
```

Notez l'adresse affichée, de la forme `https://<nom-du-pc>.<votre-tailnet>.ts.net`.
La publication survit aux redémarrages ; pour l'arrêter : `sudo tailscale serve reset`.

> 💡 Pour éviter `sudo` à chaque fois : `sudo tailscale set --operator=$USER`.

### 3.2 Sur le téléphone Android

1. Installez **Tailscale** depuis le Play Store.
2. Connectez-vous avec **le même compte** que sur le PC et activez le VPN Tailscale.
3. Dans l'appli Tailscale, le PC doit apparaître dans la liste des appareils.

---

## 4. 📱 Côté téléphone : installer l'application SmartHome

1. Ouvrez **Chrome** et allez à l'adresse notée à l'étape 3.1 (`https://<nom-du-pc>.<tailnet>.ts.net`).
2. Saisissez le **jeton** de l'étape 2 (il est mémorisé ensuite).
3. Menu **⋮** → **Installer l'application** (ou **Ajouter à l'écran d'accueil**).
4. Ouvrez SmartHome depuis l'icône, touchez le **bouton micro** et **autorisez le micro** quand Chrome le demande.

Utilisation :

- **Touchez le micro** et parlez : l'envoi est automatique en fin de phrase. Ou tapez votre demande au clavier.
- La réponse s'affiche en direct et est lue à voix haute par le téléphone, phrase par phrase.
- **Toucher le micro pendant qu'il parle** lui coupe la parole.
- Les actions sensibles (extinction, redémarrage) demandent une **confirmation à l'écran**.

---

## 5. ⚙️ Option : démarrage automatique du PC

Pour que SmartHome se lance à l'ouverture de session, créez `~/.config/systemd/user/smarthome.service` (adaptez le chemin) :

```ini
[Unit]
Description=Assistant vocal SmartHome
After=pipewire.service

[Service]
WorkingDirectory=/chemin/vers/SmartHome
ExecStart=/chemin/vers/SmartHome/.venv/bin/python main.py
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now smarthome
```

Journal en direct : `journalctl --user -u smarthome -f`. Service *utilisateur* (et non système) : il a ainsi accès au son de votre session.

---

## 🩺 Dépannage

| Symptôme | Piste |
| :--- | :--- |
| Le mot-clé n'est jamais détecté | `python audio/wakeword.py` ; vérifier `AUDIO_INPUT_DEVICE_INDEX`, baisser `WAKEWORD_THRESHOLD` (ex. 0.4). |
| Il ne m'entend pas quand je parle doucement | Baisser `VOICE_THRESHOLD` (ex. 400) ou `VAD_SPEECH_THRESHOLD` (ex. 0.4). |
| Il reste en écoute à cause du bruit | `python audio/vad.py` pour voir ce qui est pris pour de la voix ; monter `VAD_SPEECH_THRESHOLD` (ex. 0.6). Dire « stop » remet en veille. |
| Réponses lentes | Modèle plus léger (`OLLAMA_MODEL=qwen2.5:7b`), `WHISPER_MODEL=base`. Vérifier `ollama ps` (GPU utilisé ?). |
| Le téléphone affiche « hors ligne » | Tailscale actif sur les deux appareils ? `python main.py` lancé avec `GATEWAY_ENABLED=true` ? `tailscale serve status` ? |
| Jeton refusé | Le jeton saisi doit être identique à `GATEWAY_AUTH_TOKEN` ; le changer via la roue crantée de l'appli. |
| Le bouton micro est grisé | L'appli n'est pas connectée : voir la pastille d'état en haut (« Hors ligne », « Jeton requis »). |
| « Le micro exige une connexion sécurisée (HTTPS) » | Ouvrir l'adresse `https://…ts.net` donnée par `tailscale serve status`, pas une adresse `http://` ou une IP. |
| « Accès au micro refusé » | Chrome → icône à gauche de l'adresse → Autorisations → Micro → Autoriser. |
| Une action dangereuse est refusée depuis le téléphone | Normal sans réponse à la confirmation dans les `GATEWAY_CONFIRM_TIMEOUT` secondes (20 par défaut). |

> 🔒 Sécurité : le jeton donne le contrôle du PC. Ne le partagez pas ; en cas de doute, générez-en un nouveau et redémarrez SmartHome.
