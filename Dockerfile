# syntax=docker/dockerfile:1
# Image de SmartHome : Python + dépendances + outils des actions. Le dépôt est monté sur /app par compose.yaml
# (code, .env, profils, data/, voix, PocketBase) : l'image ne change qu'avec requirements.txt ou ce fichier.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential portaudio19-dev \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip wheel \
 && pip install --no-cache-dir -r /tmp/requirements.txt
# Modèles openWakeWord (analyse audio + VAD Silero) : dans site-packages, non inscriptible à l'exécution
RUN python -c "import openwakeword.utils as u; getattr(u, 'download_models', lambda: None)()"

FROM python:${PYTHON_VERSION}-slim-bookworm
# PortAudio + plugin ALSA PulseAudio (micro et voix), pactl (ducking), amixer, playerctl (médias),
# notify-send, dbus-send (verrouillage, bus de session de l'hôte), curl (santé d'Ollama / PocketBase), git (version affichée)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libportaudio2 libsndfile1 libasound2-plugins pulseaudio-utils alsa-utils \
        playerctl libnotify-bin brightnessctl dbus procps curl ca-certificates openssl git tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/venv /opt/venv
COPY docker/asound.conf /etc/asound.conf
# HOME accessible à tout UID (le conteneur tourne avec l'UID de l'utilisateur de l'hôte) : cache des modèles Whisper
RUN mkdir -p /home/smarthome && chmod 1777 /home/smarthome
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/smarthome \
    SMARTHOME_IN_DOCKER=1
WORKDIR /app
COPY . /app
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "core.cli", "start", "--no-menu"]
